#!/usr/bin/env python3
"""Angle-based OpenNeck control and maintenance CLI.

Typical flow:
  openneck ports
  openneck calibrate --port /dev/ttyACM0
  openneck center
  openneck test yaw --angle-deg 5
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from dataclasses import asdict

from ._config import (
    Config,
    load_config,
    replace_config,
    save_config,
)
from ._driver import ServoDriver
from .api import _controller_from_config

CALIBRATION_DISPLAY_PERIOD_S = 0.1
CALIBRATION_SAMPLE_PERIOD_S = 0.02
CALIBRATION_MAX_STEP_JUMP = 400


def with_overrides(args, *, allow_missing: bool = False) -> Config:
    cfg = load_config(args.config, allow_missing=allow_missing)
    changes = {}
    for key in [
        "port",
        "baudrate",
        "yaw_id",
        "pitch_id",
        "yaw_center_step",
        "yaw_min_step",
        "yaw_max_step",
        "yaw_step_sign",
        "pitch_center_step",
        "pitch_min_step",
        "pitch_max_step",
        "pitch_step_sign",
        "speed",
        "acceleration",
    ]:
        value = getattr(args, key, None)
        if value is not None:
            changes[key] = value
    return replace_config(cfg, **changes) if changes else cfg


def cmd_ports(_args) -> None:
    from serial.tools import list_ports

    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return
    for port in ports:
        print(f"{port.device}\t{port.description}")


def cmd_config(args) -> None:
    cfg = with_overrides(args)
    print(json.dumps(asdict(cfg), indent=2))


def cmd_voltage(args) -> None:
    cfg = with_overrides(args)
    with _controller_from_config(
        cfg, enable_torque_on_connect=False
    ) as neck:
        voltage = neck.read_voltage()
        angles = neck.read_deg()
        print(
            f"yaw={angles.yaw_deg:+.2f}deg voltage={voltage['yaw']:.1f}V\n"
            f"pitch={angles.pitch_deg:+.2f}deg voltage={voltage['pitch']:.1f}V"
        )


def cmd_calibrate(args) -> None:
    cfg = with_overrides(args, allow_missing=True)
    with ServoDriver(cfg, enable_torque_on_connect=False) as driver:
        driver.release_torque()
        print("\n[1/3] Move the camera to physical forward center.")
        input("Press Enter when aligned...")
        positions = driver.read_positions()
        yaw_center_step = int(positions[cfg.yaw_id])
        pitch_center_step = int(positions[cfg.pitch_id])

        yaw_min_step, yaw_max_step = record_axis_limits(
            driver, cfg.yaw_id, "yaw"
        )
        pitch_min_step, pitch_max_step = record_axis_limits(
            driver, cfg.pitch_id, "pitch"
        )

        validate_axis("yaw", yaw_min_step, yaw_center_step, yaw_max_step)
        validate_axis(
            "pitch", pitch_min_step, pitch_center_step, pitch_max_step
        )
        cfg = replace_config(
            cfg,
            yaw_center_step=yaw_center_step,
            yaw_min_step=yaw_min_step,
            yaw_max_step=yaw_max_step,
            pitch_center_step=pitch_center_step,
            pitch_min_step=pitch_min_step,
            pitch_max_step=pitch_max_step,
        )

        path = save_config(cfg, args.config)
        print(f"[config] saved {path}")
        print("[calibrate] done")
        print(json.dumps(asdict(cfg), indent=2))


def record_axis_limits(
    driver: ServoDriver, motor_id: int, name: str
) -> tuple[int, int]:
    print(f"\nMove ONLY the {name} axis through its full safe range.")
    print("Do not force the mechanism. Press Enter when finished.")
    print("Sampling position while you move...")

    samples: list[int] = []
    rejected = 0
    last_display = 0.0
    while True:
        try:
            pos = driver.read_position(motor_id)
        except RuntimeError:
            rejected += 1
            pos = None
        if pos is not None:
            if samples and abs(pos - samples[-1]) > CALIBRATION_MAX_STEP_JUMP:
                rejected += 1
            else:
                samples.append(pos)
        if sys.stdin in select_ready():
            sys.stdin.readline()
            break
        now = time.time()
        if samples and now - last_display > CALIBRATION_DISPLAY_PERIOD_S:
            print(
                f"  {name}: current={samples[-1]} min={min(samples)} "
                f"max={max(samples)} rejected={rejected}",
                end="\r",
                flush=True,
            )
            last_display = now
        time.sleep(CALIBRATION_SAMPLE_PERIOD_S)
    print()

    if not samples:
        raise RuntimeError(f"No valid {name} samples captured.")
    low, high = min(samples), max(samples)
    print(
        f"[calibrate] {name}_min_step={low} "
        f"{name}_max_step={high} rejected={rejected}"
    )
    return int(low), int(high)


def validate_axis(name: str, low: int, center: int, high: int) -> None:
    if not low < center < high:
        raise RuntimeError(
            f"Invalid {name} calibration: min={low}, center={center}, max={high}. "
            "Center must be between min and max."
        )
    if high - low < 100:
        raise RuntimeError(
            f"Invalid {name} calibration: range too small ({high - low} steps). "
            "Move the axis through a wider safe range."
        )


def cmd_center(args) -> None:
    cfg = with_overrides(args)
    with _controller_from_config(cfg) as neck:
        old_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            applied = neck.center()
            print(f"[center] target={applied}")
            deadline = time.time() + args.hold_s
            while time.time() < deadline:
                print(f"[servo] readback={neck.read_deg()}")
                time.sleep(0.2)
        finally:
            signal.signal(signal.SIGINT, old_handler)


def cmd_test(args) -> None:
    cfg = with_overrides(args)
    with _controller_from_config(cfg) as neck:
        print(f"[test] axis={args.axis} angle={args.angle_deg:.2f}deg")
        for angle_deg in (0.0, args.angle_deg, -args.angle_deg, 0.0):
            applied_deg = neck._move_axis_deg(args.axis, angle_deg)
            print(
                f"[test] requested_{args.axis}={angle_deg:+.2f}deg "
                f"applied_{args.axis}={applied_deg:+.2f}deg"
            )
            time.sleep(1.0)


def select_ready():
    import select

    ready, _, _ = select.select([sys.stdin], [], [], 0.0)
    return ready


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=None)
    parser.add_argument("--port", default=None)
    parser.add_argument("--baudrate", type=int, default=None)
    parser.add_argument("--yaw-id", type=int, default=None)
    parser.add_argument("--pitch-id", type=int, default=None)
    parser.add_argument("--yaw-center-step", type=int, default=None)
    parser.add_argument("--yaw-min-step", type=int, default=None)
    parser.add_argument("--yaw-max-step", type=int, default=None)
    parser.add_argument("--yaw-step-sign", type=int, choices=[-1, 1], default=None)
    parser.add_argument("--pitch-center-step", type=int, default=None)
    parser.add_argument("--pitch-min-step", type=int, default=None)
    parser.add_argument("--pitch-max-step", type=int, default=None)
    parser.add_argument("--pitch-step-sign", type=int, choices=[-1, 1], default=None)
    parser.add_argument("--speed", type=int, default=None)
    parser.add_argument("--acceleration", type=int, default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenNeck angle control driver")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ports", help="List serial ports")
    p.set_defaults(func=cmd_ports)

    p = sub.add_parser("config", help="Show loaded config")
    add_common(p)
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("voltage", help="Read servo voltage and current angles")
    add_common(p)
    p.set_defaults(func=cmd_voltage)

    p = sub.add_parser("calibrate", help="Save current physical forward pose as center")
    add_common(p)
    p.set_defaults(func=cmd_calibrate)

    p = sub.add_parser("center", help="Move to saved center")
    add_common(p)
    p.add_argument("--hold-s", type=float, default=2.0)
    p.set_defaults(func=cmd_center)

    p = sub.add_parser("test", help="Move one axis by a small angle")
    add_common(p)
    p.add_argument("axis", choices=["yaw", "pitch"])
    p.add_argument("--angle-deg", type=float, default=5.0)
    p.set_defaults(func=cmd_test)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
