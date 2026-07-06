"""Programmatic API for OpenNeck integrations."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from .cli import Config, Gimbal, load_config

Axis = Literal["yaw", "pitch", "both"]


class OpenNeckController:
    """Small controller wrapper for embedding OpenNeck in another Python app."""

    def __init__(
        self,
        config: Config | str | Path | None = None,
        *,
        port: str | None = None,
        enable_torque_on_connect: bool = True,
    ) -> None:
        if config is None:
            cfg = load_config()
        elif isinstance(config, Config):
            cfg = config
        else:
            cfg = load_config(Path(config))

        if port is not None:
            cfg.port = port

        self.config = cfg
        self._gimbal = Gimbal(cfg, enable_torque_on_connect=enable_torque_on_connect)

    def __enter__(self) -> "OpenNeckController":
        self._gimbal.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def port(self) -> str:
        return self._gimbal.port_name

    def close(self) -> None:
        self._gimbal.close()

    def read_positions(self) -> dict[int, int]:
        return self._gimbal.read()

    def read_voltage(self) -> dict[int, float]:
        return {sid: self._gimbal.read_voltage(sid) for sid in self._gimbal.ids}

    def center(self, axis: Axis = "both", wait_s: float = 0.5) -> None:
        self._gimbal.center_axis(axis, wait_s=wait_s)

    def move_norm(self, yaw: float, pitch: float) -> dict[int, int]:
        """Move with normalized yaw/pitch commands in [-1, 1]."""
        return self._gimbal.move_norm(yaw, pitch)

    def move_steps(
        self,
        *,
        yaw: int | None = None,
        pitch: int | None = None,
        wait_s: float = 0.0,
    ) -> None:
        """Move to raw servo positions."""
        targets: dict[int, int] = {}
        if yaw is not None:
            targets[self.config.yaw_id] = yaw
        if pitch is not None:
            targets[self.config.pitch_id] = pitch
        if targets:
            self._gimbal.write(targets, wait_s=wait_s, verbose=False)

    def release(self) -> None:
        self._gimbal.release()
