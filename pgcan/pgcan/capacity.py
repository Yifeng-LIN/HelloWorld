"""在 Eurostat 没给 ST_PAS 的月份，用「班期 x 机型座位数」补出运力分母。

班期表放在 data/schedule_cz_cdg_can.json，格式是若干时间段：
    {"start": "2026-03-29", "end": "2026-06-30",
     "weekly_frequency": 7, "aircraft": "359", "note": "..."}

只有经过核实的时段才写进去。没覆盖到的月份会返回 NaN，
而不是拿一个编出来的数字冒充事实。
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

DEFAULT_SCHEDULE = (
    Path(__file__).resolve().parent.parent / "data" / "schedule_cz_cdg_can.json"
)


def load_schedule(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    src = Path(path) if path else DEFAULT_SCHEDULE
    if not src.exists():
        return []
    return json.loads(src.read_text(encoding="utf-8"))


def _overlap_days(seg_start, seg_end, month_start, month_end) -> int:
    lo = max(seg_start, month_start)
    hi = min(seg_end, month_end)
    return max((hi - lo).days + 1, 0)


def monthly_seats(
    year: int, month: int, schedule: Optional[List[Dict[str, Any]]] = None
) -> Optional[float]:
    """单向月度座位数。班期表没覆盖到该月则返回 None。"""
    segments = schedule if schedule is not None else load_schedule()
    if not segments:
        return None

    month_start = dt.date(year, month, 1)
    month_end = dt.date(year, month, calendar.monthrange(year, month)[1])
    days_in_month = (month_end - month_start).days + 1

    seats = 0.0
    covered = 0
    for seg in segments:
        seg_start = dt.date.fromisoformat(seg["start"])
        seg_end = dt.date.fromisoformat(seg["end"])
        days = _overlap_days(seg_start, seg_end, month_start, month_end)
        if not days:
            continue
        covered += days
        per_seat = config.AIRCRAFT_SEATS.get(str(seg["aircraft"]).upper())
        if per_seat is None:
            return None
        flights = days * (float(seg["weekly_frequency"]) / 7.0)
        seats += flights * per_seat

    # 覆盖不足 90% 的月份不给结论
    if covered < days_in_month * 0.9:
        return None
    return seats


def attach_capacity(df, schedule: Optional[List[Dict[str, Any]]] = None):
    """给月度表补一列 ``seats_scheduled``（同时给出未覆盖月份的 NaN）。"""
    import pandas as pd

    if df.empty or "month" not in df.columns:
        return df
    segments = schedule if schedule is not None else load_schedule()
    out = df.copy()
    out["seats_scheduled"] = [
        monthly_seats(p.year, p.month, segments) for p in out["month"]
    ]
    return out
