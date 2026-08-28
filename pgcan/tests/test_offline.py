"""离线自检：不联网，用构造的样例数据把整条分析链路跑通。

⚠ 这里的数字是**为了测试代码而构造的假数据**，不是真实客座率。
真实数字请跑 `python -m pgcan monthly` 从 Eurostat 现取。
"""

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pgcan import analyze, capacity, eurostat          # noqa: E402
from pgcan.jsonstat import to_records                  # noqa: E402


def _fake_jsonstat(years=range(2013, 2020)):
    """构造一份形状与 Eurostat 一致的 JSON-stat，季节形态是人为设定的。"""
    months = [f"{y}-{m:02d}" for y in years for m in range(1, 13)]
    measures = ["PAS_CRD", "ST_PAS"]
    # 人为设定的季节强弱（仅用于验证算法能把它还原出来）
    shape = {1: .93, 2: .90, 3: .78, 4: .76, 5: .77, 6: .85,
             7: .96, 8: .97, 9: .88, 10: .84, 11: .74, 12: .87}

    values = {}
    for mi, measure in enumerate(measures):
        for ti, period in enumerate(months):
            flat = mi * len(months) + ti
            seats = 9500.0
            if measure == "ST_PAS":
                values[str(flat)] = seats
            else:
                month_num = int(period.split("-")[1])
                values[str(flat)] = round(seats * shape[month_num], 1)

    return {
        "id": ["tra_meas", "time"],
        "size": [len(measures), len(months)],
        "dimension": {
            "tra_meas": {"category": {
                "index": {m: i for i, m in enumerate(measures)}}},
            "time": {"category": {
                "index": {p: i for i, p in enumerate(months)}}},
        },
        "value": values,
    }


def test_jsonstat_roundtrip():
    records = to_records(_fake_jsonstat())
    assert len(records) == 7 * 12 * 2
    assert {r["tra_meas"] for r in records} == {"PAS_CRD", "ST_PAS"}
    print(f"  jsonstat: {len(records)} 条记录 OK")


def test_pipeline():
    records = to_records(_fake_jsonstat())
    wide = eurostat.to_monthly_frame(records)
    assert "load_factor" in wide.columns, wide.columns.tolist()

    monthly = analyze.monthly_load_factor(wide)
    assert len(monthly) == 84, len(monthly)
    assert 0.7 < monthly["load_factor"].mean() < 0.9

    seasonal = analyze.seasonal_index(monthly)
    assert not seasonal.empty, "季节指数算不出来"
    assert len(seasonal) == 12, len(seasonal)

    # 算法应当把构造时设定的强弱顺序还原出来：8月最满、11月最空
    fullest = seasonal.iloc[0]["month_num"]
    emptiest = seasonal.iloc[-1]["month_num"]
    assert fullest == 8, f"最满月份识别为 {fullest}，应为 8"
    assert emptiest == 11, f"最空月份识别为 {emptiest}，应为 11"
    assert math.isclose(seasonal["seasonal_index"].mean(), 1.0, abs_tol=1e-6)

    print("  季节指数还原结果：")
    print(seasonal[["month_cn", "seasonal_index", "mean_load_factor"]]
          .to_string(index=False))


def test_capacity_is_honest():
    """班期表没覆盖的月份必须返回 None，不许编数字。"""
    sched = capacity.load_schedule()
    assert capacity.monthly_seats(2026, 1, sched) == 31 * 314
    assert capacity.monthly_seats(2026, 7, sched) == 31 * 309
    assert capacity.monthly_seats(2015, 5, sched) is None
    print("  运力模块：未核实月份正确返回 None")


def test_availability_summary():
    from pgcan.amadeus import summarise_availability

    loose = summarise_availability([{"segments": [{"availabilityClasses": [
        {"class": c, "numberOfBookableSeats": 9}
        for c in ["Y", "B", "M", "L", "V", "X"]]}]}])
    tight = summarise_availability([{"segments": [{"availabilityClasses": [
        {"class": "Y", "numberOfBookableSeats": 2}]}]}])

    assert loose["low_classes_open"] == 3, loose
    assert loose["scarcity"] == 0.0, loose
    assert tight["scarcity"] > 0.7, tight
    print(f"  库存紧张度：宽松={loose['scarcity']} 紧张={tight['scarcity']}")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(f"\n[{name}]")
            fn()
    print("\n全部通过")
