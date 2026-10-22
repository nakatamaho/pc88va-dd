# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""ROM-free tests for direction oracles and real-material request selection."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_sgp_direction import expected_image
from check_sgp_cache import requests


class MaterialTests(unittest.TestCase):
    def test_traversal_not_reflection(self):
        bg = bytes([8]) * 71680
        normal = expected_image(bg, 0)
        for case in (1, 2, 3):
            self.assertEqual(expected_image(bg, case), normal)
        variants = [expected_image(bg, case) for case in range(4, 8)]
        self.assertEqual(len(set(variants)), 4)

    def test_transparency(self):
        bg = bytes([8]) * 71680
        self.assertEqual(expected_image(bg, 0)[16*320+17], 0)
        self.assertEqual(expected_image(bg, 4)[16*320+17], 8)

    def test_single_visible_piece(self):
        memory = bytearray(65536)
        memory[0x8b80] = 9
        memory[0x8b81] = 3
        memory[0x9380] = 200
        memory[0x9381] = 71
        memory[0x9b80] = 3
        self.assertEqual(requests(memory), [(9, 3, 1, 1)])

    def test_large_flipped_piece_order(self):
        memory = bytearray(65536)
        memory[0x8b80] = 128
        memory[0x9380] = 150
        memory[0x9381] = 71
        memory[0x9b80] = 3
        self.assertEqual(requests(memory), [(i, 0, 1, 1) for i in (131, 130, 129, 128)])

    def test_reject_unsupported(self):
        with self.assertRaises(ValueError):
            requests(bytes(10))
        memory = bytearray(65536)
        memory[0xa007] = 1
        with self.assertRaises(ValueError):
            requests(memory)


if __name__ == '__main__':
    unittest.main()
