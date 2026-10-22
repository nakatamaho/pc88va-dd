# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""ROM-free checks of incremental video-state fixtures."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from video_cases import cases


class VideoCasesTests(unittest.TestCase):
    def test_sizes_and_input(self):
        source = bytes(65536)
        result = cases(source)
        self.assertEqual(len(result), 7)
        self.assertTrue(all(len(data) == 65536 for data in result.values()))
        self.assertEqual(result['base'], source)
        self.assertEqual(source, bytes(65536))

    def test_single_changes(self):
        result = cases(bytes(65536))
        for name in ('tile', 'latch', 'sprite'):
            changed = [i for i, value in enumerate(result[name]) if value]
            self.assertEqual(len(changed), 1)
        self.assertNotEqual(result['edges'], result['moved'])
        # The top-clipped entry becomes fully hidden in the moved state.
        memory = result['moved']
        size = memory[0x8b82] >> 7
        y = ((257 - memory[0x9382] - 16 * size) & 255) - 32
        self.assertEqual(y, -32)

    def test_reject_size(self):
        with self.assertRaises(ValueError):
            cases(bytes(65535))


if __name__ == '__main__':
    unittest.main()
