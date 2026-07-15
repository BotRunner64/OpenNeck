"""Public angle-based control API for OpenNeck."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    from typing import Self
except ImportError:  # Python 3.10
    from typing import TypeVar

    Self = TypeVar("Self", bound="OpenNeckController")

from ._angles import angle_to_step as _angle_to_step
from ._angles import step_to_angle as _step_to_angle
from ._config import Config as _Config
from ._config import load_config as _load_config
from ._config import replace_config as _replace_config
from ._driver import ServoDriver as _ServoDriver


__all__ = ["NeckAngles", "OpenNeckController"]


@dataclass(frozen=True)
class NeckAngles:
    """OpenNeck angles in degrees, relative to the calibrated center."""

    yaw_deg: float
    pitch_deg: float


class OpenNeckController:
    """Control a two-axis OpenNeck using yaw and pitch angles in degrees.

    Positive yaw turns left. Positive pitch looks up. Servo installation
    direction and mechanical limits are defined entirely by the config file.
    """

    def __init__(
        self,
        config: str | Path | None = None,
        *,
        port: str | None = None,
    ) -> None:
        loaded = _load_config(config)
        if port is not None:
            loaded = _replace_config(loaded, port=port)
        self._config = loaded
        self._driver = _ServoDriver(loaded)

    def connect(self) -> None:
        """Open the servo bus and enable torque on both axes."""
        self._driver.connect()

    def move_deg(self, yaw_deg: float, pitch_deg: float) -> NeckAngles:
        """Send target angles and return the mechanically clamped target."""
        yaw_step = self._angle_to_step("yaw", yaw_deg)
        pitch_step = self._angle_to_step("pitch", pitch_deg)
        self._driver.write_positions(
            {
                self._config.yaw_id: yaw_step,
                self._config.pitch_id: pitch_step,
            }
        )
        return NeckAngles(
            yaw_deg=self._step_to_angle("yaw", yaw_step),
            pitch_deg=self._step_to_angle("pitch", pitch_step),
        )

    def center(self) -> NeckAngles:
        """Move to the calibrated forward, level pose."""
        return self.move_deg(0.0, 0.0)

    def read_deg(self) -> NeckAngles:
        """Read current servo positions as angles relative to the center."""
        positions = self._driver.read_positions()
        return NeckAngles(
            yaw_deg=self._step_to_angle(
                "yaw", positions[self._config.yaw_id]
            ),
            pitch_deg=self._step_to_angle(
                "pitch", positions[self._config.pitch_id]
            ),
        )

    def read_voltage(self) -> dict[str, float]:
        """Read the yaw and pitch servo supply voltages."""
        return {
            "yaw": self._driver.read_voltage(self._config.yaw_id),
            "pitch": self._driver.read_voltage(self._config.pitch_id),
        }

    def release_torque(self) -> None:
        """Disable holding torque on both axes."""
        self._driver.release_torque()

    def close(self) -> None:
        """Close the servo bus without changing the torque state."""
        self._driver.close()

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _angle_to_step(self, axis: str, angle_deg: float) -> int:
        return _angle_to_step(
            angle_deg,
            center_step=getattr(self._config, f"{axis}_center_step"),
            min_step=getattr(self._config, f"{axis}_min_step"),
            max_step=getattr(self._config, f"{axis}_max_step"),
            step_sign=getattr(self._config, f"{axis}_step_sign"),
        )

    def _step_to_angle(self, axis: str, step: int) -> float:
        return _step_to_angle(
            step,
            center_step=getattr(self._config, f"{axis}_center_step"),
            step_sign=getattr(self._config, f"{axis}_step_sign"),
        )

    def _move_axis_deg(self, axis: str, angle_deg: float) -> float:
        """Move one axis for package-internal maintenance commands."""
        if axis not in {"yaw", "pitch"}:
            raise ValueError(f"unsupported OpenNeck axis: {axis!r}")
        step = self._angle_to_step(axis, angle_deg)
        self._driver.write_positions(
            {getattr(self._config, f"{axis}_id"): step}
        )
        return self._step_to_angle(axis, step)


def _controller_from_config(
    config: _Config,
    *,
    enable_torque_on_connect: bool = True,
) -> OpenNeckController:
    """Construct a controller from an already validated private config."""
    controller = OpenNeckController.__new__(OpenNeckController)
    controller._config = config
    controller._driver = _ServoDriver(
        config,
        enable_torque_on_connect=enable_torque_on_connect,
    )
    return controller
