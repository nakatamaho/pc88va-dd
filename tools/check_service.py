# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Drive the F10 service screen in vaeg with test keys and check it.

Test keys (TEST_KEYS build): M = F10, P = play, U D L R = directions, typed
by the debug script. Checks the screen's text from the exported tile RAM,
its composition against the host renderer, the sound test (SSG, and FM
when built), and that a changed DIP switch restarts the programs.
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d88
import roms
from render import Renderer, tile_index
from check_pages import address
from check_live import snapshot, pending_rows, mismatches
from check_native import framebuffer, EXPORT_TRIPLE as EXPORT, BG_CACHE   # M03 builds: three fronts
from sound import decode, check_ssg



RESTART_SAMPLES = 16            # every 30 frames after the restart


def text_lines(memory):
    """The tile RAM as 36 game rows of 28 characters."""
    lines = []
    for gy in range(36):
        row = ''
        for gx in range(28):
            code = memory[0x8000 + tile_index(gy, 27 - gx)] & 0x7f
            if 0x10 <= code <= 0x19:
                row += chr(code - 0x10 + ord('0'))
            elif 0x1a <= code <= 0x33:
                row += chr(code - 0x1a + ord('A'))
            elif code == 0x7f:
                row += ' '
            else:
                row += '.'
        lines.append(row.rstrip())
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vaeg', type=Path, required=True)
    parser.add_argument('--bios', type=Path, required=True)
    parser.add_argument('--roms', type=Path, default=roms.DEFAULT)
    parser.add_argument('--audio', choices=('ssg', 'fm-lite', 'fm-fit'), default='fm-fit')
    parser.add_argument('--disk', type=Path, help='prebuilt TEST_KEYS/LIVE_CAPTURE disk with game data')
    parser.add_argument('--listing', type=Path, help='its listing (with --disk)')
    parser.add_argument('--fmvoice', type=Path, help='the FMVOICE.DAT installed on --disk, if any')
    parser.add_argument('--start', type=int, default=1600,
                        help='guest frame of the first step (MS-DOS boots first, about 650 frames)')
    args = parser.parse_args()
    if bool(args.disk) != bool(args.listing):
        parser.error('--disk and --listing go together')
    root = d88.REPO/'build/service-check'
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    if args.disk:
        # A distribution test disk: FM voices from the FMVOICE.DAT installed
        # on it; FM first when they are fitted, else SSG.
        disk, listing = args.disk.resolve(), args.listing.read_text()
        method, profiles = None, None
        if args.fmvoice:
            import ddpayload
            method, profiles = ddpayload.parse_fm_file(args.fmvoice.read_bytes())
        fm, fit = profiles is not None, method == 2
        initial_fm = fit                    # fitted voices start with FM
        fm_layout = True                    # the distribution always has the FM code
    else:
        disk = out/'service.d88'
        subprocess.run([sys.executable, '-I', str(d88.REPO/'tools/build_m03.py'), '--audio', args.audio,
                        '--test-keys', '--capture-state', '--roms', str(args.roms.resolve()),
                        '--output', str(disk)], check=True, stdout=subprocess.DEVNULL)
        listing = disk.with_suffix('.lst').read_text()
        fm = initial_fm = args.audio != 'ssg'
        fit = args.audio == 'fm-fit'
        profiles = disk.with_suffix('.fm.bin').read_bytes() if fm else None
        fm_layout = fm
    sample = address(listing, 'live_sample')
    # (frame, keys typed, capture id or None)
    steps = [(900, None, 'game'), (910, 'M', None), (960, None, 'menu'),
             (970, 'DD', None), (1010, 'R', None), (1050, None, 'lives5'),
             (1060, 'DDDDDD', None), (1110, 'RRRRR', None), (1200, None, 'test_first')]
    if fm:
        steps += [(1210, 'U', None), (1240, 'R', None), (1270, 'DP', None), (1310, None, 'test_second')]
    steps += [(1360, 'M', None)] + [(1380 + 30 * i, None, f'restart{i}') for i in range(RESTART_SAMPLES)]
    script = ['debug-script 1', f'limit-frame {args.start + 2100}']
    for frame, keys, capture in steps:
        script.append(f'wait-frame {frame - 900 + args.start}')
        if keys:
            script.append(f'input-line {keys}')
        if capture:
            script += [f'wait-pc {sample} 1', f'capture {capture} gvram']
    (out/'run.debug').write_text('\n'.join(script + ['exit']) + '\n')
    (out/'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\n')
    with (out/'vaeg.log').open('w') as log:
        subprocess.run([str(args.vaeg.resolve()), '--cfg', str(out/'va.cfg'), '--no-bkupmem', '--nowait',
                        '--mute', '--roms', str(args.bios.resolve()), '--fdd1', str(disk),
                        '--debug-script', str(out/'run.debug'), '--debug-output-dir', str(out)],
                       env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'),
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
    renderer = Renderer(roms.load(args.roms))
    report = []

    def load(name):
        raw = (out/f'{name}.gvram.bin').read_bytes()
        memory, meta, cleaned = snapshot(raw, EXPORT)
        cleaned = bytearray(cleaned)
        cleaned[BG_CACHE:BG_CACHE + 65536] = bytes([0x5a]) * 65536  # tile cache
        end = EXPORT + (0x724 if fm_layout else 0x631)
        cleaned[EXPORT + 0x600:end] = bytes([0x5a]) * (end - EXPORT - 0x600)
        cleaned[EXPORT + 0x740:EXPORT + 0x754] = bytes([0x5a]) * 0x14   # cache counters, NMI counts
        pending = pending_rows(raw, EXPORT)
        cleaned[EXPORT + 0x760:EXPORT + 0x77c] = bytes([0x5a]) * 28
        picture = renderer.render(memory)
        expected = b''.join(bytes(16) + picture[y*288:(y+1)*288] + bytes(16) for y in range(224))
        if name in ('menu', 'lives5') and pending:
            sys.exit(f'{name}: background rows still pending long after the change; {out}')
        if mismatches(expected, framebuffer(bytes(cleaned), True, meta[8]), pending):
            sys.exit(f'{name}: composed screen differs from host rendering; {out}')
        return raw, memory

    def require(name, lines, wanted):
        for gy, text in wanted:
            if text not in lines[gy]:
                sys.exit(f'{name}: row {gy} is {lines[gy]!r}, wanted {text!r}; {out}')

    _, game = load('game')
    if 'SERVICE MODE' in '\n'.join(text_lines(game)):
        sys.exit('menu visible before F10')
    _, menu = load('menu')
    lines = text_lines(menu)
    # Items from row 5, two rows apart (SVC_FIRST_Y in src/m03/service.inc).
    require('menu', lines, [(3, 'SERVICE MODE'), (5, 'COIN A'), (5, '1 COIN 1 CREDIT'),
                            (9, 'LIVES     3'), (11, 'BONUS     20K 60K'),
                            (19, 'SOUND     ' + ('FM' if initial_fm else 'SSG')), (21, 'TEST      SOUND 01'),
                            (23, 'ROUND     OFF'), (25, 'FPS       60')])
    if menu[0x8000 + tile_index(5, 27 - 1)] & 0x80 == 0:
        sys.exit('menu: first item is not highlighted')
    report.append('menu text, highlight and composition match')
    _, changed = load('lives5')
    require('lives5', text_lines(changed), [(9, 'LIVES     5'), (11, 'BONUS     20K')])
    report.append('LIVES 3 -> 5; BONUS follows the 5-lives table')

    def sound(name, use_fm):
        raw, memory = load(name)
        source = raw[EXPORT + 0x600:EXPORT + 0x620]
        if use_fm:
            from fmvoice import check_registers
            active = check_registers(source, raw[EXPORT + 0x620:EXPORT + 0x720],
                                     raw[EXPORT + 0x721:EXPORT + 0x724], profiles, fit)
        else:
            active = check_ssg(source, raw[EXPORT + 0x620:EXPORT + 0x630])
        if active == 0:
            sys.exit(f'{name}: the sound test produced no voice; {out}')
        report.append(f'{name}: {active} voices, register targets match')
        return memory

    # The second test switches the backend (FM builds start on FM, the
    # distribution on SSG).
    test = sound('test_first', use_fm=initial_fm)
    require('test_first', text_lines(test), [(21, 'TEST      SOUND 06')])
    if fm:
        test = sound('test_second', use_fm=not initial_fm)
        require('test_second', text_lines(test), [(19, 'SOUND     ' + ('SSG' if initial_fm else 'FM'))])
    # The restart clears Z80 RAM as at power-on; the restarted program's RAM
    # test does not yield, and the scheduler draws anyway (RENDER_STARVE):
    # the samples follow the boot (RAM OK, ROM OK, then attract, some 300
    # frames on).
    cleared = attract = False
    for i in range(RESTART_SAMPLES):
        memory = load(f'restart{i}')[1]
        lines = text_lines(memory)
        if 'SERVICE MODE' in '\n'.join(lines):
            sys.exit('restart: the menu is still visible')
        tiles = memory[0x8000:0x8400]
        fill = max(tiles.count(value) for value in set(tiles))
        uniform = fill >= 1000 and tiles.count(0x7f) < 1000      # RAM test pattern
        if uniform or any('RAM OK' in line for line in lines):
            cleared = True
        elif cleared and any('HIGH SCORE' in line for line in lines):
            attract = True
    if not (cleared and attract):
        sys.exit(f'restart: no boot RAM test followed by attract; {out}')
    report.append('DIP change restarted the programs (boot RAM test, then attract)')
    text = '\n'.join(report) + '\n'
    (out/'result.txt').write_text(text)
    print(text + str(out))


if __name__ == '__main__':
    main()
