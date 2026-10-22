# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Check packed-4bpp retained SGP pixels, clipped nibbles and both front pages.

Default sources are synthetic. --snapshot selects real-source sprite pieces;
--stress exercises 512 unique keys, not 512 simultaneous game objects.
Timings exclude background reset, initial source expansion and RAM guards.
"""

import argparse
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d88
import roms
from render import Renderer
from build_screen import rle, palette_word, source_palette
from check_sgp_cache import requests
from check_pages import address, registers
from check_two_planes import packed
from cache_directory import RetainedCache

CLIPS = ((0,0,16,16), (1,0,15,16), (2,1,13,15), (3,2,11,12), (0,3,16,11))


def synthetic():
    pens = bytes((x//4+3*(y//3)+code+(x == 1 and y == code % 16)) & 3
                 for code in range(256) for y in range(16) for x in range(16))
    lookup = bytes(v for colour in range(64) for v in (15,0,colour % 14+1,(colour*5) % 14+1))
    palette = [palette_word((i & 3)*85, ((i >> 2)&3)*85, (i >> 4)*255) for i in range(32)]
    palette[16] = 0
    pieces = [(i & 15, i, (i >> 1)&1, i&1) for i in range(32)]
    return pens, lookup, palette, pieces


def stress_pieces():
    return [(i & 255, (i >> 8)*17+(i & 3), (i >> 4)&1, (i >> 5)&1) for i in range(512)]


def placement(index):
    index %= 128
    col, row = index % 16, index // 16
    x = 304 if col == 15 else row & 1 if col == 0 else 16+col*18+(index & 1)
    return x, (0,28,56,84,112,140,168,208)[row]


def expected(pens, lookup, entries, invert_y=False):
    out = bytearray([8])*71680
    for i, (piece, clip) in enumerate(entries):
        code, colour, fx, fy = piece
        fy ^= invert_y
        left, top, width, height = clip
        dx,dy = placement(i)
        for y in range(top, top+height):
            for x in range(left, left+width):
                pen = pens[code*256+(15-y if fy else y)*16+(15-x if fx else x)]
                nibble = (lookup[colour*4+pen]+1) & 15
                if nibble:
                    out[(dy+y)*320+dx+x] = nibble
    return packed(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vaeg', type=Path, required=True)
    parser.add_argument('--bios', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--roms', type=Path, default=roms.DEFAULT)
    parser.add_argument('--stress', action='store_true')
    args = parser.parse_args()
    if args.snapshot:
        source = roms.load(args.roms)
        pens, lookup = Renderer(source).sprites, source['spritelookup']
        palette, pieces = source_palette(source['palette']), requests(args.snapshot.read_bytes())
    else:
        pens, lookup, palette, pieces = synthetic()
    if args.stress:
        pieces = stress_pieces()
        entries = [(piece, CLIPS[i % len(CLIPS)]) for i,piece in enumerate(pieces)]
    else:
        entries = [(piece, clip) for clip in CLIPS for piece in pieces]
    if not entries:
        parser.error('no visible pieces')
    keys = {code | (colour << 8) | (fx << 14) for (code,colour,fx,fy), clip in entries}
    if len(keys) > 512:
        parser.error('input exceeds 512 retained keys')
    root = d88.REPO / 'build/packed-sgp'
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    disk = out / 'packed.d88'
    palette = palette[:16] + palette[31:32] + palette[16:31]
    data = bytearray(struct.pack('<32H', *palette)+rle(bytes([0x88])*35840))
    pen_address = 8192+len(data)
    data.extend(rle(pens))
    lookup_address = 8192+len(data)
    data.extend(lookup)
    if len(data) & 1:
        data.append(0)
    records_address = 8192+len(data)
    for i, ((code,colour,fx,fy), clip) in enumerate(entries):
        x,y = placement(i)
        key = code | (colour << 8) | (fx << 14)
        data.extend(struct.pack('<11H', key, code*256, lookup_address+colour*4, fx, fy,
                                y*160+x//2, x&1, *clip))
    definitions = f'%define P_PENS {pen_address}\n%define P_RECORDS {records_address}\n%define P_COUNT {len(entries)}\n'
    d88.build_boot_disk(d88.REPO / 'src/m02/screen.asm', definitions, bytes(data), disk,
                        'DDM02PACKED', 8192, ['PACKED_PROBE=1', 'CODE_BYTES=8192'],
                        listing=disk.with_suffix('.lst'))
    listing = disk.with_suffix('.lst').read_text()
    begin, end, guard = (address(listing, label) for label in ('packed_begin', 'packed_end', 'packed_guard_passed'))
    script = 'debug-script 1\nlimit-frame 3000\n'
    for i in range(3):
        script += (f'wait-pc {begin} 1\ncapture begin{i} registers\n'
                   f'wait-pc {end} 1\ncapture end{i} registers gvram\n'
                   f'wait-pc {guard} 1\ncapture guard{i} registers\n')
    (out / 'run.debug').write_text(script+'exit\n')
    (out / 'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\n')
    with (out / 'vaeg.log').open('w') as log:
        subprocess.run([str(args.vaeg.resolve()), '--cfg', str(out / 'va.cfg'),
                        '--no-bkupmem', '--nowait', '--mute', '--roms', str(args.bios.resolve()),
                        '--fdd1', str(disk), '--debug-script', str(out / 'run.debug'),
                        '--debug-output-dir', str(out)],
                       env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'),
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=240)
    expected_a = expected(pens, lookup, entries)
    expected_b = expected(pens, lookup, entries, True)
    (out / 'expected-a.bin').write_bytes(expected_a)
    (out / 'expected-b.bin').write_bytes(expected_b)
    model = RetainedCache()
    report = ['pass,requests,keys,hits,misses,probes,clocks']
    for i, name in enumerate(('cold_A', 'warm_A', 'warm_B_opposite_Y')):
        a = registers(out / f'begin{i}.registers.tsv')
        b = registers(out / f'end{i}.registers.tsv')
        if int(a['ax'],16) != i or not (out / f'guard{i}.registers.tsv').exists():
            sys.exit(f'event/guard failure: {out}')
        image = (out / f'end{i}.gvram.bin').read_bytes()
        wanted = bytearray([0x5a])*262144
        wanted[:35840] = expected_a
        if i == 2:
            wanted[35840:71680] = expected_b
        wanted[0x20000:0x28c00] = bytes([0x88])*35840
        if image != wanted:
            count = sum(a != b for a,b in zip(image, wanted))
            sys.exit(f'{name}: GVRAM differs ({count} bytes), including guards; {out}')
        misses = probes = 0
        for (code,colour,fx,fy), clip in entries:
            _, inserted, searched = model.lookup(code | (colour << 8) | (fx << 14))
            misses += inserted
            probes += searched
        actual = tuple(int(b[r],16) for r in ('bx','dx','si','bp'))
        if actual != (len(entries)-misses, misses, model.used, probes & 65535):
            sys.exit(f'directory differs from host model: {actual}; {out}')
        report.append(f'{name},{len(entries)},{model.used},{actual[0]},{actual[1]},{actual[3]},'
                      f'{int(b["clock"])-int(a["clock"])}')
    text = '\n'.join(report)+'\n'
    (out / 'results.csv').write_text(text)
    print(text+str(out))


if __name__ == '__main__':
    main()
