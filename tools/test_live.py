# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""ROM-free staged-loader and live video-export layout tests."""

from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import d88
import roms
from check_live import snapshot


class LiveTests(unittest.TestCase):
    def test_explicit_revision(self):
        def find(source, table):
            if table is roms.ROMS:
                return {'sound': b'synthetic'}
            return {role: bytes([i]) for i,role in enumerate(table)}
        with patch.object(roms,'_find',side_effect=find) as mocked:
            result = roms.programs(Path('unused'), 'rev2')
            self.assertEqual(result[0],'rev2')
            self.assertEqual(mocked.call_count,2)
        with self.assertRaises(ValueError):
            roms.programs(Path('unused'),'unknown')

    def test_export_layout(self):
        raw = bytearray([0x5a])*262144
        state = bytes(i & 255 for i in range(1416))
        raw[0x30000:0x30588] = state
        meta = tuple(range(11))
        struct.pack_into('<11H',raw,0x30588,*meta)
        memory, actual, cleaned = snapshot(raw)
        self.assertEqual(actual,meta)
        for a,b,target in ((0,1024,0x8000),(1024,1152,0x8b80),(1152,1280,0x9380),
                           (1280,1408,0x9b80),(1408,1416,0xa000)):
            self.assertEqual(memory[target:target+b-a],state[a:b])
        self.assertEqual(cleaned,bytes([0x5a])*262144)

    def test_export_size(self):
        with self.assertRaises(ValueError):
            snapshot(bytes(100))

    def test_stage_limit(self):
        with self.assertRaises(ValueError):
            d88.build_boot_disk(Path('unused.asm'),' ',b'',Path('unused.d88'),'DDTEST',1024,
                                staged=bytes(65537))

    def test_staged_sector_placement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root/'probe.asm'
            source.write_text('cpu 186\norg 0\nstart: hlt\njmp start\ntimes 1024-($-$$) db 0\n')
            data = bytes((i*13+7)&255 for i in range(1537))
            staged = bytes((i*31+9)&255 for i in range(2051))
            disk = root/'probe.d88'
            sectors = d88.build_boot_disk(source,'',data,disk,'DDTEST',1024,staged=staged)
            self.assertEqual(sectors,3)
            image = disk.read_bytes()
            def sector(index):
                pos = 0x2b0+index*(16+1024)+16
                return image[pos:pos+1024]
            loaded = b''.join(sector(i) for i in range(1,sectors+1))
            self.assertEqual(loaded[1024:1024+len(data)],data)
            self.assertEqual(loaded[1024+len(data):],bytes(sectors*1024-1024-len(data)))
            extra = b''.join(sector(i) for i in range(sectors+1,sectors+4))
            self.assertEqual(extra[:len(staged)],staged)
            self.assertEqual(extra[len(staged):],bytes(len(extra)-len(staged)))


if __name__ == '__main__':
    unittest.main()
