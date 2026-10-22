# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""ROM-free inverse-row mapping and snapshot delta tests."""

from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_screen import state_delta, tile_rows
from render import tile_index
from check_native import framebuffer, FRONT_B, BLANK


class NativeStateTests(unittest.TestCase):
    def test_packed_page_composition(self):
        raw = bytearray([0x5a])*262144
        raw[:0x12400] = bytes(0x12400)
        for a,b in BLANK:
            raw[a:b] = bytes(b-a)
        raw[0x20000:0x28c00] = bytes([0x88])*35840
        raw[0] = 0x10            # opaque black then transparent
        raw[FRONT_B] = 0xf0      # highest opaque sprite colour then transparent
        self.assertEqual(framebuffer(raw,True,0)[:2], bytes((16,8)))
        self.assertEqual(framebuffer(raw,True,FRONT_B // 16)[:2], bytes((30,8)))
        with self.assertRaises(ValueError):
            framebuffer(raw,True,1)
        raw[0x8c00] = 1          # the margin between the fronts must stay blank
        with self.assertRaises(ValueError):
            framebuffer(raw,True,0)
        raw[0x8c00] = 0
        raw[0x12400] = 0         # unused bytes keep their canary
        with self.assertRaises(ValueError):
            framebuffer(raw,True,0)

    def test_inverse_rows(self):
        rows = tile_rows()
        self.assertEqual(len(rows), 1024)
        self.assertEqual(rows.count(255), 16)
        for y in range(28):
            self.assertEqual(rows.count(y), 36)
            for x in range(36):
                self.assertEqual(rows[tile_index(x, y)], y)

    def test_unchanged_delta(self):
        self.assertEqual(state_delta(bytes(1416), bytes(1416)), b'\xff\xff')

    def test_delta_roundtrip(self):
        before = bytes(1416)
        after = bytes(i & 255 for i in range(1416))
        delta = state_delta(before, after)
        result = bytearray(before)
        pos = 0
        while True:
            index, = struct.unpack_from('<H', delta, pos)
            pos += 2
            if index == 65535:
                break
            result[index] = delta[pos]
            pos += 1
        self.assertEqual(bytes(result), after)
        self.assertEqual(pos, len(delta))

    def test_invalid_state_size(self):
        with self.assertRaises(ValueError):
            state_delta(bytes(1415), bytes(1416))


if __name__ == '__main__':
    unittest.main()
