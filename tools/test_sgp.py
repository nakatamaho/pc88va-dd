# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""ROM-free tests of the independent SGP benchmark image oracle."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_sgp import expected_image


class SgpTests(unittest.TestCase):
    def test_transparency_and_opaque_black_index(self):
        background = bytes([3]) * 71680
        image = expected_image(background, 16, 1)
        self.assertEqual(image[16 * 320 + 16], 3)
        self.assertEqual(image[23 * 320 + 17], 16)
        self.assertEqual(expected_image(background, 16, 0), background)

    def test_odd_x_and_overlap(self):
        image = expected_image(bytes([3]) * 71680, 32, 2)
        # The later sprite starts at odd x=35. Its transparent first pixel
        # preserves the earlier sprite, while its next pixel overwrites it.
        self.assertEqual(image[16 * 320 + 35], 19)
        self.assertEqual(image[16 * 320 + 36], 17)

    def test_stress_bounds(self):
        image = expected_image(bytes([3]) * 71680, 32, 64)
        self.assertEqual(len(image), 71680)
        self.assertEqual(image[168 * 320:], bytes([3]) * (56 * 320))
        self.assertEqual(image[:16 * 320], bytes([3]) * (16 * 320))

    def test_invalid(self):
        for size, count in ((8, 1), (32, 65), (16, -1)):
            with self.assertRaises(ValueError):
                expected_image(bytes(71680), size, count)


if __name__ == '__main__':
    unittest.main()
