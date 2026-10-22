# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""ROM-free tests of host composition using synthetic source pens."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import Renderer, tile_index, WIDTH, HEIGHT


class RenderTests(unittest.TestCase):
    def setUp(self):
        # Deliberately bypass decoding: test composition independently.
        self.r = Renderer.__new__(Renderer)
        self.r.chars = bytearray(256 * 64)
        self.r.bg = bytearray(256 * 64)
        self.r.sprites = bytearray(256 * 256)
        self.r.maps = bytearray(4096)
        self.r.bglookup = bytearray([3] * 256)
        self.r.sprlookup = bytearray([15] * 256)
        self.m = bytearray(65536)

    def sprite(self, code=0, x=32, y=48, flip=0):
        self.m[0x8b80] = code
        self.m[0x9381] = x + 39
        self.m[0x9380] = (257 - y - 32 - 16 * (code >> 7)) & 255
        self.m[0x9b80] = flip

    def test_tile_mapping(self):
        indices = {tile_index(x, y) for y in range(28) for x in range(36)}
        self.assertEqual(len(indices), 1008)
        self.assertTrue(all(0 <= i < 1024 for i in indices))
        self.assertEqual(tile_index(2, 0), 64)
        self.assertEqual(tile_index(0, 0), 962)
        self.assertEqual(tile_index(35, 27), 61)

    def test_background(self):
        self.assertEqual(self.r.render(self.m), bytes([3]) * (WIDTH * HEIGHT))

    def test_character_colour_and_transparency(self):
        self.m[0x8000 + tile_index(2, 0)] = 0x91
        self.r.chars[0x11 * 64] = 1
        pixels = self.r.render(self.m)
        self.assertEqual(pixels[16:18], bytes([10, 3]))
        self.m[0xa002] = 1
        self.assertEqual(self.r.render(self.m)[16], 1)

    def test_background_page_bank_disable(self):
        self.m[0xa000] = 1
        self.m[0xa004] = 1
        self.r.maps[1024 + tile_index(2, 0)] = 0x20
        self.r.bglookup[0x12 * 4] = 7
        self.assertEqual(self.r.render(self.m)[16], 7)
        self.m[0xa003] = 1
        self.r.bglookup[0x1f * 4] = 0
        self.assertEqual(self.r.render(self.m)[16], 0)

    def test_sprite_transparency_flip(self):
        self.sprite()
        self.r.sprites[0] = 1
        self.r.sprlookup[1] = 5
        pixels = self.r.render(self.m)
        self.assertEqual(pixels[48 * WIDTH + 32:48 * WIDTH + 34], bytes([21, 3]))
        self.m[0x9b80] = 3
        pixels = self.r.render(self.m)
        self.assertEqual(pixels[63 * WIDTH + 47], 21)
        self.assertEqual(pixels[48 * WIDTH + 32], 3)

    def test_large_sprite_tile_order(self):
        self.sprite(code=128)
        for i in range(4):
            self.r.sprites[(128 + i) * 256:(129 + i) * 256] = bytes([i]) * 256
            self.r.sprlookup[i] = i
        for flip in range(4):
            self.m[0x9b80] = flip
            pixels = self.r.render(self.m)
            for y in range(2):
                for x in range(2):
                    expected = 16 + ((y ^ (flip >> 1)) * 2 + (x ^ (flip & 1)))
                    self.assertEqual(pixels[(48 + y * 16) * WIDTH + 32 + x * 16], expected)

    def test_sprite_wrap_and_clip(self):
        self.sprite(x=-1)
        self.r.sprites[:256] = bytes([1]) * 256
        self.r.sprlookup[1] = 5
        pixels = self.r.render(self.m)
        self.assertEqual(pixels[48 * WIDTH + 254], 3)
        self.assertEqual(pixels[48 * WIDTH + 255:48 * WIDTH + 271], bytes([21]) * 16)
        self.assertEqual(pixels[48 * WIDTH + 271], 3)

    def test_sprite_priority_and_edge_clip(self):
        self.sprite(x=8)
        self.r.sprites[:256] = bytes([1]) * 256
        self.r.sprlookup[1] = 5
        self.r.sprlookup[5] = 6
        # A later entry at the same position must cover the first.
        self.m[0x8b83] = 1
        self.m[0x9382:0x9384] = self.m[0x9380:0x9382]
        pixels = self.r.render(self.m)
        self.assertEqual(pixels[48 * WIDTH + 15], 3)
        self.assertEqual(pixels[48 * WIDTH + 16:48 * WIDTH + 24], bytes([22]) * 8)
        self.assertEqual(pixels[48 * WIDTH + 24], 3)

    def test_reject_unsupported_snapshot(self):
        with self.assertRaises(ValueError):
            self.r.render(bytes(1024))
        self.m[0xa007] = 1
        with self.assertRaises(ValueError):
            self.r.render(self.m)


if __name__ == '__main__':
    unittest.main()
