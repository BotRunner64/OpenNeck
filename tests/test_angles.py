from __future__ import annotations

import math
import unittest

from openneck._angles import STEPS_PER_DEG, angle_to_step, step_to_angle


class AngleConversionTests(unittest.TestCase):
    def test_angle_to_step_uses_center_sign_and_limits(self) -> None:
        params = {
            "center_step": 2048,
            "min_step": 1900,
            "max_step": 2200,
            "step_sign": 1,
        }

        self.assertEqual(angle_to_step(0.0, **params), 2048)
        self.assertEqual(angle_to_step(10.0, **params), 2162)
        self.assertEqual(angle_to_step(100.0, **params), 2200)
        self.assertEqual(angle_to_step(-100.0, **params), 1900)

    def test_negative_step_sign_reverses_hardware_direction(self) -> None:
        params = {
            "center_step": 2048,
            "min_step": 1900,
            "max_step": 2200,
            "step_sign": -1,
        }

        self.assertEqual(angle_to_step(10.0, **params), 1934)
        self.assertAlmostEqual(
            step_to_angle(1934, center_step=2048, step_sign=-1),
            114 / STEPS_PER_DEG,
        )

    def test_non_finite_angle_is_rejected(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    angle_to_step(
                        value,
                        center_step=2048,
                        min_step=0,
                        max_step=4095,
                        step_sign=1,
                    )

    def test_invalid_step_sign_is_rejected(self) -> None:
        for sign in (0, True):
            with self.subTest(sign=sign):
                with self.assertRaises(ValueError):
                    angle_to_step(
                        0.0,
                        center_step=2048,
                        min_step=0,
                        max_step=4095,
                        step_sign=sign,
                    )


if __name__ == "__main__":
    unittest.main()
