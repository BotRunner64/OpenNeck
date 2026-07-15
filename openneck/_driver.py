"""Private low-level FTServo driver."""

from __future__ import annotations

import time
from typing import Any

from ._config import Config, SERVO_MAX_STEP, SERVO_MIN_STEP


TORQUE_ENABLE_ADDR = 40
PRESENT_VOLTAGE_ADDR = 62


def find_servo_port() -> str:
    from serial.tools import list_ports

    ports = list(list_ports.comports())
    preferred = [
        port.device
        for port in ports
        if "ttyACM" in port.device
        or "ttyUSB" in port.device
        or port.device.startswith("COM")
    ]
    if preferred:
        return preferred[0]
    if ports:
        return ports[0].device
    raise RuntimeError("no serial ports found; pass port explicitly")


class ServoDriver:
    """Raw servo access for the controller and maintenance CLI."""

    def __init__(
        self,
        config: Config,
        *,
        enable_torque_on_connect: bool = True,
    ) -> None:
        self.config = config
        self.ids = (config.yaw_id, config.pitch_id)
        self.enable_torque_on_connect = enable_torque_on_connect
        self.port_name: str | None = config.port
        self._comm_success: int | None = None
        self._port: Any = None
        self._packet: Any = None
        self._opened = False
        self._connected = False

    def __enter__(self) -> "ServoDriver":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def connect(self) -> None:
        if self._connected:
            return

        from scservo_sdk import COMM_SUCCESS, PortHandler, sms_sts

        self.port_name = self.config.port or find_servo_port()
        self._comm_success = COMM_SUCCESS
        self._port = PortHandler(self.port_name)
        self._packet = sms_sts(self._port)
        torque_enable_started = False
        try:
            if not self._port.openPort():
                raise RuntimeError(f"failed to open port {self.port_name}")
            self._opened = True
            if not self._port.setBaudRate(self.config.baudrate):
                raise RuntimeError(f"failed to set baudrate {self.config.baudrate}")
            for servo_id in self.ids:
                self.ping(servo_id)
            if self.enable_torque_on_connect:
                torque_enable_started = True
                for servo_id in self.ids:
                    self.enable_torque(servo_id)
        except BaseException:
            if torque_enable_started:
                self._rollback_torque_after_failed_connect()
            try:
                self.close()
            except Exception:
                pass
            raise
        self._connected = True

    def close(self) -> None:
        port = self._port
        was_opened = self._opened
        try:
            if was_opened and port is not None:
                port.closePort()
        finally:
            self._reset_sdk_busy(port)
            self._connected = False
            self._opened = False
            self._packet = None
            self._port = None
            self._comm_success = None

    def ping(self, servo_id: int, attempts: int = 3) -> int:
        self._ensure_connected_or_opened()
        last_error: RuntimeError | None = None
        for attempt in range(1, attempts + 1):
            model, comm, error = self._packet_call("ping", servo_id)
            try:
                self._check(comm, error, f"ping servo {servo_id}")
                return int(model)
            except RuntimeError as exc:
                last_error = exc
                if attempt < attempts:
                    time.sleep(0.08)
        assert last_error is not None
        raise last_error

    def read_positions(self) -> dict[int, int]:
        self._ensure_connected()
        return {servo_id: self.read_position(servo_id) for servo_id in self.ids}

    def read_position(self, servo_id: int) -> int:
        self._ensure_connected_or_opened()
        position, _speed, comm, error = self._packet_call(
            "ReadPosSpeed", servo_id
        )
        self._check(comm, error, f"read servo {servo_id}")
        position = int(position)
        if position < SERVO_MIN_STEP or position > SERVO_MAX_STEP:
            raise RuntimeError(f"read servo {servo_id}: invalid position {position}")
        return position

    def read_voltage(self, servo_id: int) -> float:
        self._ensure_connected_or_opened()
        raw, comm, error = self._packet_call(
            "read1ByteTxRx", servo_id, PRESENT_VOLTAGE_ADDR
        )
        self._check(comm, error, f"read voltage servo {servo_id}")
        return float(raw) / 10.0

    def enable_torque(self, servo_id: int) -> None:
        self._set_torque(servo_id, enabled=True)

    def release_torque(self) -> None:
        self._ensure_connected()
        for servo_id in self.ids:
            self._set_torque(servo_id, enabled=False)

    def write_positions(self, targets: dict[int, int]) -> None:
        self._ensure_connected()
        for servo_id, position in targets.items():
            position = int(position)
            if position < SERVO_MIN_STEP or position > SERVO_MAX_STEP:
                raise ValueError(
                    f"servo {servo_id} target must be in "
                    f"{SERVO_MIN_STEP}..{SERVO_MAX_STEP}, got {position}"
                )
            comm, error = self._packet_call(
                "WritePosEx",
                servo_id,
                position,
                self.config.speed,
                self.config.acceleration,
            )
            self._check(comm, error, f"write servo {servo_id} pos={position}")

    def _set_torque(self, servo_id: int, *, enabled: bool) -> None:
        self._ensure_connected_or_opened()
        comm, error = self._packet_call(
            "write1ByteTxRx",
            servo_id,
            TORQUE_ENABLE_ADDR,
            1 if enabled else 0,
        )
        action = "enable" if enabled else "disable"
        self._check(comm, error, f"{action} torque servo {servo_id}")

    def _rollback_torque_after_failed_connect(self) -> None:
        for servo_id in self.ids:
            try:
                self._set_torque(servo_id, enabled=False)
            except Exception:
                # Preserve the original connection failure while attempting
                # to leave every reachable servo in the safest state.
                continue

    def _packet_call(self, method_name: str, *args: Any) -> Any:
        packet = self._packet
        if packet is None:
            raise RuntimeError("OpenNeck servo packet handler is unavailable")
        try:
            return getattr(packet, method_name)(*args)
        except BaseException:
            self._reset_sdk_busy()
            raise

    def _reset_sdk_busy(self, port: Any = None) -> None:
        target = self._port if port is None else port
        if target is None:
            return
        try:
            target.is_using = False
        except Exception:
            pass

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("OpenNeck is not connected")

    def _ensure_connected_or_opened(self) -> None:
        if not self._opened or self._packet is None:
            raise RuntimeError("OpenNeck servo port is not open")

    def _check(self, comm: int, error: int, action: str) -> None:
        assert self._comm_success is not None
        if comm != self._comm_success:
            raise RuntimeError(f"{action}: {self._packet.getTxRxResult(comm)}")
        if error:
            raise RuntimeError(f"{action}: {self._packet.getRxPacketError(error)}")
