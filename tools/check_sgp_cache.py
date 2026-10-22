# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Measure real-source palette/X-flip conversion and SGP cache costs.

Select visible 16x16 pieces from a video snapshot, then place them in a
synthetic grid. This includes conversion and cache management, not a full
game frame: clipping, restoration and scheduler costs are excluded. Y flip
uses SGP negative pitch. Raw pens are decoded at build time, as in M02.
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
import d88
import roms
from render import Renderer
from build_screen import rle, source_palette
from check_pages import address, registers
from cache_directory import RetainedCache

CODE_BYTES = 8192


def requests(memory: bytes) -> list[tuple[int, int, int, int]]:
    if len(memory) != 65536 or memory[0xa007] & 1:
        raise ValueError('requires an unflipped 64 KiB video snapshot')
    result = []
    for off in range(0, 128, 2):
        code, colour = memory[0x8b80+off], memory[0x8b81+off] & 63
        size = code >> 7
        sx = memory[0x9381+off] - 39
        sy = ((257 - memory[0x9380+off] - 16*size) & 255) - 32
        fx, fy = memory[0x9b80+off] & 1, (memory[0x9b80+off] >> 1) & 1
        if size:
            code = (code & 192) | ((code & 63) << 2)
        for y in range(size+1):
            for x in range(size+1):
                left, top = (sx+16*x) & 255, sy+16*y
                if top >= 224 or top+16 <= 0:
                    continue
                if not any(left+w < 272 and left+w+16 > 16 for w in (0, 256)):
                    continue
                tile = (code + (y ^ (size*fy))*2 + (x ^ (size*fx))) & 255
                result.append((tile, colour, fx, fy))
    return result


def build(source, snapshot, disk, first_use=None, until=None):
    memory = snapshot.read_bytes()
    all_requests = requests(memory)
    if first_use is not None:
        with first_use.open(newline='') as stream:
            all_requests = [(int(row['code']), int(row['colour']), int(row['xflip']), 0)
                            for row in csv.DictReader(stream)
                            if until is None or int(row['first_frame']) <= until]
    selected = all_requests[:512]
    if not selected:
        raise ValueError('snapshot has no visible sprite pieces')
    renderer = Renderer(source)
    background = bytes([8]) * 71680
    data = bytearray(struct.pack('<32H', *source_palette(source['palette'])) + rle(background))
    lookup = CODE_BYTES + len(data)
    data.extend(source['spritelookup'])
    pens = CODE_BYTES + len(data)
    data.extend(rle(renderer.sprites))
    keys = {}
    records = CODE_BYTES + len(data)
    expected = bytearray(background)
    for i, (code, colour, fx, fy) in enumerate(selected):
        key = code | (colour << 8) | (fx << 14)
        keys[(code, colour, fx)] = key
        position = i % 128         # a trace manifest can exceed one grid
        left, top = 16 + (position % 16)*18 + (position & 1), 16 + (position // 16)*24
        data.extend(struct.pack('<6H', key, code*256, lookup+colour*4, fx, fy, top*320+left))
        for y in range(16):
            for x in range(16):
                pen = renderer.sprites[code*256 + (15-y if fy else y)*16 + (15-x if fx else x)]
                colour_index = source['spritelookup'][colour*4+pen] & 15
                if colour_index != 15:
                    expected[(top+y)*320+left+x] = colour_index | 16
    include = f'%define R_COUNT {len(selected)}\n%define R_RECORDS {records}\n%define R_PENS {pens}\n'
    d88.build_boot_disk(d88.REPO / 'src/m02/screen.asm', include, bytes(data), disk,
                        'DDM02CACHE', CODE_BYTES, ['SGP_CACHE=1', f'CODE_BYTES={CODE_BYTES}'],
                        listing=disk.with_suffix('.lst'))
    return background, bytes(expected), len(all_requests), selected, keys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--roms', type=Path, default=roms.DEFAULT)
    parser.add_argument('--first-use', type=Path, help='replay trace_cache.py first-use manifest instead of one frame')
    parser.add_argument('--until-frame', type=int, help='include manifest entries first used no later than this frame')
    parser.add_argument('--vaeg', required=True, type=Path)
    parser.add_argument('--bios', required=True, type=Path)
    args = parser.parse_args()
    if args.until_frame is not None and args.first_use is None:
        parser.error('--until-frame requires --first-use')
    source = roms.load(args.roms)
    root = d88.REPO / 'build/sgp-cache'
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    disk = out / 'cache.d88'
    background, expected, total, selected, keys = build(source, args.snapshot, disk, args.first_use, args.until_frame)
    listing = disk.with_suffix('.lst').read_text()
    begin, end = (address(listing, 'cache_'+name) for name in ('begin', 'end'))
    script = 'debug-script 1\nlimit-frame 3000\n'
    for i in range(11):
        script += (f'wait-pc {begin} 1\ncapture begin{i} registers\n'
                   f'wait-pc {end} 1\ncapture end{i} registers gvram\n')
    (out / 'run.debug').write_text(script+'exit\n')
    (out / 'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\n')
    with (out / 'vaeg.log').open('w') as log:
        subprocess.run([str(args.vaeg.resolve()), '--cfg', str(out / 'va.cfg'),
                        '--no-bkupmem', '--nowait', '--mute', '--roms', str(args.bios.resolve()),
                        '--fdd1', str(disk), '--debug-script', str(out / 'run.debug'),
                        '--debug-output-dir', str(out)],
                       env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'),
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=240)
    keep = RetainedCache()
    rows = ['method,slots,pass,hits,misses,total_clocks,retained_slots,probes']
    for i in range(11):
        capture = (out / f'end{i}.gvram.bin').read_bytes()
        if (len(capture) != 262144 or capture[:71680] != expected
                or capture[71680:143360] != background):
            sys.exit(f'case {i}: pixels differ; see {out}')
        a = registers(out / f'begin{i}.registers.tsv')
        b = registers(out / f'end{i}.registers.tsv')
        if int(a['ax'], 16) != i:
            sys.exit('nonconsecutive capture')
        hits, misses = int(b['bx'], 16), int(b['dx'], 16)
        if i and hits+misses != len(selected):
            sys.exit('invalid cache counters')
        slots = (0,1,1,16,16,64,64,128,128,512,512)[i]
        method = 'CPU' if i == 0 else 'SGP_keep' if i >= 9 else 'SGP'
        resident, probes = int(b['si'], 16), int(b['bp'], 16)
        if i >= 9:
            model_misses = model_probes = 0
            for code, colour, fx, fy in selected:
                _, inserted, searched = keep.lookup(code | (colour << 8) | (fx << 14))
                model_misses += inserted
                model_probes += searched
            if (resident, misses, probes) != (keep.used, model_misses, model_probes):
                sys.exit('guest retained directory differs from host model')
            if resident != len(keys):
                sys.exit('retained directory lost or duplicated a key')
        if i == 10 and (misses or hits != len(selected)):
            sys.exit('retained cache missed on identical replay')
        rows.append(f'{method},{slots},{"direct" if i == 0 else "cold" if i & 1 else "warm"},'
                    f'{hits},{misses},{int(b["clock"])-int(a["clock"])},{resident},{probes}')
    origin = args.first_use.name if args.first_use else args.snapshot.name
    summary = (f'{origin}: {len(selected)}/{total} selected requests; {len(keys)} cache keys; '
               f'{sum(fx for _,_,fx,_ in selected)} X flips; {sum(fy for _,_,_,fy in selected)} Y flips\n')
    report = '\n'.join(rows)+'\n'
    (out / 'results.csv').write_text(report)
    (out / 'summary.txt').write_text(summary)
    print(summary+report+str(out))


if __name__ == '__main__':
    main()
