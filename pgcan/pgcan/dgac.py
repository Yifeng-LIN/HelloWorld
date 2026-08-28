"""从 data.gouv.fr 取法国民航局(DGAC)的月度机场对运量。

用途：
  * 历史更长（1990 年起），可用来看法航时代 + 南航时代的完整需求曲线；
  * 分方向（CDG->CAN / CAN->CDG），Eurostat 的方向拆分没这么直观；
  * 给 Eurostat 的旅客数做交叉校验。

注意：DGAC 这份文件不同年份的列名变过好几轮，所以这里用模糊匹配识别列，
并提供 ``inspect`` 模式让你先看一眼真实表头再决定。
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
import zipfile
from typing import Any, Dict, List, Optional

import requests

from . import config

log = logging.getLogger(__name__)

TIMEOUT = 180

# 广州在这份法国文件里可能以下面任一形式出现
GUANGZHOU_TOKENS = ["ZGGG", "CAN", "CANTON", "GUANGZHOU"]
PARIS_CDG_TOKENS = ["LFPG", "CDG", "CHARLES DE GAULLE", "ROISSY"]


def _norm(text: str) -> str:
    """去重音、转大写、压掉非字母数字，方便做模糊比对。"""
    decomposed = unicodedata.normalize("NFKD", str(text))
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", "_", ascii_only.upper()).strip("_")


# ------------------------------------------------------------------ 资源发现
def list_resources(
    slug: str = config.DGAC_DATASET_SLUG,
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    """列出数据集下所有可下载资源（标题 / 格式 / URL）。"""
    sess = session or requests.Session()
    resp = sess.get(f"{config.DGAC_API}/{slug}/", timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()

    resources = []
    for res in payload.get("resources", []):
        resources.append(
            {
                "title": res.get("title"),
                "format": (res.get("format") or "").lower(),
                "url": res.get("url"),
                "size": res.get("filesize"),
            }
        )
    return resources


def _tabular_resources(resources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keep = []
    for res in resources:
        fmt = res.get("format", "")
        title = _norm(res.get("title") or "")
        if fmt in {"csv", "zip", "xlsx", "xls"} and "NOTICE" not in title:
            keep.append(res)
    return keep


# ------------------------------------------------------------------ 下载解析
def _read_table(content: bytes, name: str):
    import pandas as pd

    if name.lower().endswith(".zip") or content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            inner = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not inner:
                return None
            content = zf.read(inner[0])
            name = inner[0]

    if name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(content))

    for sep in (";", ",", "\t"):
        for enc in ("utf-8", "latin-1"):
            try:
                df = pd.read_csv(
                    io.BytesIO(content), sep=sep, encoding=enc, low_memory=False
                )
            except Exception:
                continue
            if df.shape[1] > 1:
                return df
    return None


def detect_columns(columns: List[str]) -> Dict[str, Optional[str]]:
    """按 config.DGAC_COLUMN_HINTS 把真实列名映射到语义名。"""
    normalized = {col: _norm(col) for col in columns}
    mapping: Dict[str, Optional[str]] = {}
    for semantic, hints in config.DGAC_COLUMN_HINTS.items():
        match = None
        for col, norm in normalized.items():
            if any(_norm(hint) in norm for hint in hints):
                match = col
                break
        mapping[semantic] = match
    return mapping


def inspect(
    slug: str = config.DGAC_DATASET_SLUG,
    session: Optional[requests.Session] = None,
    limit: int = 3,
) -> None:
    """打印前几个资源的真实表头和列名映射结果，供人工确认。"""
    sess = session or requests.Session()
    for res in _tabular_resources(list_resources(slug, sess))[:limit]:
        print(f"\n=== {res['title']}  [{res['format']}]\n{res['url']}")
        try:
            content = sess.get(res["url"], timeout=TIMEOUT).content
        except requests.RequestException as exc:
            print(f"    下载失败: {exc}")
            continue
        df = _read_table(content, res["url"])
        if df is None:
            print("    无法解析为表格")
            continue
        print(f"    形状: {df.shape}")
        print(f"    列名: {list(df.columns)}")
        print(f"    列映射: {detect_columns(list(df.columns))}")
        print(df.head(3).to_string())


def fetch_route(
    slug: str = config.DGAC_DATASET_SLUG,
    session: Optional[requests.Session] = None,
):
    """把所有资源拼起来，筛出 CDG <-> 广州 的行。"""
    import pandas as pd

    sess = session or requests.Session()
    frames = []

    for res in _tabular_resources(list_resources(slug, sess)):
        try:
            content = sess.get(res["url"], timeout=TIMEOUT).content
        except requests.RequestException as exc:
            log.warning("下载失败 %s: %s", res["title"], exc)
            continue

        df = _read_table(content, res["url"])
        if df is None or df.empty:
            continue

        hit = _filter_route(df)
        if hit is not None and not hit.empty:
            hit = hit.copy()
            hit["source_file"] = res["title"]
            frames.append(hit)
            log.info("%s -> 命中 %d 行", res["title"], len(hit))

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _filter_route(df):
    """在整张表里找同时提到 CDG 和广州的行（不依赖具体列名）。"""
    text_cols = [c for c in df.columns if df[c].dtype == object]
    if not text_cols:
        return None

    blob = df[text_cols].astype(str).apply(lambda s: s.str.upper())
    joined = blob.agg(" | ".join, axis=1)

    has_can = joined.str.contains(
        "|".join(re.escape(t) for t in GUANGZHOU_TOKENS), regex=True, na=False
    )
    has_cdg = joined.str.contains(
        "|".join(re.escape(t) for t in PARIS_CDG_TOKENS), regex=True, na=False
    )
    return df[has_can & has_cdg]
