# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Compare front-clearing policies on identical snapshot inputs.

Every variant must pass check_native's full pixel/RGB/guard verification.
Mixed fixture: cold and warm (second pass) movement. Sequence: 60
consecutive primary transitions. Emulator clocks only; no hardware claim.
"""

import argparse
from pathlib import Path
import re
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
VARIANTS = {
    'cell-cpu': ['--coalesce'],
    'run-cpu': ['--coalesce', '--cpu-run-clear'],
    'full-sgp': ['--front-full'],
    'full-cpu': ['--front-full', '--front-cpu-clear'],
    'hybrid-8': ['--front-hybrid', '--coalesce', '--front-threshold', '8'],
    'hybrid-16': ['--front-hybrid', '--coalesce', '--front-threshold', '16'],
    'hybrid-24': ['--front-hybrid', '--coalesce', '--front-threshold', '24'],
}


def run(args, extra, first, following):
    command = [sys.executable, '-I', str(REPO/'tools/check_native.py'), '--planes', *extra,
               '--vaeg', str(args.vaeg), '--bios', str(args.bios), str(first)]
    for path in following:
        command += ['--next-snapshot', str(path)]
    text = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    return [int(v) for v in re.findall(r'Incremental \d+ .*?; (\d+) guest clocks', text)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vaeg', type=Path, required=True)
    parser.add_argument('--bios', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, default=REPO/'build/video-cases')
    parser.add_argument('--sequence', type=Path, default=REPO/'build/screen-check/run-_seebfle')
    parser.add_argument('--only', nargs='*', help='variant names')
    args = parser.parse_args()
    fixtures = [args.fixtures/f'{n}.memory' for n in ('base','tile','latch','sprite','edges','moved')]
    sequence = [args.sequence/f'{f:06}.memory' for f in range(1201, 1261)]
    rows = ['variant,mixed_cold,mixed_warm,overlap_after_warm,seq60_sum,seq60_max']
    for name, extra in VARIANTS.items():
        if args.only and name not in args.only:
            continue
        mixed = run(args, extra, args.fixtures/'base.memory',
                    fixtures + fixtures + [args.fixtures/'overlap.memory'])
        seq = run(args, extra, args.sequence/'001200.memory', sequence)
        rows.append(f'{name},{mixed[5]},{mixed[11]},{mixed[12]},{sum(seq)},{max(seq)}')
        print(rows[-1], flush=True)
    out = REPO/'build/compare-clear.csv'
    out.write_text('\n'.join(rows)+'\n')
    print(out)


if __name__ == '__main__':
    main()
