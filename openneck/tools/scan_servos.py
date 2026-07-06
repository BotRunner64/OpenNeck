#!/usr/bin/env python3
"""Scan FTServo/SCServo IDs on a serial bus."""

from __future__ import annotations

import argparse

from ._servo_bus import ServoBus, choose_port, print_servo_table


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan servos on a serial bus.")
    parser.add_argument("--port", default=None, help="Serial port, e.g. /dev/ttyACM0")
    parser.add_argument("--baudrate", type=int, default=1_000_000)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=20)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    port = choose_port(args.port)

    with ServoBus(port, args.baudrate) as bus:
        print(f"[bus] connected port={port} baudrate={args.baudrate}")
        ids = bus.scan(args.start, args.end)
        print(f"[scan] found ids={ids}")
        if ids:
            print_servo_table(bus, ids, "Servo status")


if __name__ == "__main__":
    main()
