# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""ROM-free WSG/SSG decoding and target arithmetic tests."""

from pathlib import Path
import sys
import math
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from sound import decode, target, Voice, PERIOD_NUMERATOR, VOLUME, check_ssg
from fmvoice import additive, validate, generate, pitch


class SoundTests(unittest.TestCase):
    def test_fm_profiles_and_cache(self):
        prom = bytes(round(7.5+7.5*math.sin(2*math.pi*i/32)) for i in range(32))*8
        profiles = additive(prom)
        self.assertEqual(len(profiles),144)
        for offset in range(0,144,18):
            self.assertEqual(profiles[offset],7)
            self.assertEqual(profiles[offset:offset+9],profiles[offset+9:offset+18])
            self.assertIn(1,profiles[offset+1:offset+9:2])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(generate(prom,'fm-lite',root),profiles)
            self.assertEqual(generate(prom,'fm-lite',root),profiles)
            self.assertEqual(len(list(root.glob('*.bin'))),1)
        silent = additive(bytes(256))
        self.assertTrue(all(silent[o+i] == 127 for o in range(0,144,9) for i in (2,4,6,8)))
        with self.assertRaises(ValueError):
            validate(bytes(143))

    def test_fm_pitch(self):
        for frequency in (1,332,333,2048,6291,6292,65535,65536,681574,1048575):
            for exact in (False,True):
                packed = pitch(frequency,exact)
                self.assertTrue(1 <= packed >> 11 <= 7)
                self.assertTrue(0 <= packed&2047 <= 2047)
        self.assertNotEqual(pitch(26,False),pitch(26,True))
        with self.assertRaises(ValueError):
            pitch(1 << 20)

    def test_register_nibbles(self):
        raw = bytearray([0xf0])*32
        raw[0x10:0x15] = bytes((1,2,3,4,5))
        raw[0x16:0x1a] = bytes((6,7,8,9))
        raw[0x1b:0x1f] = bytes((10,11,12,13))
        raw[0x15],raw[0x1a],raw[0x1f] = 0xe3,0xa7,0xff
        raw[5],raw[10],raw[15] = 0xfd,0xea,0xf7
        voices = decode(raw)
        self.assertEqual(voices,(Voice(0x54321,3,5),Voice(0x98760,7,2),Voice(0xdcba0,15,7)))

    def test_pitch_boundaries(self):
        self.assertEqual(PERIOD_NUMERATOR,1363148)
        for freq in (1,332,333,65535,65536,681574,1048575):
            period,level = target(Voice(freq,15,0))
            self.assertEqual(period,max(1,min(4095,1363148//freq)))
            self.assertEqual(level,15)
        self.assertEqual(target(Voice(0,15,0)),(None,0))
        self.assertEqual(target(Voice(1000,0,0)),(None,0))

    def test_levels_monotonic(self):
        self.assertEqual(tuple(sorted(VOLUME)),VOLUME)
        self.assertEqual(VOLUME[0],0)
        self.assertTrue(all(0 < v <= 15 for v in VOLUME[1:]))

    def test_shadow_validation(self):
        raw = bytearray(32)
        raw[0x12],raw[0x15] = 1,15
        period,level = target(decode(raw)[0])
        regs = bytearray(16)
        regs[7] = 0xf8
        regs[0],regs[1],regs[8] = period&255,period>>8,level
        self.assertEqual(check_ssg(raw,regs),1)
        regs[0] ^= 1
        with self.assertRaises(ValueError):
            check_ssg(raw,regs)
        with self.assertRaises(ValueError):
            decode(bytes(31))


if __name__ == '__main__':
    unittest.main()
