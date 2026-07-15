from __future__ import annotations

import sys
import types
import unittest
from typing import Any
from unittest.mock import patch

from openneck._config import Config
from openneck._driver import ServoDriver


def make_fake_sdk() -> tuple[types.ModuleType, dict[str, Any]]:
    state: dict[str, Any] = {
        "closed": False,
        "fail_ping": None,
        "fail_enable": None,
        "pings": [],
        "raise_write": False,
        "torque": {1: 0, 2: 0},
    }

    class FakePortHandler:
        def __init__(self, port_name: str) -> None:
            self.port_name = port_name
            self.is_using = False
            state["port"] = self

        def openPort(self) -> bool:
            return True

        def setBaudRate(self, baudrate: int) -> bool:
            return True

        def closePort(self) -> None:
            state["closed"] = True

    class FakePacket:
        def __init__(self, port: FakePortHandler) -> None:
            self.port = port

        def ping(self, servo_id: int) -> tuple[int, int, int]:
            state["pings"].append(servo_id)
            if servo_id == state["fail_ping"]:
                return 0, -1, 0
            return 321, 0, 0

        def write1ByteTxRx(
            self, servo_id: int, address: int, value: int
        ) -> tuple[int, int]:
            state["torque"][servo_id] = value
            if value == 1 and servo_id == state["fail_enable"]:
                return -1, 0
            return 0, 0

        def WritePosEx(
            self,
            servo_id: int,
            position: int,
            speed: int,
            acceleration: int,
        ) -> tuple[int, int]:
            if state["raise_write"]:
                self.port.is_using = True
                raise ValueError("simulated packet serialization failure")
            return 0, 0

        def getTxRxResult(self, comm: int) -> str:
            return f"comm={comm}"

        def getRxPacketError(self, error: int) -> str:
            return f"error={error}"

    module = types.ModuleType("scservo_sdk")
    module.COMM_SUCCESS = 0
    module.PortHandler = FakePortHandler
    module.sms_sts = FakePacket
    return module, state


class ServoDriverTests(unittest.TestCase):
    def test_ping_failure_does_not_enable_any_torque(self) -> None:
        sdk, state = make_fake_sdk()
        state["fail_ping"] = 2
        driver = ServoDriver(Config(port="/dev/fake"))

        with (
            patch.dict(sys.modules, {"scservo_sdk": sdk}),
            patch("openneck._driver.time.sleep"),
            self.assertRaisesRegex(RuntimeError, "ping servo 2"),
        ):
            driver.connect()

        self.assertEqual(state["torque"], {1: 0, 2: 0})
        self.assertTrue(state["closed"])

    def test_torque_is_rolled_back_if_enabling_one_axis_fails(self) -> None:
        sdk, state = make_fake_sdk()
        state["fail_enable"] = 2
        driver = ServoDriver(Config(port="/dev/fake"))

        with (
            patch.dict(sys.modules, {"scservo_sdk": sdk}),
            self.assertRaisesRegex(RuntimeError, "enable torque servo 2"),
        ):
            driver.connect()

        self.assertEqual(state["torque"], {1: 0, 2: 0})
        self.assertTrue(state["closed"])

    def test_sdk_busy_flag_is_reset_when_packet_call_raises(self) -> None:
        sdk, state = make_fake_sdk()
        driver = ServoDriver(Config(port="/dev/fake"))

        with patch.dict(sys.modules, {"scservo_sdk": sdk}):
            driver.connect()
            state["raise_write"] = True
            with self.assertRaisesRegex(ValueError, "serialization failure"):
                driver.write_positions({1: 2048})

        self.assertFalse(state["port"].is_using)
        driver.close()


if __name__ == "__main__":
    unittest.main()
