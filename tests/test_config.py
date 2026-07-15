from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from openneck._config import Config, load_config


class ConfigTests(unittest.TestCase):
    def test_loads_only_current_schema(self) -> None:
        data = {
            "port": "/dev/test",
            "baudrate": 1_000_000,
            "yaw_id": 3,
            "pitch_id": 4,
            "yaw_center_step": 2000,
            "yaw_min_step": 1000,
            "yaw_max_step": 3000,
            "yaw_step_sign": -1,
            "pitch_center_step": 2100,
            "pitch_min_step": 1200,
            "pitch_max_step": 2800,
            "pitch_step_sign": 1,
            "speed": 20,
            "acceleration": 10,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            config = load_config(path)

        self.assertEqual(config.yaw_center_step, 2000)
        self.assertEqual(config.yaw_step_sign, -1)
        self.assertEqual(config.pitch_id, 4)

    def test_unknown_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"obsolete_field": true}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "obsolete_field"):
                load_config(path)

    def test_explicit_missing_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            with self.assertRaises(FileNotFoundError):
                load_config(path)

    def test_axis_direction_and_bounds_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            Config(yaw_step_sign=0)
        with self.assertRaises(ValueError):
            Config(yaw_step_sign=True)
        with self.assertRaises(ValueError):
            Config(yaw_min_step=3000, yaw_center_step=2000)
        with self.assertRaises(ValueError):
            Config(yaw_id=2, pitch_id=2)

    def test_motion_packet_fields_are_range_checked(self) -> None:
        Config(speed=65_535, acceleration=255)
        with self.assertRaises(ValueError):
            Config(speed=65_536)
        with self.assertRaises(ValueError):
            Config(acceleration=256)


if __name__ == "__main__":
    unittest.main()
