# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Attribute one native render's guest clocks to routines by instruction trace.

Requires a trace-enabled vaeg build. Each traced instruction's consumed clocks
are assigned to the nearest preceding global label of its CS:IP. SGP busy-wait
polling therefore appears under its wait routine. Uses snapshot replays only.
"""

import argparse
from collections import Counter
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d88
import roms
from check_pages import address

LINE = re.compile(r'^\s*\d+\s+([0-9A-F]{8})\s')
LABEL = re.compile(r'^\s*\d+\s+(?:[0-9A-F]{8}\s+\S+\s+)?(?:<\d+>\s+)?([A-Za-z_][A-Za-z0-9_]*):')


def labels(listing):
    pending, table = [], []
    for line in listing.splitlines():
        found = LABEL.match(line)
        if found:
            pending.append(found[1])
        at = LINE.match(line)
        if at and pending:
            for name in pending:
                table.append((int(at[1], 16), name))
            pending = []
    table.sort()
    return table


def owner(table, ip):
    low, high = 0, len(table)
    while low < high:
        mid = (low+high)//2
        if table[mid][0] <= ip:
            low = mid+1
        else:
            high = mid
    return table[low-1][1] if low else '?'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vaeg', type=Path, required=True, help='trace-enabled build')
    parser.add_argument('--bios', type=Path, required=True)
    parser.add_argument('--roms', type=Path, default=roms.DEFAULT)
    parser.add_argument('--fixtures', type=Path, default=d88.REPO/'build/video-cases')
    parser.add_argument('--states', default='base,tile,latch,sprite,edges,moved,base,tile,latch,sprite,edges,moved')
    parser.add_argument('--profile', type=int, default=12, help='1-based following state to profile')
    parser.add_argument('--steps', type=int, default=400000)
    parser.add_argument('--renders', type=int, default=1, help='renders profiled together, from --profile on')
    parser.add_argument('--base', default='base', help='fixture of the first (full) render')
    parser.add_argument('flags', nargs='*', help='extra build_screen flags, e.g. --front-hybrid')
    args = parser.parse_args()
    states = args.states.split(',')
    if not 1 <= args.profile <= len(states):
        parser.error('--profile out of range')
    root = d88.REPO/'build/trace-profile'
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    disk = out/'profile.d88'
    command = [sys.executable, '-I', str(d88.REPO/'tools/build_screen.py'), '--native-planes', *args.flags,
               '--snapshot', str((args.fixtures/f'{args.base}.memory').resolve()), '--roms', str(args.roms.resolve()),
               '--output', str(disk)]
    for name in states:
        command += ['--next-snapshot', str((args.fixtures/f'{name}.memory').resolve())]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    listing = disk.with_suffix('.lst').read_text()
    begin = address(listing, 'native_next_begin')
    end = int(address(listing, 'native_next_end').split(':')[1], 16)
    script = f'debug-script 1\nlimit-frame 4000\nwait-pc {begin} {args.profile}\ntrace render {args.steps}\nexit\n'
    (out/'run.debug').write_text(script)
    (out/'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\n')
    subprocess.run([str(args.vaeg.resolve()), '--cfg', str(out/'va.cfg'), '--no-bkupmem', '--nowait', '--mute',
                    '--roms', str(args.bios.resolve()), '--fdd1', str(disk), '--debug-script', str(out/'run.debug'),
                    '--debug-output-dir', str(out)], env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'),
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=True, timeout=300)
    table = labels(listing)
    clocks, counts = Counter(), Counter()
    ip = None
    finished = False
    ended = 0
    for line in (out/'render.trace.log').read_text().splitlines():
        if line.startswith('begin '):
            fields = dict(item.split('=', 1) for item in line.split()[1:] if '=' in item)
            ip = int(fields['ip'], 16) if fields.get('cs') == '2000' else None
            if ip == end:
                ended += 1
                if ended == args.renders:
                    finished = True
                    break
        elif line.startswith('end ') and ip is not None:
            fields = dict(item.split('=', 1) for item in line.split()[1:] if '=' in item)
            name = owner(table, ip)
            clocks[name] += int(fields['consumed'], 16)
            counts[name] += 1
    if not finished:
        sys.exit(f'render did not finish within {args.steps} steps: {out}')
    total = sum(clocks.values())
    report = ['routine,clocks,percent,instructions']
    for name, value in clocks.most_common():
        report.append(f'{name},{value},{100*value/total:.1f},{counts[name]}')
    report.append(f'total,{total},100.0,{sum(counts.values())}')
    if args.renders > 1:
        report.append(f'per render,{total // args.renders},,')
    text = '\n'.join(report)+'\n'
    (out/'profile.csv').write_text(text)
    print(text+str(out))


if __name__ == '__main__':
    main()
