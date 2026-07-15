"""Private configuration model for OpenNeck."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path.cwd() / "active_vision_config.json"
SERVO_MIN_STEP = 0
SERVO_MAX_STEP = 4095


@dataclass(frozen=True)
class Config:
    port: str | None = None
    baudrate: int = 1_000_000

    yaw_id: int = 1
    pitch_id: int = 2

    yaw_center_step: int = 2048
    yaw_min_step: int = 1024
    yaw_max_step: int = 3072
    yaw_step_sign: int = 1

    pitch_center_step: int = 2048
    pitch_min_step: int = 1365
    pitch_max_step: int = 2731
    pitch_step_sign: int = 1

    speed: int = 0
    acceleration: int = 0

    def __post_init__(self) -> None:
        if self.port is not None and not isinstance(self.port, str):
            raise TypeError("port must be a string or None")
        _require_int("baudrate", self.baudrate, minimum=1)
        _require_int("yaw_id", self.yaw_id, minimum=1, maximum=253)
        _require_int("pitch_id", self.pitch_id, minimum=1, maximum=253)
        if self.yaw_id == self.pitch_id:
            raise ValueError("yaw_id and pitch_id must be different")

        self._validate_axis("yaw")
        self._validate_axis("pitch")
        _require_int("speed", self.speed, minimum=0, maximum=65_535)
        _require_int("acceleration", self.acceleration, minimum=0, maximum=255)

    def _validate_axis(self, axis: str) -> None:
        center = getattr(self, f"{axis}_center_step")
        low = getattr(self, f"{axis}_min_step")
        high = getattr(self, f"{axis}_max_step")
        sign = getattr(self, f"{axis}_step_sign")

        _require_int(
            f"{axis}_center_step",
            center,
            minimum=SERVO_MIN_STEP,
            maximum=SERVO_MAX_STEP,
        )
        _require_int(
            f"{axis}_min_step",
            low,
            minimum=SERVO_MIN_STEP,
            maximum=SERVO_MAX_STEP,
        )
        _require_int(
            f"{axis}_max_step",
            high,
            minimum=SERVO_MIN_STEP,
            maximum=SERVO_MAX_STEP,
        )
        if not low <= center <= high:
            raise ValueError(
                f"{axis}_min_step <= {axis}_center_step <= {axis}_max_step "
                f"is required, got {low} <= {center} <= {high}"
            )
        if isinstance(sign, bool) or sign not in (-1, 1):
            raise ValueError(f"{axis}_step_sign must be -1 or 1, got {sign!r}")


def load_config(
    path: str | Path | None = None,
    *,
    allow_missing: bool = False,
) -> Config:
    config_path = DEFAULT_CONFIG_PATH if path is None else Path(path)
    if not config_path.exists():
        if path is None or allow_missing:
            return Config()
        raise FileNotFoundError(f"OpenNeck config not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"OpenNeck config must be a JSON object: {config_path}")

    known = {field.name for field in fields(Config)}
    unknown = sorted(set(data) - known)
    if unknown:
        names = ", ".join(unknown)
        raise ValueError(f"unsupported OpenNeck config field(s): {names}")
    return Config(**data)


def save_config(config: Config, path: str | Path | None = None) -> Path:
    config_path = DEFAULT_CONFIG_PATH if path is None else Path(path)
    with config_path.open("w", encoding="utf-8") as file:
        json.dump(asdict(config), file, indent=2)
        file.write("\n")
    return config_path


def replace_config(config: Config, **changes: Any) -> Config:
    """Return a validated copy after applying CLI or API overrides."""
    return replace(config, **changes)


def _require_int(
    name: str,
    value: object,
    *,
    minimum: int,
    maximum: int | None = None,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        suffix = f"..{maximum}" if maximum is not None else " or greater"
        raise ValueError(f"{name} must be {minimum}{suffix}, got {value}")
