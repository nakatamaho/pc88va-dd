# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""ROM-free compact-trace and retained-directory tests."""

from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cache_directory import RetainedCache
from trace_cache import records


class GrowthTests(unittest.TestCase):
    def test_collision_retains_slots(self):
        cache = RetainedCache()
        keys = (0, 0x408, 0x810)
        for i, key in enumerate(keys):
            self.assertEqual(cache.lookup(key), (i, True, i+1))
        for i, key in enumerate(keys):
            self.assertEqual(cache.lookup(key), (i, False, i+1))
        self.assertEqual(cache.used, 3)

    def test_capacity_never_evicts(self):
        cache = RetainedCache()
        for i in range(512):
            self.assertEqual(cache.lookup(i)[0:2], (i, True))
        with self.assertRaises(OverflowError):
            cache.lookup(512)
        for i in range(512):
            self.assertEqual(cache.lookup(i)[0:2], (i, False))

    def test_invalid_key(self):
        with self.assertRaises(ValueError):
            RetainedCache().lookup(32768)

    def test_compact_record(self):
        record = bytearray(struct.pack('<I', 123) + bytes(385))
        record[4] = 9
        record[5] = 3
        record[4+128] = 200
        record[5+128] = 71
        record[4+256] = 3
        self.assertEqual(list(records(record)), [(123, [(9, 3, 1, 1)])])

    def test_partial_record(self):
        with self.assertRaises(ValueError):
            list(records(bytes(388)))


if __name__ == '__main__':
    unittest.main()
