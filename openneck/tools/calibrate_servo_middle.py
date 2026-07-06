#!/usr/bin/env python3
"""Set current servo position as hardware middle position 2048."""

from __future__ import annotations

import argparse
import time

from ._servo_bus import (
    MIDDLE_POSITION,
    ServoBus,
    choose_port,
    confirm_or_exit,
    print_servo_table,
    validate_servo_id,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Write current servo pose as hardware middle position 2048. "
            "This changes non-volatile servo config."
        )
    )
    parser.add_argument("--port", default=None, help="Serial port, e.g. /dev/ttyACM0")
    parser.add_argument("--baudrate", type=int, default=1_000_000)
    parser.add_argument(
        "--ids",
        type=int,
        nargs="+",
        default=[1, 2],
        help="Servo IDs to calibrate. Defaults to OpenNeck yaw/pitch: 1 2",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Scan IDs 1..20 and calibrate all found servos instead of --ids",
    )
    parser.add_argument("--no-disable", action="store_true", help="Do not disable torque first")
    parser.add_argument("--no-center-test", action="store_true", help="Skip move-to-2048 test")
    parser.add_argument("--speed", type=int, default=1000)
    parser.add_argument("--acceleration", type=int, default=50)
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    port = choose_port(args.port)

    with ServoBus(port, args.baudrate) as bus:
        print(f"[bus] connected port={port} baudrate={args.baudrate}")

        ids = bus.scan(1, 20) if args.scan else [validate_servo_id(sid) for sid in args.ids]
        if not ids:
            raise SystemExit("No servos selected or found.")

        print_servo_table(bus, ids, "Before calibration")

        if not args.no_disable:
            for servo_id in ids:
                bus.write_torque(servo_id, False)
            print(f"[servo] torque disabled ids={ids}")

        print("\nMove the selected servo(s) to the desired mechanical middle pose.")
        input("Press Enter when the pose is correct...")

        print(f"[plan] write current pose as hardware middle {MIDDLE_POSITION} for ids={ids}")
        print("[warning] this writes non-volatile servo hardware config.")
        confirm_or_exit("Type CALIBRATE to continue: ", "CALIBRATE", args.yes)

        for servo_id in ids:
            print(f"[calibrate] id={servo_id}")
            bus.calibrate_middle(servo_id)
            time.sleep(0.2)

        print_servo_table(bus, ids, "After calibration")

        if not args.no_center_test:
            print(f"\n[center-test] moving ids={ids} to {MIDDLE_POSITION}")
            for servo_id in ids:
                bus.write_torque(servo_id, True)
                bus.move_position(
                    servo_id,
                    MIDDLE_POSITION,
                    speed=args.speed,
                    acceleration=args.acceleration,
                )
                time.sleep(0.1)
            time.sleep(2.0)
            print_servo_table(bus, ids, "After center test")

    print("[done] middle calibration complete")


if __name__ == "__main__":
    main()
