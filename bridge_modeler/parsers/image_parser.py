from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import anthropic
from bridge_modeler.models.raw_input import RawBridgeInput, ConfidenceFloat, SpanValue
from bridge_modeler.models.irg import ValidationResult
from bridge_modeler.engine.validator import validate

SYSTEM_PROMPT = """You are a structural engineering assistant. Analyze the bridge image and
extract the following parameters. Return ONLY valid JSON, no explanation.

{
  "bridge_type": {"value": "box_girder|t_beam|solid_slab", "confidence": 0.0},
  "span_lengths_m": [{"value": 0.0, "confidence": 0.0}],
  "pier_height_m": {"value": 0.0, "confidence": 0.0},
  "deck_width_m": {"value": 0.0, "confidence": 0.0},
  "material": {"value": "", "confidence": 0.0}
}

Set confidence to 0.0 for any parameter you cannot determine from the image.
Never guess structural dimensions — low confidence is correct and safe."""


def _detect_media_type(data: bytes) -> str:
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] in (b"GIF8", b"GIF9"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def parse_image(image_bytes: bytes) -> ValidationResult:
    b64 = base64.standard_b64encode(image_bytes).decode()
    media_type = _detect_media_type(image_bytes)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64},
                    },
                    {"type": "text", "text": "Extract bridge parameters from this image."},
                ],
            }
        ],
    )

    raw_json = response.content[0].text.strip()
    # Strip markdown code fences if present
    if raw_json.startswith("```"):
        raw_json = raw_json.split("```")[1]
        if raw_json.startswith("json"):
            raw_json = raw_json[4:]
    data = json.loads(raw_json)

    def _cf(d: dict | None) -> ConfidenceFloat | None:
        if not d or d.get("value") is None:
            return None
        return ConfidenceFloat(value=float(d["value"]), confidence=float(d.get("confidence", 0.0)))

    def _spans(lst: list | None) -> list[SpanValue] | None:
        if not lst:
            return None
        return [SpanValue(value=float(s["value"]), confidence=float(s.get("confidence", 0.0))) for s in lst]

    bt_block = data.get("bridge_type", {})
    mat_block = data.get("material", {})

    raw = RawBridgeInput(
        source="image",
        bridge_type=bt_block.get("value") if isinstance(bt_block, dict) else bt_block,
        bridge_type_confidence=float(bt_block.get("confidence", 0.0)) if isinstance(bt_block, dict) else 1.0,
        span_lengths_m=_spans(data.get("span_lengths_m")),
        pier_height_m=_cf(data.get("pier_height_m")),
        deck_width_m=_cf(data.get("deck_width_m")),
        material=mat_block.get("value") if isinstance(mat_block, dict) else mat_block,
        material_confidence=float(mat_block.get("confidence", 0.0)) if isinstance(mat_block, dict) else 1.0,
    )

    return validate(raw)
