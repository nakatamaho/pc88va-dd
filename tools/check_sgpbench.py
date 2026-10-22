# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Run the SGP benchmark disk in vaeg and check it.

Requires every correctness case to match (vaeg implements the semantics the
game relies on) and front A to equal the model; prints the timing table as
the machine shows it, for comparison with a photograph of a VA or VA2.
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
import sgpbench  # noqa: E402
from build_sgpbench import main as build  # noqa: E402

BENCH_SEG = 0x3000
RESULTS = 0x12400


def label(listing: str, name: str) -> int:
    after = listing.split(name + ':', 1)[1]
    match = re.search(r'^\s*\d+\s+([0-9A-F]{8})\s', listing.split(name + ':', 1)[0].splitlines()[-1] + after,
                      re.MULTILINE)
    return int(match[1], 16) + 0x100


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--vaeg', type=Path, required=True)
    parser.add_argument('--bios', type=Path, required=True)
    parser.add_argument('--model', choices=('va', 'va2'), default=None, help='vaeg --model (default: its own)')
    args = parser.parse_args()
    root = d88.REPO / 'build/sgpbench-check'
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    disk = out / 'sgpbench.d88'
    sys.argv = [sys.argv[0], '--output', str(disk)]
    build()
    done = label(disk.with_suffix('.lst').read_text(), 'bench_done')
    (out / 'run.debug').write_text(f'debug-script 1\nlimit-frame 16000\nwait-pc {BENCH_SEG:04X}:{done:04X} 1\n'
                                   'capture r registers gvram screen\nexit\n')
    cfg = '[NekoProjectII]\nMonitor15kHz=true\nGUI_win_cx=640\nGUI_win_cy=470\n'
    (out / 'va.cfg').write_text(cfg)
    model = ['--model', args.model] if args.model else []
    with open(out / 'vaeg.log', 'w') as log:
        subprocess.run([str(args.vaeg), *model, '--cfg', str(out / 'va.cfg'), '--no-bkupmem', '--nowait', '--mute',
                        '--frameskip', 'full', '--scaling', 'native', '--roms', str(args.bios), '--fdd1', str(disk),
                        '--debug-script', str(out / 'run.debug'), '--debug-output-dir', str(out)],
                       env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'),
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=2400)
    gvram = (out / 'r.gvram.bin').read_bytes()
    if gvram[RESULTS:RESULTS + 4] != b'SGPB':
        sys.exit(f'no results at GVRAM {RESULTS:05X}h; {out}')
    n_tests, n_cases = gvram[RESULTS + 4], gvram[RESULTS + 5]
    timeouts, n_windows = gvram[RESULTS + 6], gvram[RESULTS + 7]
    windows = sgpbench.WINDOWS[:n_windows]
    rows = ['test,name,window_vrtcs,reps,us_per_rep']
    print(f'{"NN":2} {"TEST":20} ' + ' '.join(f'{f"us @{w}":>11}' for w in windows) + '  spread')
    for i in range(n_tests):
        name = sgpbench.TESTS[i]
        values = []
        for k, w in enumerate(windows):
            reps, us10 = struct.unpack_from('<II', gvram, RESULTS + 8 + (i * n_windows + k) * 8)
            values.append(us10 / 10)
            rows.append(f'{i + 1},{name},{w},{reps},{us10 / 10:.1f}')
        spread = (max(values) - min(values)) / values[-1] * 100 if values[-1] else 0
        print(f'{i + 1:02} {name:20} ' + ' '.join(f'{v:11.1f}' for v in values) + f'  {spread:5.2f}%')
    (out / 'results.csv').write_text('\n'.join(rows) + '\n')
    counts = struct.unpack_from(f'<{n_cases}H', gvram, RESULTS + 8 + n_tests * n_windows * 8)
    failed = [(i, c) for i, c in enumerate(counts) if c]
    expected = sgpbench.expected()
    front = gvram[:len(expected)]
    differ = sum(a != b for a, b in zip(front, expected))
    print(f'cases {n_cases}: {len(failed)} fail {failed[:8]}; front A bytes differing from the model: {differ}; '
          f'SGP timeouts: {timeouts}')
    print(out)
    if failed or differ or timeouts or gvram[0x9100:0x9100 + len(expected)] != expected:
        sys.exit(1)


if __name__ == '__main__':
    main()
