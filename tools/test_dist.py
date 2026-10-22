# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""ROM-free tests of the distribution's disk layout, payload and FMVOICE.DAT."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ddisk
import ddpayload
import patches


def synthetic_source():
    """Made-up ROM contents of the right sizes (no ROM data)."""
    sizes = {'chars': 2048, 'sprites1': 4096, 'sprites2': 4096, 'sprites3': 4096,
             'sprites4': 4096, 'bgtiles': 4096, 'bgmaps': 4096, 'palette': 32,
             'spritelookup': 256, 'bglookup': 256, 'waves': 256}
    return {role: bytes(0 if i % 97 else (i * 37 + len(role)) & 255 for i in range(size))
            for role, size in sizes.items()}


class DistTests(unittest.TestCase):
    def test_layout(self):
        self.assertEqual(ddpayload.LOAD_SECTORS, 55)
        self.assertEqual(ddpayload.STAGE_FIRST_SECTOR, 56)
        self.assertEqual(ddpayload.PROGRAM_OFFSET, 25 * 1024)
        self.assertLessEqual(ddpayload.PROGRAM_OFFSET + ddpayload.PROGRAM_BYTES, ddpayload.STAGE_OFFSET)
        self.assertLessEqual(ddpayload.CODE_BYTES + ddpayload.TABLE_BYTES, 0x9000)
        self.assertLessEqual(ddpayload.FM_SLOT + ddpayload.FM_HEADER.size + ddpayload.FM_BYTES,
                             ddpayload.STAGE_BYTES)
        self.assertIn('%define L_TABLE_BYTES 9400', ddpayload.include())

    def test_static_symbols(self):
        symbols = patches.static_symbols()
        self.assertEqual(symbols['MAIN_SEGMENT_BYTES'] + symbols['SOUND_SEGMENT_BYTES'],
                         ddpayload.PROGRAM_BYTES)
        self.assertIn('Z80_ENTER', patches.nasm_include_static())

    def test_disk_round_trip(self):
        image = bytes((i * 7) & 255 for i in range(ddisk.IMAGE_BYTES))
        data = ddisk.write('DD-PC88VA', image)
        self.assertEqual(ddisk.read(data), ('DD-PC88VA', image))
        with self.assertRaises(ValueError):
            ddisk.read(data[:-1])
        broken = bytearray(data)
        broken[0x1B] = 0
        with self.assertRaises(ValueError):
            ddisk.read(bytes(broken))

    def test_staged_area(self):
        program = bytes(range(256)) * (ddpayload.PROGRAM_BYTES // 256)
        area = ddpayload.staged(synthetic_source(), 'rev2', program)
        self.assertEqual(len(area), ddpayload.STAGE_BYTES)
        info = ddpayload.check_staged(area, program)
        self.assertEqual(info['revision'], 'rev2')
        self.assertFalse(any(area[ddpayload.FM_SLOT:]))
        damaged = bytearray(area)
        damaged[info['end'] - 1] ^= 1
        with self.assertRaises(ValueError):
            ddpayload.check_staged(bytes(damaged))
        with self.assertRaises(ValueError):
            ddpayload.check_staged(area, program[:-1] + b'\x01')
        with self.assertRaises(ValueError):
            ddpayload.check_staged(bytes(ddpayload.STAGE_BYTES))

    def test_container_search(self):
        """ROMs stored inside a larger file at any offset (synthetic data)."""
        import hashlib
        import zlib
        import roms
        pieces = {'a': bytes((i * 11 + 3) & 255 for i in range(256)),
                  'b': bytes((i * 5 + 1) & 255 for i in range(4096))}
        table = {role: (len(d), zlib.crc32(d), hashlib.sha1(d).hexdigest()) for role, d in pieces.items()}
        blob = bytes(1001) + pieces['b'] + bytes(37) + pieces['a'] + bytes(5000)   # unaligned
        found = {}
        roms._search(blob, table, found)
        self.assertEqual(found, pieces)
        wrong = dict(table, a=(256, table['a'][1], '0' * 40))                     # SHA-1 mismatch
        found = {}
        roms._search(blob, wrong, found)
        self.assertNotIn('a', found)

    def test_fm_file(self):
        voices = bytes((i % 9 == 0) * 7 or (i % 2) * 3 + 1 for i in range(ddpayload.FM_BYTES))
        for method in (1, 2):
            data = ddpayload.fm_file(voices, method)
            self.assertEqual(len(data), 164)
            self.assertEqual(ddpayload.parse_fm_file(data), (method, voices))
        damaged = bytearray(ddpayload.fm_file(voices, 2))
        damaged[-1] ^= 1
        with self.assertRaises(ValueError):
            ddpayload.parse_fm_file(bytes(damaged))
        with self.assertRaises(ValueError):
            ddpayload.fm_file(bytes([64]) + voices[1:], 2)
        with self.assertRaises(ValueError):
            ddpayload.fm_file(voices, 3)


if __name__ == '__main__':
    unittest.main()
