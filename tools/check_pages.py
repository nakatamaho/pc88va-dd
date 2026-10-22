# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Build and check the synthetic three-page probe in vaeg (no ROM assets).

The emulator still requires the user's machine BIOS. Results establish
emulator behaviour only, not hardware compatibility or hardware timing.
"""

import argparse
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d88


def address(listing: str, label: str) -> str:
    after = listing.split(label + ':', 1)[1]
    match = re.search(r'^\s*\d+\s+([0-9A-F]{8})\s', after, re.MULTILINE)
    if not match:
        raise ValueError(f'no instruction after {label}')
    return f'2000:{int(match[1], 16):04X}'


def registers(path: Path) -> dict:
    return dict(line.split('\t', 1) for line in path.read_text().splitlines())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vaeg', required=True, type=Path)
    parser.add_argument('--bios', required=True, type=Path)
    args = parser.parse_args()
    root = d88.REPO / 'build/pages-check'
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    disk = out / 'pages.d88'
    subprocess.run([sys.executable, '-I', str(d88.REPO / 'tools/build_screen.py'),
                    '--pages', '--output', str(disk)], check=True)
    d88.nasm(['-DPAGE_TEST=1', '-l', str(out / 'probe.lst'), '-o', str(out / 'probe.bin'),
              str(d88.REPO / 'src/m02/screen.asm')])
    listing = (out / 'probe.lst').read_text()
    start = address(listing, 'copy_begin')
    end = address(listing, 'copy_end')
    shown = address(listing, 'page_shown')
    (out / 'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\n')
    # Each wait is newly armed: ordinal 1 means the next occurrence, not
    # the first occurrence since boot. Using 2/3 here skips page switches.
    (out / 'run.debug').write_text(
        f'debug-script 1\nlimit-frame 1000\n'
        f'wait-pc {start} 1\ncapture begin registers\n'
        f'wait-pc {end} 1\ncapture end registers\n'
        f'wait-pc {shown} 1\ncapture pages registers gvram\n'
        f'wait-pc {shown} 1\ncapture second registers\n'
        f'wait-pc {shown} 1\ncapture third registers\n')
    with (out / 'vaeg.log').open('w') as log:
        subprocess.run([str(args.vaeg.resolve()), '--cfg', str(out / 'va.cfg'),
                        '--no-bkupmem', '--nowait', '--mute', '--roms', str(args.bios.resolve()),
                        '--fdd1', str(disk), '--debug-script', str(out / 'run.debug'),
                        '--debug-output-dir', str(out)],
                       env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'),
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    expected = disk.with_suffix('.expected').read_bytes()
    actual = (out / 'pages.gvram.bin').read_bytes()
    for page in range(3):
        wanted = bytearray(expected)
        if page:
            wanted[321:323] = bytes([page]) * 2
        if actual[page*71680:(page+1)*71680] != wanted:
            sys.exit(f'page {page} differs; see {out}')
    for name, page in (('pages', 0), ('second', 1), ('third', 2)):
        state = registers(out / f'{name}.registers.tsv')
        if int(state['bx'], 16) != page * 4 or int(state['ax'], 16) != page:
            sys.exit(f'nonconsecutive page-switch captures: {out}')
    def clock(name):
        return int(registers(out / f'{name}.registers.tsv')['clock'])
    elapsed = clock('end') - clock('begin')
    frame_clocks = (clock('third') - clock('second')) / 60
    if elapsed <= 0 or frame_clocks <= 0:
        sys.exit('invalid timing captures')
    report = (f'All three 71680-byte areas match.\n'
              f'Full-page CPU copy: {elapsed} guest clocks, '
              f'{elapsed / frame_clocks:.3f} display frames.\n'
              'Includes call/return and interrupt overhead; not hardware timing.\n')
    (out / 'result.txt').write_text(report)
    print(report + str(out))


if __name__ == '__main__':
    main()
