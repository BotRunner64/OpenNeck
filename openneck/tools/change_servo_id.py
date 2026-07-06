#!/usr/bin/env python3
"""Change one FTServo/SCServo ID on a bus."""

from __future__ import annotations

import argparse
import time

from ._servo_bus import ServoBus, choose_port, confirm_or_exit, validate_servo_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Change a single servo ID. For safety, connect exactly one servo "
            "to the bus unless --old-id is provided and you know what you are doing."
        )
    )
    parser.add_argument("--port", default=None, help="Serial port, e.g. /dev/ttyACM0")
    parser.add_argument("--baudrate", type=int, default=1_000_000)
    parser.add_argument("--old-id", type=int, default=None, help="Current servo ID")
    parser.add_argument("--new-id", type=int, required=True, help="New servo ID")
    parser.add_argument("--scan-start", type=int, default=1)
    parser.add_argument("--scan-end", type=int, default=253)
    parser.add_argument(
        "--allow-multiple",
        action="store_true",
        help="Allow changing --old-id even if other servos are present",
    )
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    new_id = validate_servo_id(args.new_id)
    old_id = validate_servo_id(args.old_id) if args.old_id is not None else None
    port = choose_port(args.port)

    with ServoBus(port, args.baudrate) as bus:
        print(f"[bus] connected port={port} baudrate={args.baudrate}")
        found = bus.scan(args.scan_start, args.scan_end)
        print(f"[scan] found ids={found}")

        if old_id is None:
            if len(found) != 1:
                raise SystemExit(
                    "Expected exactly one servo on the bus when --old-id is omitted. "
                    "Disconnect other servos, or pass --old-id with --allow-multiple."
                )
            old_id = found[0]
        else:
            bus.ping(old_id)
            if len(found) > 1 and not args.allow_multiple:
                raise SystemExit(
                    "Multiple servos were detected. For ID changes, disconnect other "
                    "servos or pass --allow-multiple intentionally."
                )

        if old_id == new_id:
            raise SystemExit("Old ID and new ID are the same; nothing to change.")

        print(f"[plan] change servo ID {old_id} -> {new_id}")
        print("[warning] this writes the servo's non-volatile hardware config.")
        confirm_or_exit("Type CHANGE to continue: ", "CHANGE", args.yes)

        bus.write_servo_id(old_id, new_id)
        time.sleep(0.2)

        model = bus.ping(new_id)
        print(f"[verify] new ID {new_id} responds, model={model}")

        try:
            bus.lock_eprom(new_id)
            print("[verify] EEPROM locked")
        except Exception as exc:
            print(f"[warning] failed to lock EEPROM with new ID: {exc}")

    print("[done] ID change complete")


if __name__ == "__main__":
    main()
