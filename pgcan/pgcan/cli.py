"""命令行入口。

典型用法::

    # 1) 月度客座率（Eurostat，官方座位数+旅客数，唯一免费的真值来源）
    python -m pgcan monthly

    # 2) 看看 DGAC 那份文件到底长什么样（列名年年在变）
    python -m pgcan dgac-inspect

    # 3) DGAC 逐月、分方向的旅客数（1990 年起，历史最长）
    python -m pgcan dgac

    # 4) 未来 180 天逐日满座探测 -> 周度紧张度（需要 Amadeus 免费 key）
    export AMADEUS_CLIENT_ID=... AMADEUS_CLIENT_SECRET=...
    python -m pgcan weekly --start 2026-09-01 --days 180
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import analyze, capacity, config

OUT = Path(__file__).resolve().parent.parent / "out"


def _setup(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    OUT.mkdir(parents=True, exist_ok=True)


def cmd_monthly(args) -> int:
    from . import eurostat

    records = eurostat.fetch()
    if not records:
        print(
            "没取到 Eurostat 数据。可能原因：\n"
            "  - 你的网络到 ec.europa.eu 不通\n"
            "  - airp_pr 代码变了，跑 `python -m pgcan probe-codes` 找找看",
            file=sys.stderr,
        )
        return 1

    raw = eurostat.to_monthly_frame(records)
    raw = capacity.attach_capacity(raw)
    monthly = analyze.monthly_load_factor(raw)

    raw.to_csv(OUT / "eurostat_raw.csv", index=False)
    monthly.to_csv(OUT / "monthly.csv", index=False)
    print(f"逐月序列 {len(monthly)} 行 -> {OUT/'monthly.csv'}")

    if monthly.empty:
        print("拿到了旅客数但没有座位数，无法算客座率。"
              "先看 eurostat_raw.csv 里有哪些 tra_meas。")
        return 0

    seasonal = analyze.seasonal_index(monthly)
    if not seasonal.empty:
        seasonal.to_csv(OUT / "seasonal.csv", index=False)
        print(f"\n季节指数（>1 = 比全年平均更满）-> {OUT/'seasonal.csv'}")
        print(
            seasonal[
                ["month_cn", "seasonal_index", "mean_load_factor", "n_years"]
            ].to_string(index=False)
        )

    chart = analyze.plot_monthly(monthly, seasonal, OUT / "monthly.png")
    if chart:
        print(f"\n图表 -> {chart}")
    return 0


def cmd_probe_codes(args) -> int:
    """在整份 TSV 里找出所有含 ZGGG / 广州的 airp_pr 代码。"""
    from . import eurostat

    try:
        records = eurostat.fetch_via_bulk(grep=args.grep)
    except Exception as exc:
        print(f"批量文件下载失败: {exc}", file=sys.stderr)
        return 1
    codes = sorted({r.get("airp_pr", "") for r in records})
    if not codes:
        print(f"批量文件里没有匹配 {args.grep!r} 的航线")
        return 1
    print(f"匹配到的 airp_pr 代码（把它写进 config.EUROSTAT_ROUTE_CODES）：")
    for code in codes:
        n = sum(1 for r in records if r.get("airp_pr") == code)
        print(f"  {code}   ({n} 个观测值)")
    return 0


def cmd_dgac_inspect(args) -> int:
    from . import dgac

    dgac.inspect(limit=args.limit)
    return 0


def cmd_dgac(args) -> int:
    from . import dgac

    df = dgac.fetch_route()
    if df.empty:
        print("DGAC 文件里没找到 CDG<->广州 的行。"
              "先跑 `python -m pgcan dgac-inspect` 看看表头。", file=sys.stderr)
        return 1
    path = OUT / "dgac_route.csv"
    df.to_csv(path, index=False)
    print(f"DGAC 命中 {len(df)} 行 -> {path}")
    print(df.head(20).to_string())
    return 0


def cmd_weekly(args) -> int:
    from . import amadeus

    client = amadeus.Amadeus(env=args.env, cache_dir=OUT / "cache")
    dates = amadeus.date_range(args.start, args.days)

    for origin, destination in [
        (config.IATA_ORIGIN, config.IATA_DEST),
        (config.IATA_DEST, config.IATA_ORIGIN),
    ]:
        if args.direction != "both" and args.direction != f"{origin}{destination}":
            continue
        scan = amadeus.scan_dates(
            client, dates, origin, destination,
            with_seatmap=not args.no_seatmap,
        )
        tag = f"{origin}_{destination}"
        scan.to_csv(OUT / f"daily_{tag}.csv", index=False)
        weekly = analyze.weekly_pressure(scan)
        if not weekly.empty:
            weekly.to_csv(OUT / f"weekly_{tag}.csv", index=False)
            print(f"\n=== {origin} -> {destination} 最紧张的 10 周")
            print(weekly.head(10).to_string(index=False))
        print(f"逐日明细 -> {OUT/f'daily_{tag}.csv'}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="pgcan", description="巴黎(CDG)<->广州(CAN) 历史客座率工具"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("monthly", help="Eurostat 月度客座率 + 季节指数")

    p_probe = sub.add_parser("probe-codes", help="找出 Eurostat 里的航线代码")
    p_probe.add_argument("--grep", default=config.EUROSTAT_ROUTE_GREP)

    p_ins = sub.add_parser("dgac-inspect", help="打印 DGAC 文件的真实表头")
    p_ins.add_argument("--limit", type=int, default=3)

    sub.add_parser("dgac", help="DGAC 逐月分方向旅客数")

    p_week = sub.add_parser("weekly", help="Amadeus 逐日/周度满座探测")
    p_week.add_argument("--start", required=True, help="起始日 YYYY-MM-DD")
    p_week.add_argument("--days", type=int, default=180)
    p_week.add_argument("--env", default="production",
                        choices=["production", "test"])
    p_week.add_argument("--direction", default="both",
                        choices=["both", "CDGCAN", "CANCDG"])
    p_week.add_argument("--no-seatmap", action="store_true",
                        help="只查舱位库存，省调用额度")

    args = parser.parse_args(argv)
    _setup(args.verbose)

    handlers = {
        "monthly": cmd_monthly,
        "probe-codes": cmd_probe_codes,
        "dgac-inspect": cmd_dgac_inspect,
        "dgac": cmd_dgac,
        "weekly": cmd_weekly,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
