#!/usr/bin/env python3
"""Small helpers for FTServo/SCServo bus maintenance scripts."""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_BAUDRATE = 1_000_000
ID_ADDR = 5
TORQUE_ENABLE_ADDR = 40
PRESENT_VOLTAGE_ADDR = 62
MIDDLE_POSITION = 2048
CALIBRATE_MIDDLE_CMD = 128


def available_ports() -> list[str]:
    from serial.tools import list_ports

    return [port.device for port in list_ports.comports()]


def choose_port(explicit: str | None) -> str:
    if explicit:
        return explicit

    ports = available_ports()
    preferred = [
        port
        for port in ports
        if "ttyACM" in port or "ttyUSB" in port or port.startswith("COM")
    ]
    if preferred:
        return preferred[0]
    if ports:
        return ports[0]
    raise SystemExit("No serial ports found. Pass --port explicitly.")


def load_sdk():
    try:
        from scservo_sdk import COMM_SUCCESS, PortHandler, sms_sts
    except ImportError as exc:
        raise SystemExit(
            "Missing scservo_sdk. Install project dependencies first: "
            "pip install openneck"
        ) from exc
    return COMM_SUCCESS, PortHandler, sms_sts


@dataclass
class ServoBus:
    port_name: str
    baudrate: int = DEFAULT_BAUDRATE

    def __post_init__(self) -> None:
        self.comm_success, port_handler, packet_handler = load_sdk()
        self.port = port_handler(self.port_name)
        self.packet = packet_handler(self.port)
        self.opened = False

    def __enter__(self) -> "ServoBus":
        if not self.port.openPort():
            raise RuntimeError(f"failed to open port {self.port_name}")
        self.opened = True
        if not self.port.setBaudRate(self.baudrate):
            raise RuntimeError(f"failed to set baudrate {self.baudrate}")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if not self.opened:
            return
        try:
            if hasattr(self.port, "clearPort"):
                self.port.clearPort()
            self.port.closePort()
        finally:
            self.opened = False

    def check(self, comm: int, err: int, action: str) -> None:
        if comm != self.comm_success:
            raise RuntimeError(f"{action}: {self.packet.getTxRxResult(comm)}")
        if err:
            raise RuntimeError(f"{action}: {self.packet.getRxPacketError(err)}")

    def ping(self, servo_id: int) -> int:
        model, comm, err = self.packet.ping(servo_id)
        self.check(comm, err, f"ping servo {servo_id}")
        return int(model)

    def try_ping(self, servo_id: int) -> int | None:
        model, comm, err = self.packet.ping(servo_id)
        if comm == self.comm_success and not err:
            return int(model)
        return None

    def scan(self, start: int = 1, end: int = 253) -> list[int]:
        found: list[int] = []
        for servo_id in range(start, end + 1):
            if self.try_ping(servo_id) is not None:
                found.append(servo_id)
        return found

    def read_position(self, servo_id: int) -> int:
        if hasattr(self.packet, "ReadPosSpeed"):
            pos, _speed, comm, err = self.packet.ReadPosSpeed(servo_id)
        else:
            pos, comm, err = self.packet.ReadPos(servo_id)
        self.check(comm, err, f"read position servo {servo_id}")
        return int(pos)

    def read_voltage(self, servo_id: int) -> float:
        raw, comm, err = self.packet.read1ByteTxRx(servo_id, PRESENT_VOLTAGE_ADDR)
        self.check(comm, err, f"read voltage servo {servo_id}")
        return float(raw) / 10.0

    def write_torque(self, servo_id: int, enabled: bool) -> None:
        comm, err = self.packet.write1ByteTxRx(
            servo_id, TORQUE_ENABLE_ADDR, 1 if enabled else 0
        )
        self.check(comm, err, f"{'enable' if enabled else 'disable'} torque servo {servo_id}")

    def move_position(
        self,
        servo_id: int,
        position: int = MIDDLE_POSITION,
        speed: int = 1000,
        acceleration: int = 50,
    ) -> None:
        comm, err = self.packet.WritePosEx(servo_id, position, speed, acceleration)
        self.check(comm, err, f"move servo {servo_id} to {position}")

    def unlock_eprom(self, servo_id: int) -> None:
        comm, err = self.packet.unLockEprom(servo_id)
        self.check(comm, err, f"unlock EEPROM servo {servo_id}")

    def lock_eprom(self, servo_id: int) -> None:
        comm, err = self.packet.LockEprom(servo_id)
        self.check(comm, err, f"lock EEPROM servo {servo_id}")

    def write_servo_id(self, old_id: int, new_id: int) -> None:
        self.unlock_eprom(old_id)
        try:
            comm, err = self.packet.write1ByteTxRx(old_id, ID_ADDR, new_id)
            self.check(comm, err, f"write servo ID {old_id}->{new_id}")
        except Exception:
            # If the write failed, the old ID should still be valid.
            self.lock_eprom(old_id)
            raise

    def calibrate_middle(self, servo_id: int) -> None:
        self.unlock_eprom(servo_id)
        try:
            comm, err = self.packet.write1ByteTxRx(
                servo_id, TORQUE_ENABLE_ADDR, CALIBRATE_MIDDLE_CMD
            )
            self.check(comm, err, f"calibrate middle servo {servo_id}")
        finally:
            self.lock_eprom(servo_id)


def validate_servo_id(servo_id: int) -> int:
    if servo_id < 1 or servo_id > 253:
        raise SystemExit("Servo ID must be in range 1..253.")
    return servo_id


def confirm_or_exit(prompt: str, expected: str, yes: bool) -> None:
    if yes:
        return
    value = input(prompt).strip()
    if value != expected:
        raise SystemExit("Cancelled.")


def print_servo_table(bus: ServoBus, ids: list[int], title: str) -> None:
    print(f"\n{title}")
    print("-" * 44)
    print(f"{'ID':>4}  {'model':>8}  {'pos':>6}  {'voltage':>8}")
    print("-" * 44)
    for servo_id in ids:
        model = bus.ping(servo_id)
        pos = bus.read_position(servo_id)
        voltage = bus.read_voltage(servo_id)
        print(f"{servo_id:>4}  {model:>8}  {pos:>6}  {voltage:>7.1f}V")
    print("-" * 44)
