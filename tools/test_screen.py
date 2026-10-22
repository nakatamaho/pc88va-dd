# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Synthetic checks of static display asset packing."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_screen import rle, palette_word, source_palette


class ScreenTests(unittest.TestCase):
    def test_rle_roundtrip(self):
        for source in (b'', bytes(71680), bytes(range(32)) * 2240,
                       bytes([17]) * 255 + bytes([31]) * 256):
            packed = rle(source)
            result = bytearray()
            offset = 0
            while packed[offset]:
                result.extend(bytes([packed[offset + 1]]) * packed[offset])
                offset += 2
            self.assertEqual(offset, len(packed) - 1)
            self.assertEqual(result, source)

    def test_palette_fields(self):
        self.assertEqual(palette_word(0, 0, 0), 0)
        self.assertEqual(palette_word(255, 0, 0), 0x03c0)
        self.assertEqual(palette_word(0, 255, 0), 0xf000)
        self.assertEqual(palette_word(0, 0, 255), 0x001e)
        self.assertEqual(palette_word(255, 255, 255), 0xf3de)

    def test_resistor_extremes(self):
        self.assertEqual(source_palette(bytes([0, 7, 56, 192, 255])),
                         [0, 0x03c0, 0xf000, 0x001e, 0xf3de])


if __name__ == '__main__':
    unittest.main()
