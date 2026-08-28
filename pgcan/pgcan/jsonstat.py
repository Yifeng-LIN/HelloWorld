"""极简 JSON-stat 2.0 解析器（Eurostat 的 REST 接口返回这个格式）。

只依赖标准库，故意不引 pyjstat —— 那个包对 Eurostat 的稀疏 value 字典
兼容性时好时坏。
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List


def _dimension_codes(js: Dict[str, Any], dim_id: str) -> List[str]:
    """按 index 顺序返回某个维度的代码列表。"""
    cat = js["dimension"][dim_id]["category"]
    index = cat["index"]
    if isinstance(index, list):          # 已经是有序列表
        return list(index)
    # dict 形式 {code: position}
    return [code for code, _ in sorted(index.items(), key=lambda kv: kv[1])]


def _dimension_labels(js: Dict[str, Any], dim_id: str) -> Dict[str, str]:
    return js["dimension"][dim_id].get("category", {}).get("label", {}) or {}


def iter_records(js: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """把 JSON-stat 数据集摊平成一行行 dict。

    每行包含各维度的代码（以及 ``<dim>_label``）和 ``value``。
    缺失值直接跳过，不会产出 None 行。
    """
    dim_ids: List[str] = js["id"]
    sizes: List[int] = js["size"]
    codes = {d: _dimension_codes(js, d) for d in dim_ids}
    labels = {d: _dimension_labels(js, d) for d in dim_ids}

    # 行主序的步长
    strides: List[int] = [1] * len(sizes)
    for i in range(len(sizes) - 2, -1, -1):
        strides[i] = strides[i + 1] * sizes[i + 1]

    values = js.get("value", {})
    if isinstance(values, list):
        items: Iterator[Any] = (
            (i, v) for i, v in enumerate(values) if v is not None
        )
    else:
        items = ((int(k), v) for k, v in values.items() if v is not None)

    for flat_index, value in items:
        rec: Dict[str, Any] = {}
        remainder = flat_index
        for dim_id, stride in zip(dim_ids, strides):
            pos = remainder // stride
            remainder %= stride
            code = codes[dim_id][pos]
            rec[dim_id] = code
            if labels[dim_id].get(code):
                rec[f"{dim_id}_label"] = labels[dim_id][code]
        rec["value"] = value
        yield rec


def to_records(js: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(iter_records(js))
