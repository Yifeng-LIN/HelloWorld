"""从 Eurostat 取 CDG<->CAN 的月度座位数 / 旅客数 -> 真实客座率。

这是本工具箱里唯一一个能同时给出「分子」和「分母」的免费官方来源：
    ST_PAS  = 可提供座位数
    PAS_CRD = 实际承运旅客数
    客座率  = PAS_CRD / ST_PAS

两条获取路径：
  1. REST/JSON-stat 接口按 airp_pr 过滤（快，几十 KB）
  2. 整份 TSV 批量文件里 grep 航线（慢但最稳，接口改版也不怕）
"""

from __future__ import annotations

import csv
import gzip
import io
import logging
from typing import Any, Dict, Iterable, List, Optional

import requests

from . import config
from .jsonstat import to_records

log = logging.getLogger(__name__)

TIMEOUT = 120


# ------------------------------------------------------------------ 路径 1
def fetch_via_api(
    route_codes: Optional[Iterable[str]] = None,
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    """按航线代码过滤拉取。返回摊平后的记录列表，取不到就返回空列表。"""
    sess = session or requests.Session()
    codes = list(route_codes or config.EUROSTAT_ROUTE_CODES)
    out: List[Dict[str, Any]] = []

    for code in codes:
        url = f"{config.EUROSTAT_BASE}/{config.EUROSTAT_DATASET}"
        params = {"format": "JSON", "lang": "EN", "freq": "M", "airp_pr": code}
        try:
            resp = sess.get(url, params=params, timeout=TIMEOUT)
        except requests.RequestException as exc:
            log.warning("Eurostat 接口请求失败 (%s): %s", code, exc)
            continue

        if resp.status_code == 400:
            # Eurostat 对不存在的维度值返回 400，属正常情况
            log.info("航线代码 %s 在 avia_par_fr 中不存在", code)
            continue
        if not resp.ok:
            log.warning("Eurostat 返回 HTTP %s (%s)", resp.status_code, code)
            continue

        try:
            payload = resp.json()
        except ValueError:
            log.warning("Eurostat 返回的不是 JSON (%s)", code)
            continue

        if "value" not in payload or not payload["value"]:
            log.info("航线代码 %s 无数据", code)
            continue

        records = to_records(payload)
        log.info("接口路径取到 %d 条记录 (%s)", len(records), code)
        out.extend(records)

    return out


# ------------------------------------------------------------------ 路径 2
def fetch_via_bulk(
    grep: str = config.EUROSTAT_ROUTE_GREP,
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    """下载整份 TSV 批量文件，逐行筛出目标航线。

    文件形如::

        freq,unit,tra_meas,airp_pr\\TIME_PERIOD	2003-01	2003-02 ...
        M,PAS,PAS_CRD,FR_LFPG_CN_ZGGG	1234 	1180 p	:
    """
    sess = session or requests.Session()
    params = {
        "file": f"data/{config.EUROSTAT_DATASET}.tsv.gz",
        "unzip": "false",
    }
    resp = sess.get(
        config.EUROSTAT_BULK, params=params, timeout=TIMEOUT, stream=True
    )
    resp.raise_for_status()

    raw = resp.content
    try:
        text = gzip.decompress(raw).decode("utf-8", errors="replace")
    except (OSError, EOFError):
        text = raw.decode("utf-8", errors="replace")

    reader = csv.reader(io.StringIO(text), delimiter="\t")
    header = next(reader)
    key_names = header[0].split("\\")[0].split(",")
    periods = [h.strip() for h in header[1:]]

    out: List[Dict[str, Any]] = []
    for row in reader:
        if not row or grep not in row[0]:
            continue
        keys = dict(zip(key_names, row[0].split(",")))
        for period, cell in zip(periods, row[1:]):
            value = _parse_cell(cell)
            if value is None:
                continue
            rec = dict(keys)
            rec["time"] = period
            rec["value"] = value
            out.append(rec)

    log.info("批量文件路径取到 %d 条记录 (grep=%s)", len(out), grep)
    return out


def _parse_cell(cell: str) -> Optional[float]:
    """Eurostat 单元格可能是 ``:``（缺失）或 ``1234 p``（带标志位）。"""
    token = (cell or "").strip()
    if not token or token.startswith(":"):
        return None
    number = token.split(" ")[0].replace(",", "")
    try:
        return float(number)
    except ValueError:
        return None


# ------------------------------------------------------------------ 组装
def fetch(session: Optional[requests.Session] = None) -> List[Dict[str, Any]]:
    """先走接口，拿不到再退回批量文件。两条路都失败时返回空列表。"""
    records = fetch_via_api(session=session)
    if records:
        return records
    log.info("接口路径无结果，改用批量 TSV 文件")
    try:
        return fetch_via_bulk(session=session)
    except requests.RequestException as exc:
        log.warning("批量文件下载失败: %s", exc)
        return []


def to_monthly_frame(records: List[Dict[str, Any]]):
    """把记录透视成每月一行、tra_meas 一列，并算出 load_factor。"""
    import pandas as pd

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df = df[df["time"].astype(str).str.match(r"^\d{4}-\d{2}$")]
    if df.empty:
        return pd.DataFrame()

    wide = (
        df.pivot_table(
            index="time", columns="tra_meas", values="value", aggfunc="sum"
        )
        .rename_axis(None, axis=1)
        .sort_index()
    )
    wide.index = pd.PeriodIndex(wide.index, freq="M")

    for pax_col, seat_col in config.LOAD_FACTOR_PAIRS:
        if pax_col in wide.columns and seat_col in wide.columns:
            seats = wide[seat_col].where(wide[seat_col] > 0)
            wide["load_factor"] = wide[pax_col] / seats
            wide["lf_numerator"] = pax_col
            break

    return wide.reset_index(names="month")
