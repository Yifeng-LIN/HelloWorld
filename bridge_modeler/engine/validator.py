from __future__ import annotations
from bridge_modeler.models.raw_input import RawBridgeInput
from bridge_modeler.models.irg import BridgeIRG, BridgeType, ValidationResult

CONFIDENCE_GATE = 0.75
VALID_MATERIALS = {"C30", "C40", "C50", "C60", "Q235", "Q345", "Q420"}


def validate(raw: RawBridgeInput) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    pending: list[str] = []

    # --- Confidence gate ---
    if raw.bridge_type_confidence < CONFIDENCE_GATE:
        pending.append("bridge_type")
    if raw.material_confidence < CONFIDENCE_GATE:
        pending.append("material")
    if raw.span_lengths_m:
        for i, s in enumerate(raw.span_lengths_m):
            if s.confidence < CONFIDENCE_GATE:
                pending.append(f"span_lengths_m[{i}]")
    elif raw.span_lengths_m is None:
        errors.append("span_lengths_m is required")
    if raw.pier_height_m and raw.pier_height_m.confidence < CONFIDENCE_GATE:
        pending.append("pier_height_m")
    if raw.deck_width_m and raw.deck_width_m.confidence < CONFIDENCE_GATE:
        pending.append("deck_width_m")

    # --- Required field presence ---
    if not raw.bridge_type:
        errors.append("bridge_type is required")
    if not raw.span_lengths_m:
        if "span_lengths_m" not in errors:
            errors.append("span_lengths_m is required")
    if raw.pier_height_m is None:
        errors.append("pier_height_m is required")
    if raw.deck_width_m is None:
        errors.append("deck_width_m is required")
    if not raw.material:
        errors.append("material is required")

    # --- Span range ---
    if raw.span_lengths_m:
        for i, s in enumerate(raw.span_lengths_m):
            if not (5.0 <= s.value <= 1500.0):
                errors.append(f"span_lengths_m[{i}]={s.value}m out of range [5, 1500]")

    # --- Deck width ---
    if raw.deck_width_m:
        if not (4.0 <= raw.deck_width_m.value <= 80.0):
            errors.append(f"deck_width_m={raw.deck_width_m.value}m out of range [4, 80]")

    # --- Pier height ---
    if raw.pier_height_m:
        if not (0.0 <= raw.pier_height_m.value <= 200.0):
            errors.append(f"pier_height_m={raw.pier_height_m.value}m out of range [0, 200]")

    # --- Material whitelist ---
    if raw.material and raw.material not in VALID_MATERIALS:
        errors.append(f"material '{raw.material}' not in whitelist {sorted(VALID_MATERIALS)}")

    # --- Box girder depth ratio (warning only) ---
    if raw.bridge_type == "box_girder" and raw.span_lengths_m:
        for s in raw.span_lengths_m:
            lo, hi = s.value / 25, s.value / 10
            warnings.append(
                f"Box girder depth for span {s.value}m should be {lo:.1f}–{hi:.1f}m (verify with design)"
            )

    # --- Multi-span consistency: nothing extra to check since we just use the list ---

    # Pending blocks passing
    if pending:
        return ValidationResult(
            passed=False,
            errors=errors,
            warnings=warnings,
            pending_confirmation=pending,
        )

    if errors:
        return ValidationResult(passed=False, errors=errors, warnings=warnings, pending_confirmation=pending)

    # Build IRG
    try:
        bridge_type_enum = BridgeType(raw.bridge_type)
    except ValueError:
        return ValidationResult(
            passed=False,
            errors=[f"Unknown bridge_type '{raw.bridge_type}'"],
            warnings=warnings,
        )

    irg = BridgeIRG(
        bridge_type=bridge_type_enum,
        span_lengths_m=[s.value for s in raw.span_lengths_m],
        pier_height_m=raw.pier_height_m.value,
        deck_width_m=raw.deck_width_m.value,
        material=raw.material,
        pending_confirmation=[],
    )

    return ValidationResult(passed=True, errors=[], warnings=warnings, pending_confirmation=[], irg=irg)
