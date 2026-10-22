# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Run the sprite benchmark disk in vaeg and check it.

Requires the SGP and the CPU to draw the same pixels for every size and
depth, and no SGP timeout; prints the table the machine shows (us a
sprite), the pixel rates and, for the shared runs, how close they come to
the ideal of the CPU and the SGP fully in parallel.
"""

import argparse
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d88  # noqa: E402
import sprbench  # noqa: E402
from build_sprbench import main as build  # noqa: E402

BENCH_SEG = 0x3000
RESULTS = 0x12400


def label(listing: str, name: str) -> int:
    for line in listing.splitlines():
        match = re.match(r'\s*\d+\s+([0-9A-F]{8})\s+\S*\s*' + name + r':', line)
        if match:
            return int(match[1], 16) + 0x100
    raise ValueError(f'no {name} in the listing')


def parse(gvram: bytes):
    if gvram[RESULTS:RESULTS + 4] != b'SPRB':
        raise ValueError(f'no results at GVRAM {RESULTS:05X}h')
    n_cfg, n_split = gvram[RESULTS + 4], gvram[RESULTS + 5]
    timeouts, = struct.unpack_from('<H', gvram, RESULTS + 6)
    base = RESULTS + 8
    cells = [struct.unpack_from('<IIIIH', gvram, base + i * sprbench.CELL) for i in range(n_cfg * n_split)]
    base += n_cfg * n_split * sprbench.CELL
    per_sprite = struct.unpack_from(f'<{n_cfg * n_split}I', gvram, base)
    base += n_cfg * n_split * 4
    checks = struct.unpack_from(f'<{n_cfg}H', gvram, base)
    max_diff, spin16, spin256 = struct.unpack_from('<3H', gvram, base + 2 * n_cfg)
    return n_cfg, n_split, timeouts, cells, per_sprite, checks, max_diff, (spin16, spin256)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--vaeg', type=Path, required=True)
    parser.add_argument('--bios', type=Path, required=True)
    parser.add_argument('--model', choices=('va', 'va2'), default=None, help='vaeg --model (default: its own)')
    args = parser.parse_args()
    root = d88.REPO / 'build/sprbench-check'
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    disk = out / 'sprbench.d88'
    sys.argv = [sys.argv[0], '--output', str(disk)]
    build()
    done = label(disk.with_suffix('.lst').read_text(), 'bench_done')
    (out / 'run.debug').write_text(f'debug-script 1\nlimit-frame 40000\nwait-pc {BENCH_SEG:04X}:{done:04X} 1\n'
                                   'capture r registers gvram screen\nexit\n')
    (out / 'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\nGUI_win_cx=640\nGUI_win_cy=470\n')
    model = ['--model', args.model] if args.model else []
    with open(out / 'vaeg.log', 'w') as log:
        subprocess.run([str(args.vaeg), *model, '--cfg', str(out / 'va.cfg'), '--no-bkupmem', '--nowait', '--mute',
                        '--frameskip', 'full', '--scaling', 'native', '--roms', str(args.bios), '--fdd1', str(disk),
                        '--debug-script', str(out / 'run.debug'), '--debug-output-dir', str(out)],
                       env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'),
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=7200)
    n_cfg, n_split, timeouts, cells, per_sprite, checks, max_diff, spin = parse((out / 'r.gvram.bin').read_bytes())
    rows = ['colours,size,split,sprites,reps_a,us_per_rep_a,reps_b,us_per_rep_b,us_per_sprite,diff_percent,mpixels_per_s']
    worst = 0.0
    print(f'{"COL":>4} {"SIZE":>4} ' + ' '.join(f'{s:>9}' for s in sprbench.SPLITS)
          + '   best/ideal  Mpx/s CPU  SGP')
    for c, (depth, size, count) in enumerate(sprbench.configs()):
        us = [per_sprite[c * n_split + k] / 10 for k in range(n_split)]
        for k, name in enumerate(sprbench.SPLITS):
            reps_a, us10_a, reps_b, us10_b, sprites = cells[c * n_split + k]
            diff = abs(us10_a - us10_b) / ((us10_a + us10_b) / 2) * 100
            worst = max(worst, diff)
            rows.append(f'{depth},{size},{name},{sprites},{reps_a},{us10_a / 10:.1f},{reps_b},{us10_b / 10:.1f},'
                        f'{us[k]:.1f},{diff:.3f},{size * size / us[k]:.3f}')
        cpu, sgp = us[0], us[-1]
        ideal = cpu * sgp / (cpu + sgp)         # both fully in parallel, best share
        best = min(us)
        print(f'{depth:>3}C {size:>4} ' + ' '.join(f'{u:9.1f}' for u in us)
              + f'   {best / ideal:9.2f}  {size * size / cpu:9.3f} {size * size / sgp:5.3f}')
    (out / 'results.csv').write_text('\n'.join(rows) + '\n')
    sizes = ' '.join(f'{depth}C {size}:{"OK" if checks[c] == 0 else checks[c]}'
                     for c, (depth, size, _) in enumerate(sprbench.configs()))
    print(f'SGP = CPU: {sizes}; SGP timeouts: {timeouts}')
    print(f'2 runs of {sprbench.WINDOW} VRTCs: largest difference {worst:.3f} % (the machine shows '
          f'{max_diff / 100:.2f} %); spins a VRTC: {spin[0]} (16 colours), {spin[1]} (256)')
    print(out)
    if any(checks) or timeouts:
        sys.exit(1)


if __name__ == '__main__':
    main()
