# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Synthetic graphics tests: no ROM files are required."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gfx


class GraphicsTests(unittest.TestCase):
    def test_character_bit_order(self):
        data = bytes([1]) + bytes(7)
        self.assertEqual(gfx.characters(data), bytes([1]) + bytes(63))

    def test_background_planes_and_halves(self):
        data = bytearray(16)
        data[8] = 0x80
        data[0] = 0x08
        expected = bytearray(64)
        expected[0], expected[4] = 2, 1
        self.assertEqual(gfx.background(data), expected)

    def test_sprite_quadrants(self):
        data = bytearray(64)
        data[0], data[16], data[32], data[48] = 0x80, 0x08, 0x88, 0x80
        expected = bytearray(256)
        expected[0], expected[8], expected[128], expected[136] = 2, 1, 3, 2
        self.assertEqual(gfx.sprites(data), expected)

    def test_character_stride(self):
        self.assertEqual(gfx.characters(bytes(8) + bytes([255]) * 8),
                         bytes(64) + bytes([1]) * 64)

    def test_sizes(self):
        self.assertEqual(len(gfx.characters(bytes(2048))), 256 * 64)
        self.assertEqual(len(gfx.background(bytes(4096))), 256 * 64)
        self.assertEqual(len(gfx.sprites(bytes(16384))), 256 * 256)

    def test_reject_partial(self):
        with self.assertRaises(ValueError):
            gfx.background(bytes(15))


if __name__ == '__main__':
    unittest.main()
