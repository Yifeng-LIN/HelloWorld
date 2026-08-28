"""把月度客座率序列变成「什么时候该买票」的结论。

核心产出三张表：
  1. monthly.csv    —— 逐月客座率原始序列
  2. seasonal.csv   —— 12 个月的季节指数（剔除年度趋势后的相对满座程度）
  3. weekly.csv     —— 由 Amadeus 扫描得到的周度紧张度（可选）
"""

from __future__ import annotations

from typing import Optional

MONTH_NAMES_CN = [
    "1月", "2月", "3月", "4月", "5月", "6月",
    "7月", "8月", "9月", "10月", "11月", "12月",
]


def monthly_load_factor(df):
    """整理成 month / load_factor 两列，必要时用班期运力当分母。"""
    import numpy as np
    import pandas as pd

    if df.empty:
        return pd.DataFrame(columns=["month", "load_factor"])

    out = df.copy()
    if "load_factor" not in out.columns:
        out["load_factor"] = np.nan

    # Eurostat 没给座位数时，退回班期推算的运力
    if "seats_scheduled" in out.columns:
        pax_col = next(
            (c for c in ("PAS_CRD", "PAS_BRD") if c in out.columns), None
        )
        if pax_col:
            fallback = out[pax_col] / out["seats_scheduled"].where(
                out["seats_scheduled"] > 0
            )
            out["load_factor"] = out["load_factor"].fillna(fallback)
            out["lf_source"] = np.where(
                out["load_factor"].notna() & out.get(
                    "ST_PAS", pd.Series(index=out.index, dtype=float)
                ).notna(),
                "eurostat_seats",
                "scheduled_seats",
            )

    out = out[out["load_factor"].notna()]
    # 客座率理论上 <=1，明显越界的通常是口径错配，剔掉免得污染季节指数
    out = out[(out["load_factor"] > 0.2) & (out["load_factor"] <= 1.05)]
    return out.sort_values("month").reset_index(drop=True)


def seasonal_index(df, min_years: int = 3):
    """算每个日历月的季节指数。

    做法：先用 12 个月居中滚动均值把长期趋势和疫情断档抹平，
    再看每个月相对于同期趋势的比值。>1 表示比全年平均更满。
    """
    import numpy as np
    import pandas as pd

    if df.empty or len(df) < 24:
        return pd.DataFrame()

    s = df.set_index("month")["load_factor"].astype(float).sort_index()
    s = s.asfreq("M")

    trend = s.rolling(12, center=True, min_periods=8).mean()
    ratio = (s / trend).replace([np.inf, -np.inf], np.nan).dropna()

    grouped = ratio.groupby(ratio.index.month)
    table = pd.DataFrame(
        {
            "month_num": sorted(grouped.groups),
            "seasonal_index": [grouped.get_group(m).median()
                               for m in sorted(grouped.groups)],
            "n_years": [grouped.get_group(m).size
                        for m in sorted(grouped.groups)],
        }
    )
    table = table[table["n_years"] >= min_years]
    if table.empty:
        return table

    # 归一化到均值 1
    table["seasonal_index"] = (
        table["seasonal_index"] / table["seasonal_index"].mean()
    )
    table["month_cn"] = [MONTH_NAMES_CN[m - 1] for m in table["month_num"]]
    table["mean_load_factor"] = [
        s[s.index.month == m].mean() for m in table["month_num"]
    ]
    table["rank_fullest"] = table["seasonal_index"].rank(
        ascending=False
    ).astype(int)
    return table.sort_values("seasonal_index", ascending=False).reset_index(
        drop=True
    )


def weekly_pressure(scan_df):
    """把 Amadeus 的逐日扫描聚合成周度紧张度。"""
    import pandas as pd

    if scan_df is None or scan_df.empty:
        return pd.DataFrame()

    agg = {}
    for col, how in [
        ("scarcity", "mean"),
        ("low_classes_open", "mean"),
        ("total_bookable", "mean"),
        ("seatmap_occupancy", "mean"),
        ("cheapest_eur", "median"),
    ]:
        if col in scan_df.columns:
            agg[col] = how

    if not agg:
        return pd.DataFrame()

    weekly = (
        scan_df.groupby(["iso_year", "iso_week"]).agg(agg).reset_index()
    )
    weekly["week_start"] = [
        pd.Timestamp.fromisocalendar(int(y), int(w), 1)
        for y, w in zip(weekly["iso_year"], weekly["iso_week"])
    ]
    sort_col = "scarcity" if "scarcity" in weekly.columns else agg and list(agg)[0]
    return weekly.sort_values(sort_col, ascending=False).reset_index(drop=True)


def plot_monthly(df, seasonal, out_path) -> Optional[str]:
    """画两张图：逐月客座率时间序列 + 季节指数柱状图。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    if df.empty:
        return None

    has_seasonal = seasonal is not None and not seasonal.empty
    fig, axes = plt.subplots(
        2 if has_seasonal else 1, 1,
        figsize=(11, 8 if has_seasonal else 4.5),
    )
    axes = axes if has_seasonal else [axes]

    axes[0].plot(df["month"].dt.to_timestamp(), df["load_factor"] * 100,
                 lw=1.4)
    axes[0].set_title("CDG <-> CAN monthly load factor (%)")
    axes[0].set_ylabel("load factor %")
    axes[0].grid(alpha=0.3)

    if has_seasonal:
        ordered = seasonal.sort_values("month_num")
        axes[1].bar(ordered["month_num"], ordered["seasonal_index"])
        axes[1].axhline(1.0, color="red", ls="--", lw=1)
        axes[1].set_xticks(range(1, 13))
        axes[1].set_title(
            "Seasonal index (>1 = fuller than the yearly average)"
        )
        axes[1].grid(alpha=0.3, axis="y")

    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return str(out_path)
