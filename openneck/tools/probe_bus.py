#!/usr/bin/env python3
"""Low-level serial probe for FTServo/SCServo buses."""

from __future__ import annotations

import argparse
import termios
import time

import serial

from ._servo_bus import DEFAULT_BAUDRATE, choose_port


HEADER = [0xFF, 0xFF]
INST_PING = 0x01


def checksum(packet: list[int]) -> int:
    return (~sum(packet[2:]) & 0xFF) & 0xFF


def ping_packet(servo_id: int) -> bytes:
    packet = HEADER + [servo_id, 0x02, INST_PING, 0x00]
    packet[-1] = checksum(packet)
    return bytes(packet)


def read_available(ser: serial.Serial, window_s: float) -> bytes:
    deadline = time.monotonic() + window_s
    data = bytearray()
    while time.monotonic() < deadline:
        waiting = ser.in_waiting
        if waiting:
            data.extend(ser.read(waiting))
        else:
            time.sleep(0.005)
    waiting = ser.in_waiting
    if waiting:
        data.extend(ser.read(waiting))
    return bytes(data)


def hex_bytes(data: bytes) -> str:
    if not data:
        return "<none>"
    return " ".join(f"{byte:02x}" for byte in data)


def apply_control_lines(ser: serial.Serial, dtr: bool | None, rts: bool | None) -> None:
    if dtr is not None:
        ser.dtr = dtr
    if rts is not None:
        ser.rts = rts
    time.sleep(0.1)


def disable_hangup_on_close(ser: serial.Serial) -> None:
    try:
        attrs = termios.tcgetattr(ser.fileno())
        attrs[2] &= ~termios.HUPCL
        termios.tcsetattr(ser.fileno(), termios.TCSANOW, attrs)
    except Exception:
        pass


def hangup_on_close_enabled(ser: serial.Serial) -> bool | None:
    try:
        return bool(termios.tcgetattr(ser.fileno())[2] & termios.HUPCL)
    except Exception:
        return None


def probe_once(
    ser: serial.Serial,
    servo_id: int,
    *,
    response_window_s: float,
) -> bytes:
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    packet = ping_packet(servo_id)
    written = ser.write(packet)
    if written != len(packet):
        raise RuntimeError(f"short write id={servo_id}: wrote {written}/{len(packet)}")
    time.sleep(0.005)
    return read_available(ser, response_window_s)


def control_line_states(sweep: bool) -> list[tuple[str, bool | None, bool | None]]:
    if not sweep:
        return [("default", None, None)]
    return [
        ("default", None, None),
        ("dtr=1 rts=1", True, True),
        ("dtr=1 rts=0", True, False),
        ("dtr=0 rts=1", False, True),
        ("dtr=0 rts=0", False, False),
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe raw Feetech serial responses.")
    parser.add_argument("--port", default=None, help="Serial port, e.g. /dev/ttyACM0")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--ids", type=int, nargs="+", default=[1, 2])
    parser.add_argument("--response-window-s", type=float, default=0.25)
    parser.add_argument(
        "--sweep-control-lines",
        action="store_true",
        help="Try DTR/RTS combinations to identify adapter control-line problems.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    port = choose_port(args.port)

    with serial.Serial(
        port=port,
        baudrate=args.baudrate,
        bytesize=serial.EIGHTBITS,
        timeout=0,
        write_timeout=0.5,
        inter_byte_timeout=0.5,
    ) as ser:
        disable_hangup_on_close(ser)
        print(
            f"[probe] port={port} baudrate={args.baudrate} "
            f"dtr={ser.dtr} rts={ser.rts} hupcl={hangup_on_close_enabled(ser)}"
        )
        time.sleep(0.25)
        for label, dtr, rts in control_line_states(args.sweep_control_lines):
            apply_control_lines(ser, dtr, rts)
            print(f"[probe] state={label} dtr={ser.dtr} rts={ser.rts}")
            for servo_id in args.ids:
                tx = ping_packet(servo_id)
                rx = probe_once(ser, servo_id, response_window_s=args.response_window_s)
                print(f"[probe] id={servo_id} tx={hex_bytes(tx)} rx={hex_bytes(rx)}")


if __name__ == "__main__":
    main()
