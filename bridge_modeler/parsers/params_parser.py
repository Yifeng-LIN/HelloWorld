from __future__ import annotations
from typing import Any
from bridge_modeler.models.raw_input import RawBridgeInput, ConfidenceFloat, SpanValue
from bridge_modeler.models.irg import ValidationResult
from bridge_modeler.engine.validator import validate


def parse_params(data: dict[str, Any]) -> ValidationResult:
    """Parse a user-supplied parameter dict (all confidences default to 1.0)."""

    def _wrap_float(v: Any) -> ConfidenceFloat | None:
        if v is None:
            return None
        if isinstance(v, dict):
            return ConfidenceFloat(**v)
        return ConfidenceFloat(value=float(v), confidence=1.0)

    def _wrap_spans(v: Any) -> list[SpanValue] | None:
        if v is None:
            return None
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, dict):
                    result.append(SpanValue(**item))
                else:
                    result.append(SpanValue(value=float(item), confidence=1.0))
            return result
        return None

    raw = RawBridgeInput(
        source="params",
        bridge_type=data.get("bridge_type"),
        bridge_type_confidence=data.get("bridge_type_confidence", 1.0),
        span_lengths_m=_wrap_spans(data.get("span_lengths_m")),
        pier_height_m=_wrap_float(data.get("pier_height_m")),
        deck_width_m=_wrap_float(data.get("deck_width_m")),
        material=data.get("material"),
        material_confidence=data.get("material_confidence", 1.0),
    )

    return validate(raw)
