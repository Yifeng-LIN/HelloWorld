from __future__ import annotations
import os
from typing import Any, Optional
import anthropic
import instructor
from pydantic import BaseModel, Field
from bridge_modeler.models.raw_input import RawBridgeInput, ConfidenceFloat, SpanValue
from bridge_modeler.models.irg import ValidationResult
from bridge_modeler.engine.validator import validate

REQUIRED_SLOTS_IN_ORDER = [
    "bridge_type",
    "span_lengths_m",
    "pier_height_m",
    "deck_width_m",
    "material",
]

SLOT_QUESTIONS = {
    "bridge_type": "What type of bridge is this? (box_girder, t_beam, or solid_slab)",
    "span_lengths_m": "What are the span lengths in meters? (e.g. 42 for a single span, or 30,40,30 for multiple spans)",
    "pier_height_m": "What is the pier height in meters?",
    "deck_width_m": "What is the deck width in meters?",
    "material": "What material is used? (e.g. C50, Q345)",
}


class SlotFillResult(BaseModel):
    bridge_type: Optional[str] = Field(
        None, description="Bridge type: box_girder, t_beam, or solid_slab"
    )
    span_lengths_m: Optional[list[float]] = Field(
        None, description="List of span lengths in meters"
    )
    pier_height_m: Optional[float] = Field(None, description="Pier height in meters")
    deck_width_m: Optional[float] = Field(None, description="Deck width in meters")
    material: Optional[str] = Field(None, description="Material code e.g. C50, Q345")


class DialogResponse(BaseModel):
    validation: ValidationResult
    follow_up_question: Optional[str] = None


def _first_missing_slot(slots: SlotFillResult) -> Optional[str]:
    for slot in REQUIRED_SLOTS_IN_ORDER:
        if getattr(slots, slot) is None:
            return slot
    return None


def parse_dialog(message: str, history: list[dict[str, Any]]) -> DialogResponse:
    raw_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    client = instructor.from_anthropic(raw_client)

    # Build messages from history + new user message
    messages: list[dict[str, str]] = []
    for turn in history:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": message})

    system_prompt = (
        "You are a structural engineering assistant helping collect bridge parameters. "
        "Extract any bridge parameters mentioned in the conversation. "
        "Return only what has been explicitly stated — leave fields None if not mentioned."
    )

    slots: SlotFillResult = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=512,
        system=system_prompt,
        messages=messages,
        response_model=SlotFillResult,
    )

    missing = _first_missing_slot(slots)

    # Build RawBridgeInput from filled slots
    span_list = (
        [SpanValue(value=v, confidence=1.0) for v in slots.span_lengths_m]
        if slots.span_lengths_m
        else None
    )

    raw = RawBridgeInput(
        source="dialog",
        bridge_type=slots.bridge_type,
        bridge_type_confidence=1.0 if slots.bridge_type else 0.0,
        span_lengths_m=span_list,
        pier_height_m=ConfidenceFloat(value=slots.pier_height_m, confidence=1.0)
        if slots.pier_height_m is not None
        else None,
        deck_width_m=ConfidenceFloat(value=slots.deck_width_m, confidence=1.0)
        if slots.deck_width_m is not None
        else None,
        material=slots.material,
        material_confidence=1.0 if slots.material else 0.0,
    )

    validation = validate(raw)
    follow_up = SLOT_QUESTIONS.get(missing) if missing else None

    return DialogResponse(validation=validation, follow_up_question=follow_up)
