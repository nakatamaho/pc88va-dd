# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Synthetic 8bpp CPU vs SGP restoration and transparent-sprite benchmark.

This is a vaeg timing-model comparison, not a hardware or live-game result.
The bitmap is already expanded/coloured in RAM; no packing, flips or clipping
are timed. Both methods restore all rectangles then draw in painter order.
SGP timing includes fresh command-list construction, submission and busy wait.
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d88
from check_pages import address, registers


def expected_image(background: bytes, size: int, count: int) -> bytes:
    if len(background) != 71680 or size not in (16, 32) or not 0 <= count <= 64:
        raise ValueError('invalid benchmark dimensions')
    out = bytearray(background)
    for i in range(count):
        left = 16 + (i % 16) * 18 + (i & 1)
        top = 16 + (i // 16) * 40
        for y in range(size):
            for x in range(size):
                pen = 0 if (x ^ y) & 3 == 0 else 16 | ((x + y) & 7)
                if pen:
                    out[(top + y) * 320 + left + x] = pen
    return bytes(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vaeg', required=True, type=Path)
    parser.add_argument('--bios', required=True, type=Path)
    args = parser.parse_args()
    root = d88.REPO / 'build/sgp-check'
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    disk = out / 'sgp.d88'
    subprocess.run([sys.executable, '-I', str(d88.REPO / 'tools/build_screen.py'),
                    '--sgp-bench', '--output', str(disk)], check=True)
    listing = disk.with_suffix('.lst').read_text()
    labels = {name: address(listing, 'bench_' + name) for name in
              ('cpu_begin', 'cpu_end', 'sgp_begin', 'sgp_submit', 'sgp_end')}
    script = 'debug-script 1\nlimit-frame 3000\n'
    for i in range(8):
        for name, addr in labels.items():
            kind = ' registers gvram' if name.endswith('_end') else ' registers'
            script += f'wait-pc {addr} 1\ncapture {name}{i}{kind}\n'
    (out / 'run.debug').write_text(script + 'exit\n')
    (out / 'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\n')
    with (out / 'vaeg.log').open('w') as log:
        subprocess.run([str(args.vaeg.resolve()), '--cfg', str(out / 'va.cfg'),
                        '--no-bkupmem', '--nowait', '--mute', '--roms', str(args.bios.resolve()),
                        '--fdd1', str(disk), '--debug-script', str(out / 'run.debug'),
                        '--debug-output-dir', str(out)],
                       env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'),
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=240)
    background = disk.with_suffix('.expected').read_bytes()
    rows = ['size,count,cpu_clocks,sgp_build_clocks,sgp_wait_clocks,sgp_total_clocks,speedup']
    for i in range(8):
        size, count = (16 if i < 4 else 32), (1, 8, 32, 64)[i % 4]
        expected = expected_image(background, size, count)
        for method in ('cpu', 'sgp'):
            capture = (out / f'{method}_end{i}.gvram.bin').read_bytes()
            if (len(capture) != 262144 or capture[:71680] != expected
                    or capture[71680:143360] != background):
                sys.exit(f'{method}: {size}x{size}, {count} sprites differ; see {out}')
        def clock(name):
            return int(registers(out / f'{name}{i}.registers.tsv')['clock'])
        if int(registers(out / f'sgp_end{i}.registers.tsv')['ax'], 16) & 1:
            sys.exit(f'SGP busy wait timed out: {out}')
        cpu = clock('cpu_end') - clock('cpu_begin')
        build = clock('sgp_submit') - clock('sgp_begin')
        wait = clock('sgp_end') - clock('sgp_submit')
        total = build + wait
        rows.append(f'{size},{count},{cpu},{build},{wait},{total},{cpu / total:.3f}')
    report = '\n'.join(rows) + '\n'
    (out / 'results.csv').write_text(report)
    print(report + str(out))


if __name__ == '__main__':
    main()
