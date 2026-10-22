# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Compare the V30 snapshot compositor's GVRAM with host composition.

Snapshots come from check_screen.py. This is not a live game or a timing
acceptance test. All generated assets and captures are private build output.
"""

import argparse
from pathlib import Path
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d88
import roms
from check_pages import address, registers
from build_screen import source_palette
from PIL import Image, ImageChops
from render import Renderer


# Packed layout (native_planes.inc): front A 0, front B FRONT_B, G1 20000h.
# Eight blank lines (1280 bytes, plus the 8 bytes of a sideways move) after
# each front and G1 and at the top of each 128 KiB region, where a negative
# DSA wraps: the alignment screen moves the picture by DSA.
FRONT_B = 0x9100
FRONT_C = 0x12400       # live rectangle-list builds only (TRIPLE_FRONTS)
PAGE_BYTES = 35840
EXPORT = 0x12400        # live diagnostic export with the background cache
EXPORT_TRIPLE = 0x1B800 # the same with the third front
BG_CACHE = 0x29200      # background tile cache, 64 KiB
BLANK = ((0x8c00, 0x9100), (0x11d00, 0x12400), (0x1fb00, 0x20000), (0x28c00, 0x29200), (0x3fb00, 0x40000))
UNUSED = ((0x12400, 0x1fb00), (0x29200, 0x3fb00))
BLANK_TRIPLE = BLANK + ((0x1b000, 0x1b800),)
UNUSED_TRIPLE = ((0x1b800, 0x1fb00), (0x29200, 0x3fb00))


def triple(raw):
    """A build with the third front: its area is cleared, not canaries."""
    return raw[0x12400:0x1b800] != bytes([0x5a]) * (0x1b800 - 0x12400)


def framebuffer(raw, planes=False, page=0):
    """The composed picture; PAGE is the renderer's page in paragraphs."""
    if not planes:
        return raw[:71680]
    three = triple(raw)
    if any(raw[a:b] != bytes([0x5a])*(b-a) for a,b in (UNUSED_TRIPLE if three else UNUSED)):
        raise ValueError('unused packed GVRAM bytes were overwritten')
    if any(any(raw[a:b]) for a,b in (BLANK_TRIPLE if three else BLANK)):
        raise ValueError('a blank margin around the packed pictures was written')
    def unpack(data):
        return bytes(v for b in data for v in (b >> 4, b & 15))
    page *= 16
    if page not in ((0, FRONT_B, FRONT_C) if three else (0, FRONT_B)):
        raise ValueError('invalid packed front-page offset')
    front = unpack(raw[page:page+PAGE_BYTES])
    background = unpack(raw[0x20000:0x28c00])
    return bytes(f+15 if f else b for f,b in zip(front,background))


def check_rgb(path, expected, palette):
    colours = []
    for word in palette:
        rgb = []
        for value, bits in (((word >> 6)&15,5), ((word >> 12)&15,6), ((word >> 1)&15,5)):
            expanded = (value << (bits-4)) | ((1 << (bits-4))-1 if value else 0)
            rgb.append(expanded*255//((1 << bits)-1))
        colours.append(bytes(rgb))
    wanted = Image.frombytes('RGB',(320,224),b''.join(colours[i] for i in expected))
    wanted = wanted.resize((640,448),Image.Resampling.NEAREST)
    screen = Image.open(path).convert('RGB')
    if screen.size != (640,470):
        raise ValueError(f'unexpected rendered-window size: {screen.size}')
    differences = ImageChops.difference(screen.crop((0,22,640,470)),wanted)
    if max(hi for lo,hi in differences.getextrema()) > 3:
        raise ValueError(f'final RGB mixer differs: {path}')


def check_planes_state(raw, snapshot, renderer, previous=None, page=0):
    memory = bytearray(snapshot.read_bytes())
    memory[0x8b80:0x8c00] = bytes(128)
    memory[0x9380:0x9400] = bytes(128)
    pixels = renderer.render(bytes(memory))
    background = b''.join(bytes(16)+pixels[y*288:(y+1)*288]+bytes(16) for y in range(224))
    unpacked = bytes(v for b in raw[0x20000:0x28c00] for v in (b >> 4,b & 15))
    if unpacked != background:
        raise ValueError('independent background plane differs')
    if previous is not None:
        old_raw, old_page = previous
        old_page *= 16
        if raw[old_page:old_page+PAGE_BYTES] != old_raw[old_page:old_page+PAGE_BYTES]:
            raise ValueError('renderer modified the displayed front page')
    return raw, page


def cache_report(state, planes=False):
    return ('Cache: ' + ', '.join(f'{label}={int(state[reg], 16)}' for label, reg in
            (('hits', 'bx'), ('misses', 'cx'), ('fallbacks', 'dx'), ('resident', 'si'), ('cleared_cells' if planes else 'probes', 'bp'))) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshots', type=Path, nargs='+')
    parser.add_argument('--next-snapshot', type=Path, action='append', default=[],
                        help='also check an incremental render; may be repeated')
    parser.add_argument('--roms', type=Path, default=roms.DEFAULT)
    parser.add_argument('--coalesce', action='store_true')
    parser.add_argument('--front-full', action='store_true')
    parser.add_argument('--front-cpu-clear', action='store_true')
    parser.add_argument('--front-hybrid', action='store_true')
    parser.add_argument('--front-threshold', type=int, default=16)
    parser.add_argument('--cpu-run-clear', action='store_true')
    parser.add_argument('--rect-sprites', action='store_true')
    parser.add_argument('--planes', action='store_true', help='packed two-screen backend')
    parser.add_argument('--sgp', action='store_true', help='retained SGP sprite backend')
    parser.add_argument('--cache-slots', type=int)
    parser.add_argument('--vaeg', required=True, type=Path)
    parser.add_argument('--bios', required=True, type=Path)
    args = parser.parse_args()
    if args.planes and args.sgp:
        parser.error('choose one native backend')
    if args.cache_slots is None:
        args.cache_slots = 512 if args.planes else 440
    if args.roms is None:
        parser.error('set DD_ROMS or give --roms')
    root = d88.REPO / 'build/native-check'
    root.mkdir(parents=True, exist_ok=True)
    source = roms.load(args.roms) if args.planes else None
    palette = source_palette(source['palette']) if args.planes else None
    renderer = Renderer(source) if args.planes else None
    for snapshot in args.snapshots:
        out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
        disk = out / 'native.d88'
        extra = [arg for path in args.next_snapshot for arg in ('--next-snapshot', str(path.resolve()))]
        extra += ['--memory-guards']
        if args.planes:
            extra += ['--native-planes', '--cache-slots', str(args.cache_slots)]
        if args.coalesce:
            extra += ['--coalesce']
        if args.front_hybrid:
            extra += ['--front-threshold', str(args.front_threshold)]
        for flag in ('front_full','front_cpu_clear','cpu_run_clear','front_hybrid','rect_sprites'):
            if getattr(args, flag):
                extra += ['--'+flag.replace('_','-')]
        if args.sgp:
            extra += ['--native-sgp', '--cache-slots', str(args.cache_slots)]
        subprocess.run([sys.executable, '-I', str(d88.REPO / 'tools/build_screen.py'),
                        '--native', '--snapshot', str(snapshot.resolve()), '--roms', str(args.roms.resolve()),
                        '--output', str(disk), *extra], check=True)
        listing = disk.with_suffix('.lst').read_text()
        start, end = (address(listing, label) for label in ('native_begin', 'native_end'))
        (out / 'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\nMonitor15kHzFill=true\nGUI_win_cx=640\nGUI_win_cy=470\n')
        script = (f'debug-script 1\nlimit-frame 3000\n'
                  f'wait-pc {start} 1\ncapture begin registers\n'
                  f'wait-pc {end} 1\ncapture drawn registers gvram\n')
        if args.planes:
            shown = address(listing, 'planes_shown')
            script += f'wait-pc {shown} 1\ncapture shown0 registers screen\n'
        guarded = address(listing, 'video_guard_passed')
        script += f'wait-pc {guarded} 1\ncapture guard0 registers\n'
        if args.next_snapshot:
            next_start, next_end = (address(listing, label) for label in ('native_next_begin', 'native_next_end'))
            for i in range(1, len(args.next_snapshot) + 1):
                script += (f'wait-pc {next_start} 1\ncapture nextbegin{i} registers\n'
                           f'wait-pc {next_end} 1\ncapture nextdrawn{i} registers gvram\n')
                if args.planes:
                    script += f'wait-pc {shown} 1\ncapture shown{i} registers screen\n'
                script += f'wait-pc {guarded} 1\ncapture guard{i} registers\n'
        (out / 'run.debug').write_text(script + 'exit\n')
        with (out / 'vaeg.log').open('w') as log:
            subprocess.run([str(args.vaeg.resolve()), '--cfg', str(out / 'va.cfg'),
                            '--no-bkupmem', '--nowait', '--frameskip', 'full', '--effect', 'unfiltered', '--scaling', 'native', '--mute', '--roms', str(args.bios.resolve()),
                            '--fdd1', str(disk), '--debug-script', str(out / 'run.debug'),
                            '--debug-output-dir', str(out)],
                           env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'),
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
        for i in range(len(args.next_snapshot) + 1):
            if not (out / f'guard{i}.registers.tsv').exists():
                sys.exit(f'Z80-bank/GVRAM-page guard was not reached: {out}')
        expected = disk.with_suffix('.expected').read_bytes()
        actual = (out / 'drawn.gvram.bin').read_bytes()
        if len(expected) != 71680 or len(actual) != 262144:
            sys.exit(f'invalid output sizes: {out}')
        state = registers(out / 'drawn.registers.tsv')
        differences = sum(a != b for a, b in zip(expected, framebuffer(actual, args.planes, int(state['di'],16) if args.planes else 0)))
        clocks = int(state['clock']) - int(registers(out / 'begin.registers.tsv')['clock'])
        previous = None
        if args.planes:
            previous = check_planes_state(actual, snapshot, renderer, page=int(state['di'],16))
            check_rgb(out / 'shown0.screen.bmp', expected, palette)
            if registers(out / 'shown0.registers.tsv')['di'] != state['di']:
                sys.exit('displayed page differs from composed page')
        report = f'{snapshot}: {differences} pixels differ, {clocks} guest clocks for full redraw\n'
        if args.sgp or args.planes:
            report += cache_report(state, args.planes)
        (out / 'result.txt').write_text(report)
        print(report + str(out))
        if differences:
            sys.exit(1)
        reports = []
        for i, path in enumerate(args.next_snapshot, 1):
            suffix = '.next.expected' if i == 1 else f'.next{i}.expected'
            expected = disk.with_suffix(suffix).read_bytes()
            actual = (out / f'nextdrawn{i}.gvram.bin').read_bytes()
            if len(expected) != 71680 or len(actual) != 262144:
                sys.exit(f'invalid incremental output sizes: {out}')
            state = registers(out / f'nextdrawn{i}.registers.tsv')
            differences = sum(a != b for a, b in zip(expected, framebuffer(actual, args.planes, int(state['di'],16) if args.planes else 0)))
            clocks = int(state['clock']) - int(registers(out / f'nextbegin{i}.registers.tsv')['clock'])
            if args.planes:
                previous = check_planes_state(actual, path, renderer, previous, int(state['di'],16))
                check_rgb(out / f'shown{i}.screen.bmp', expected, palette)
                if registers(out / f'shown{i}.registers.tsv')['di'] != state['di']:
                    sys.exit('displayed page differs from composed page')
            tiles = int(state['ax'], 16)
            report = f'Incremental {i} ({path.name}): {differences} pixels differ; {tiles} tiles redrawn; {clocks} guest clocks\n'
            if args.sgp or args.planes:
                report += cache_report(state, args.planes)
            reports.append(report)
            (out / 'incremental.txt').write_text(''.join(reports))
            print(report)
            if differences:
                sys.exit(1)


if __name__ == '__main__':
    main()
