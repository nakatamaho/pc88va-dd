# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Check SGP traversal/reflection against asymmetric independent images.

Includes valid opaque HD/VD modes, transparent negative-source-pitch Y
reflection, and transparent column-reordered X/XY reflection. No ROMs.
This tests the current emulator, not hardware command conformance.
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

NAMES = ('opaque_forward', 'opaque_hd', 'opaque_vd', 'opaque_hd_vd',
         'transparent_forward', 'reflect_y_pitch', 'reflect_x_columns', 'reflect_xy_columns')


def expected_image(background: bytes, case: int) -> bytes:
    if len(background) != 71680 or not 0 <= case < 8:
        raise ValueError('invalid direction case')
    out = bytearray(background)
    for y in range(16):
        for x in range(16):
            sx = 15 - x if case in (6, 7) else x
            sy = 15 - y if case in (5, 7) else y
            pen = 0 if sx % 4 == 0 and sy % 2 == 0 else (sx + 3 * sy) % 31 + 1
            if pen or case < 4:
                out[(16 + y) * 320 + 17 + x] = pen
    return bytes(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vaeg', required=True, type=Path)
    parser.add_argument('--bios', required=True, type=Path)
    args = parser.parse_args()
    root = d88.REPO / 'build/sgp-direction'
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    disk = out / 'direction.d88'
    subprocess.run([sys.executable, '-I', str(d88.REPO / 'tools/build_screen.py'),
                    '--sgp-direction', '--output', str(disk)], check=True)
    listing = disk.with_suffix('.lst').read_text()
    labels = {name: address(listing, 'dir_' + name) for name in ('begin', 'submit', 'end')}
    script = 'debug-script 1\nlimit-frame 1500\n'
    for i in range(8):
        for name, addr in labels.items():
            kind = 'registers gvram' if name == 'end' else 'registers'
            script += f'wait-pc {addr} 1\ncapture {name}{i} {kind}\n'
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
    rows = ['case,bitblts,build_clocks,submit_wait_clocks,total_clocks']
    for i, name in enumerate(NAMES):
        capture = (out / f'end{i}.gvram.bin').read_bytes()
        expected = expected_image(background, i)
        if (len(capture) != 262144 or capture[:71680] != expected
                or capture[71680:143360] != background):
            sys.exit(f'{name}: pixels differ; see {out}')
        states = {key: registers(out / f'{key}{i}.registers.tsv') for key in labels}
        if int(states['begin']['ax'], 16) != i or int(states['end']['ax'], 16) & 1:
            sys.exit(f'{name}: wrong event or SGP timeout: {out}')
        a, b, c = (int(states[key]['clock']) for key in ('begin', 'submit', 'end'))
        rows.append(f'{name},{16 if i >= 6 else 1},{b-a},{c-b},{c-a}')
    report = '\n'.join(rows) + '\n'
    (out / 'results.csv').write_text(report)
    print(report + str(out))


if __name__ == '__main__':
    main()
