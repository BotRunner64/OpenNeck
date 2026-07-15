from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import openneck
from openneck import NeckAngles, OpenNeckController
from openneck._angles import STEPS_PER_DEG


class FakeServoDriver:
    instances: list["FakeServoDriver"] = []

    def __init__(self, config, *, enable_torque_on_connect=True) -> None:
        self.config = config
        self.enable_torque_on_connect = enable_torque_on_connect
        self.connected = False
        self.closed = False
        self.released = False
        self.writes: list[dict[int, int]] = []
        self.positions = {
            config.yaw_id: config.yaw_center_step,
            config.pitch_id: config.pitch_center_step,
        }
        self.voltages = {config.yaw_id: 12.1, config.pitch_id: 12.2}
        self.instances.append(self)

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.closed = True
        self.connected = False

    def write_positions(self, targets: dict[int, int]) -> None:
        if not self.connected:
            raise RuntimeError("not connected")
        self.writes.append(dict(targets))
        self.positions.update(targets)

    def read_positions(self) -> dict[int, int]:
        return dict(self.positions)

    def read_voltage(self, servo_id: int) -> float:
        return self.voltages[servo_id]

    def release_torque(self) -> None:
        self.released = True


class ControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeServoDriver.instances.clear()
        self.directory = tempfile.TemporaryDirectory()
        self.config_path = Path(self.directory.name) / "config.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "port": "/dev/from-config",
                    "baudrate": 1_000_000,
                    "yaw_id": 7,
                    "pitch_id": 8,
                    "yaw_center_step": 2000,
                    "yaw_min_step": 1900,
                    "yaw_max_step": 2100,
                    "yaw_step_sign": 1,
                    "pitch_center_step": 1500,
                    "pitch_min_step": 1400,
                    "pitch_max_step": 1600,
                    "pitch_step_sign": -1,
                    "speed": 0,
                    "acceleration": 0,
                }
            ),
            encoding="utf-8",
        )
        self.driver_patch = patch("openneck.api._ServoDriver", FakeServoDriver)
        self.driver_patch.start()

    def tearDown(self) -> None:
        self.driver_patch.stop()
        self.directory.cleanup()

    def test_package_exports_only_angle_api(self) -> None:
        self.assertEqual(openneck.__all__, ["NeckAngles", "OpenNeckController"])
        angles = NeckAngles(1.0, 2.0)
        with self.assertRaises(FrozenInstanceError):
            angles.yaw_deg = 3.0

    def test_context_connects_and_closes(self) -> None:
        with OpenNeckController(self.config_path, port="/dev/override") as neck:
            driver = FakeServoDriver.instances[-1]
            self.assertTrue(driver.connected)
            self.assertEqual(driver.config.port, "/dev/override")
            self.assertIsInstance(neck, OpenNeckController)

        self.assertTrue(driver.closed)

    def test_move_clamps_and_returns_applied_angles(self) -> None:
        with OpenNeckController(self.config_path) as neck:
            applied = neck.move_deg(yaw_deg=100.0, pitch_deg=100.0)
            driver = FakeServoDriver.instances[-1]

        self.assertEqual(driver.writes[-1], {7: 2100, 8: 1400})
        self.assertAlmostEqual(applied.yaw_deg, 100 / STEPS_PER_DEG)
        self.assertAlmostEqual(applied.pitch_deg, 100 / STEPS_PER_DEG)

    def test_move_returns_integer_step_quantization(self) -> None:
        with OpenNeckController(self.config_path) as neck:
            applied = neck.move_deg(yaw_deg=1.0, pitch_deg=-1.0)
            driver = FakeServoDriver.instances[-1]

        self.assertEqual(driver.writes[-1], {7: 2011, 8: 1511})
        self.assertAlmostEqual(applied.yaw_deg, 11 / STEPS_PER_DEG)
        self.assertAlmostEqual(applied.pitch_deg, -11 / STEPS_PER_DEG)

    def test_internal_axis_move_writes_only_the_selected_servo(self) -> None:
        with OpenNeckController(self.config_path) as neck:
            applied_deg = neck._move_axis_deg("yaw", 5.0)
            driver = FakeServoDriver.instances[-1]

        self.assertEqual(driver.writes[-1], {7: 2057})
        self.assertAlmostEqual(applied_deg, 57 / STEPS_PER_DEG)

    def test_center_read_voltage_and_release_use_angle_api(self) -> None:
        with OpenNeckController(self.config_path) as neck:
            self.assertEqual(neck.center(), NeckAngles(0.0, 0.0))
            driver = FakeServoDriver.instances[-1]
            driver.positions = {7: 2023, 8: 1466}

            current = neck.read_deg()
            voltage = neck.read_voltage()
            neck.release_torque()

        self.assertAlmostEqual(current.yaw_deg, 23 / STEPS_PER_DEG)
        self.assertAlmostEqual(current.pitch_deg, 34 / STEPS_PER_DEG)
        self.assertEqual(voltage, {"yaw": 12.1, "pitch": 12.2})
        self.assertTrue(driver.released)

    def test_controller_has_only_the_angle_control_surface(self) -> None:
        controller = OpenNeckController(self.config_path)
        public_names = {
            name for name in dir(controller) if not name.startswith("_")
        }
        self.assertEqual(
            public_names,
            {
                "center",
                "close",
                "connect",
                "move_deg",
                "read_deg",
                "read_voltage",
                "release_torque",
            },
        )


if __name__ == "__main__":
    unittest.main()
