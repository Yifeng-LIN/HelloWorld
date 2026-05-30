from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


class ConfidenceFloat(BaseModel):
    value: float
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ConfidenceStr(BaseModel):
    value: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class SpanValue(BaseModel):
    value: float
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class RawBridgeInput(BaseModel):
    source: Literal["image", "params", "dialog"]
    bridge_type: Optional[str] = None
    span_lengths_m: Optional[list[SpanValue]] = None
    pier_height_m: Optional[ConfidenceFloat] = None
    deck_width_m: Optional[ConfidenceFloat] = None
    material: Optional[str] = None

    # Per-field confidences for bridge_type and material (string fields)
    bridge_type_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    material_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
