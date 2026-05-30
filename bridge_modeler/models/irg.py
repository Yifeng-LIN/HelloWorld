from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class BridgeType(str, Enum):
    box_girder = "box_girder"
    t_beam = "t_beam"
    solid_slab = "solid_slab"


class BridgeIRG(BaseModel):
    bridge_type: BridgeType
    span_lengths_m: list[float] = Field(..., min_length=1)
    pier_height_m: float = Field(..., ge=0.0, le=200.0)
    deck_width_m: float = Field(..., ge=4.0, le=80.0)
    material: str
    pending_confirmation: list[str] = Field(default_factory=list)

    @field_validator("span_lengths_m")
    @classmethod
    def spans_in_range(cls, v: list[float]) -> list[float]:
        for span in v:
            if not (5.0 <= span <= 1500.0):
                raise ValueError(f"Span {span}m out of range [5, 1500]")
        return v


class ValidationResult(BaseModel):
    passed: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    pending_confirmation: list[str] = Field(default_factory=list)
    irg: Optional[BridgeIRG] = None
