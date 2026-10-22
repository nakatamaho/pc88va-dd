# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Measure first-use sprite cache growth over every reference-emulator frame.

This records RAM requests, not pixel-verified rendered frames. Visibility is
bounding-box visibility; hidden/overlapped pieces are still counted. Global
screen flip is not supported. Outputs are private, ignored build artifacts.
"""

import argparse
import csv
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roms
from render import Renderer
from check_sgp_cache import requests

REPO = Path(__file__).resolve().parents[1]
RECORD_BYTES = 389


def records(data: bytes):
    if len(data) % RECORD_BYTES:
        raise ValueError('partial cache-trace record')
    for offset in range(0, len(data), RECORD_BYTES):
        record = data[offset:offset+RECORD_BYTES]
        frame, = struct.unpack_from('<I', record)
        memory = bytearray(65536)
        for i, base in enumerate((0x8b80, 0x9380, 0x9b80)):
            memory[base:base+128] = record[4+i*128:4+(i+1)*128]
        memory[0xa007] = record[-1]
        yield frame, requests(memory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mame', type=Path, required=True)
    parser.add_argument('--system', required=True)
    parser.add_argument('--rompath', type=Path, required=True)
    parser.add_argument('--roms', type=Path, default=roms.DEFAULT)
    parser.add_argument('--frames', type=int, default=6000)
    args = parser.parse_args()
    if args.frames < 1:
        parser.error('--frames must be positive')
    renderer = Renderer(roms.load(args.roms))
    root = REPO / 'build/cache-trace'
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    with tempfile.TemporaryDirectory(prefix='dd-cache-') as tmp:
        with (out / 'mame.log').open('w') as log:
            subprocess.run([str(args.mame.resolve()), args.system, '-rompath', str(args.rompath.resolve()),
                            '-nvram_directory', tmp, '-cfg_directory', tmp, '-video', 'none',
                            '-sound', 'none', '-nothrottle', '-skip_gameinfo', '-autoboot_delay', '0',
                            '-autoboot_script', str(REPO / 'tools/mame/cache_trace.lua')],
                           env=dict(os.environ, DD_OUT=str(out / 'sprites.bin'), DD_FRAMES=str(args.frames)),
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
    if '[LUA ERROR]' in (out / 'mame.log').read_text():
        sys.exit(f'trace failed; see {out}')
    data = (out / 'sprites.bin').read_bytes()
    if len(data) != RECORD_BYTES * args.frames:
        sys.exit(f'wrong trace size: {out}')
    first, nonempty, empty = {}, set(), {}
    checkpoints = {30,60,120,180,240,300,600,899,999,1000,1200,1800,3000,args.frames}
    summary = ['frame,total_keys,pixel_KiB,nonempty_keys']
    overflow = None
    with (out / 'growth.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(('frame', 'requests', 'new_keys', 'resident_keys', 'nonempty_keys'))
        for ordinal, (frame, pieces) in enumerate(records(data), 1):
            if frame != ordinal:
                sys.exit('trace frames are not consecutive')
            added = 0
            for code, colour, fx, fy in pieces:
                key = code, colour, fx
                if key not in first:
                    first[key] = frame
                    added += 1
                if (code, colour) not in empty:
                    empty[code, colour] = all((renderer.sprlookup[colour*4+pen] & 15) == 15
                                             for pen in renderer.sprites[code*256:(code+1)*256])
                if not empty[code, colour]:
                    nonempty.add(key)
            writer.writerow((frame, len(pieces), added, len(first), len(nonempty)))
            if overflow is None and len(first) > 256:
                overflow = frame
            if frame in checkpoints:
                summary.append(f'{frame},{len(first)},{len(first)/4:.2f},{len(nonempty)}')
    with (out / 'first-use.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(('code', 'colour', 'xflip', 'first_frame', 'transparent_only'))
        for (code, colour, fx), frame in sorted(first.items(), key=lambda pair: (pair[1], pair[0])):
            writer.writerow((code, colour, fx, frame, int(empty[code, colour])))
    report = '\n'.join(summary) + '\n'
    report += f'Keys first used at/after scripted start (frame 1000): {sum(f >= 1000 for f in first.values())}\n'
    report += f'First frame exceeding 256 keys: {overflow}\n'
    report += 'Coin is scripted at 900; start at 1000. These are not boot-test completion markers.\n'
    (out / 'summary.txt').write_text(report)
    print(report + str(out))


if __name__ == '__main__':
    main()
