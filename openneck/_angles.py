"""Angle/servo-step conversion used by the OpenNeck driver."""

from __future__ import annotations

import math


STEPS_PER_DEG = 4096.0 / 360.0


def angle_to_step(
    angle_deg: float,
    *,
    center_step: int,
    min_step: int,
    max_step: int,
    step_sign: int,
) -> int:
    """Convert an angle to a mechanically clamped servo position."""
    angle_deg = float(angle_deg)
    if not math.isfinite(angle_deg):
        raise ValueError("angle_deg must be finite")
    _validate_step_sign(step_sign)

    target = center_step + step_sign * angle_deg * STEPS_PER_DEG
    return int(round(min(max(target, min_step), max_step)))


def step_to_angle(
    step: int,
    *,
    center_step: int,
    step_sign: int,
) -> float:
    """Convert a raw servo position to an angle relative to the center."""
    _validate_step_sign(step_sign)
    return (int(step) - center_step) / step_sign / STEPS_PER_DEG


def _validate_step_sign(step_sign: int) -> None:
    if isinstance(step_sign, bool) or step_sign not in (-1, 1):
        raise ValueError(f"step_sign must be -1 or 1, got {step_sign!r}")
