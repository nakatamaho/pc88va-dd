# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Compare host composition with reference-emulator RGB captures.

The reference palette is used directly: this checks geometry, lookup and
composition, not resistor modelling or the VA's analogue palette.
All captures and rendered pixels stay under ignored build/.
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roms
from render import Renderer, WIDTH, HEIGHT

REPO = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roms', type=Path, default=roms.DEFAULT)
    parser.add_argument('--mame', required=True, type=Path)
    parser.add_argument('--system', required=True)
    parser.add_argument('--rompath', required=True, type=Path)
    parser.add_argument('--frames', type=int, default=1800)
    parser.add_argument('--period', type=int, default=60)
    parser.add_argument('--first-frame', type=int, help='first sample (default: period)')
    args = parser.parse_args()
    if not 0 < args.period <= args.frames:
        parser.error('require 0 < period <= frames')
    first = args.first_frame if args.first_frame is not None else args.period
    if not 1 <= first <= args.frames:
        parser.error('require 1 <= first-frame <= frames')
    renderer = Renderer(roms.load(args.roms))
    root = REPO / 'build' / 'screen-check'
    root.mkdir(parents=True, exist_ok=True)
    # Separate directories prevent old successful captures masking a failed run.
    out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    env = dict(os.environ, DD_OUT=str(out), DD_FRAMES=str(args.frames),
               DD_PERIOD=str(args.period), DD_FIRST=str(first))
    with tempfile.TemporaryDirectory(prefix='dd-screen-') as tmp:
        command = [str(args.mame.resolve()), args.system, '-rompath', str(args.rompath.resolve()),
                   '-nvram_directory', tmp, '-cfg_directory', tmp,
                   '-video', 'none', '-sound', 'none', '-nothrottle', '-skip_gameinfo',
                   '-autoboot_delay', '0', '-autoboot_script', str(REPO / 'tools/mame/screen_check.lua')]
        with (out / 'mame.log').open('w') as log:
            subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=300)
    if '[LUA ERROR]' in (out / 'mame.log').read_text():
        sys.exit(f'capture failed; see {out}/mame.log')
    failures = []
    samples = range(first, args.frames + 1, args.period)
    for frame in samples:
        stem = out / f'{frame:06d}'
        indices = renderer.render(stem.with_suffix('.memory').read_bytes())
        palette = stem.with_suffix('.palette').read_bytes()
        reference = stem.with_suffix('.rgb').read_bytes()
        if len(palette) != 96 or len(reference) != WIDTH * HEIGHT * 3:
            sys.exit(f'invalid capture size: {stem}')
        rendered = b''.join(palette[i * 3:i * 3 + 3] for i in indices)
        count = sum(rendered[i:i+3] != reference[i:i+3] for i in range(0, len(reference), 3))
        if count:
            failures.append((frame, count))
            for suffix, pixels in (('.host.ppm', rendered), ('.reference.ppm', reference)):
                Path(str(stem) + suffix).write_bytes(b'P6\n288 224\n255\n' + pixels)
    print(f'{len(samples)} frames checked; {len(failures)} differ; captures: {out}')
    for frame, count in failures:
        print(f'  frame {frame}: {count} pixels differ')
    if failures:
        sys.exit(1)


if __name__ == '__main__':
    main()
