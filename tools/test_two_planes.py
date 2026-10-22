# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""ROM-free packed-plane and palette-bank tests."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_two_planes import compose, fixture, packed
from check_packed_sgp import expected, synthetic, stress_pieces, placement, CLIPS
from cache_directory import RetainedCache


class PlaneTests(unittest.TestCase):
    def test_transparency_and_black(self):
        self.assertEqual(compose(bytes((5,6,7)), bytes((0,1,15))), bytes((5,17,31)))
        self.assertEqual(compose(bytes((5,6,7)), bytes((0,1,15)), False), bytes((16,17,31)))

    def test_packing(self):
        self.assertEqual(packed(bytes((1,2,3,4))), bytes((0x12,0x34)))
        with self.assertRaises(ValueError):
            packed(bytes((0,16)))
        with self.assertRaises(ValueError):
            packed(bytes((0,)))

    def test_size_mismatch(self):
        with self.assertRaises(ValueError):
            compose(bytes(2), bytes(1))

    def test_packed_cache_capacity(self):
        cache = RetainedCache()
        pieces = stress_pieces()
        for i, (code, colour, fx, fy) in enumerate(pieces):
            slot, inserted, _ = cache.lookup(code | (colour << 8) | (fx << 14))
            self.assertTrue(inserted)
            self.assertEqual(slot, i)
        self.assertEqual(cache.used*128, 65536)
        for code, colour, fx, fy in pieces:
            self.assertFalse(cache.lookup(code | (colour << 8) | (fx << 14))[1])

    def test_clipped_packed_oracle(self):
        pens, lookup, _, pieces = synthetic()
        entries = [(piece, CLIPS[i % len(CLIPS)]) for i,piece in enumerate(pieces)]
        a = expected(pens, lookup, entries)
        b = expected(pens, lookup, entries, True)
        self.assertEqual(len(a), 35840)
        self.assertNotEqual(a, b)
        self.assertEqual(placement(127), (304,208))
        self.assertEqual(a[-1], 0x88)  # untouched final byte, no nibble spill

    def test_layout_and_colours(self):
        colours, background, fronts = fixture()
        self.assertEqual(len(set(colours)), 32)
        self.assertEqual(colours[17], (0,0,0))
        for image in (background, *fronts):
            self.assertEqual(len(packed(image)), 35840)
            self.assertEqual(set(image), set(range(16)))
        self.assertLessEqual(2*35840, 0x20000)
        self.assertLessEqual(0x20000+35840, 0x40000)
        self.assertNotEqual(fronts[0], fronts[1])


if __name__ == '__main__':
    unittest.main()
