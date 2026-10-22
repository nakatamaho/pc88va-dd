# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Game and render rate of scripted play over a stretch of guest frames.

Builds an automatic-input game disk (MS-DOS, DD; extra build_m03.py options
after --) and runs it twice in vaeg with fixed PC counters, to frame FIRST
and to frame LAST; the difference is the stretch. Counted:

    VRTCs           the vertical interrupt handler
    game frames     new_frame (one scheduler frame of the programs)
    renders         native_render calls; sprite renders: rect_sprites
    pages           new pictures queued for display (..@live_present_new)
    idle            idle_spin iterations, in clocks from a calibration of
                    one iteration (the loop is fixed: 25 clocks in vaeg)

Emulator timing only. Faster than frame_budget.py (no instruction trace).
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d88
import roms
from check_pages import address

FRAME = 133460
IDLE_LOOP = 25                      # clocks of one idle_spin iteration (frame_budget.py)
COUNTERS = (('vrtc', 'vrtc'), ('frames', 'new_frame'), ('renders', 'native_render'),
            ('sprites', 'rect_sprites'), ('pages', '..@live_present_new'), ('idle', 'idle_spin'))


def run(args, disk, listing, out, last):
    out.mkdir()
    script = ['debug-script 1', f'limit-frame {last + 10}']
    script += [f'counter {name} {address(listing, label)}' for name, label in COUNTERS]
    script += [f'wait-frame {last}', 'exit']
    (out / 'run.debug').write_text('\n'.join(script) + '\n')
    (out / 'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\n')
    with (out / 'vaeg.log').open('w') as log:
        subprocess.run([str(args.vaeg.resolve()), '--cfg', str(out / 'va.cfg'), '--no-bkupmem', '--nowait',
                        '--mute', '--roms', str(args.bios.resolve()), '--fdd1', str(disk),
                        '--debug-script', str(out / 'run.debug'), '--debug-output-dir', str(out)],
                       env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'),
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=3600)
    values = {}
    for line in (out / 'events.tsv').read_text().splitlines():
        fields = line.split('\t')
        for name, _ in COUNTERS:
            if fields[0] == 'counter' and fields[2] == name:
                values[name] = int(fields[-1])
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--vaeg', type=Path, required=True)
    parser.add_argument('--bios', type=Path, required=True)
    parser.add_argument('--roms', type=Path, default=roms.DEFAULT)
    parser.add_argument('--first', type=int, default=2000, help='guest frame where the stretch starts')
    parser.add_argument('--last', type=int, default=5000, help='guest frame where it ends')
    parser.add_argument('--step', type=int, default=0, help='also report windows of STEP frames')
    parser.add_argument('--disk', type=Path, help='measure this disk (with its .lst) instead of building one')
    parser.add_argument('build', nargs='*', help='extra build_m03.py options (after --)')
    args = parser.parse_args()
    root = d88.REPO / 'build/play-rate'
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    disk = args.disk
    if disk is None:
        disk = out / 'rate.d88'
        subprocess.run([sys.executable, '-I', str(d88.REPO / 'tools/build_m03.py'), '--auto', '--roms',
                        str(args.roms.resolve()), '--output', str(disk), *args.build], check=True,
                       stdout=subprocess.DEVNULL)
    listing = disk.with_suffix('.lst').read_text()
    ends = [args.first, args.last]
    if args.step:
        ends = list(range(args.first, args.last, args.step)) + [args.last]
    with ThreadPoolExecutor(max_workers=min(len(ends), os.cpu_count() or 4)) as pool:
        values = list(pool.map(lambda end: run(args, disk, listing, out / f'f{end}', end), ends))

    def rates(a, b):
        d = {name: b[name] - a[name] for name, _ in COUNTERS}
        vrtcs = d['vrtc']
        return (vrtcs, d['frames'] / vrtcs, d['renders'] / vrtcs, d['sprites'] / vrtcs, d['pages'] / vrtcs,
                d['idle'] * IDLE_LOOP / (vrtcs * FRAME))
    report = 'frames,VRTCs,game_frames_per_VRTC,renders_per_VRTC,sprite_renders_per_VRTC,pages_per_VRTC,idle\n'
    rows = [(f'{ends[i]}-{ends[i + 1]}', rates(values[i], values[i + 1])) for i in range(len(ends) - 1)]
    if len(rows) > 1:
        rows.append((f'{ends[0]}-{ends[-1]}', rates(values[0], values[-1])))
    for name, r in rows:
        report += f'{name},{r[0]},{r[1]:.4f},{r[2]:.4f},{r[3]:.4f},{r[4]:.4f},{r[5]:.1%}\n'
    if len(rows) > 2:
        report += 'least idle window: %s\n' % min(rows[:-1], key=lambda row: row[1][5])[0]
    (out / 'rate.txt').write_text(report)
    print(report + str(out))


if __name__ == '__main__':
    main()
