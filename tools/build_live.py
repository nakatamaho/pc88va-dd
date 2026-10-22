# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Build a development game disk: MS-DOS 4.0 with DD.COM and the game data.

The game code (src/m02/live.asm) with the chosen options goes into DD.COM
(tools/dosdisk.py); DDGAME.DAT and FMVOICE.DAT are built from the ROMs
here, as install_roms.py builds them for users (tools/ddpayload.py). The
ROM source may be the re-release plugin DLL (DD_ROMS=.../Release_0.dll).
MS-DOS starts DD from AUTOEXEC.BAT, which loads everything where the game
expects it (code and programs at 2000h, staged area at 7000h). There are no
self-booting game disks. All output contains user assets: keep it private.
"""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d88
import ddpayload
import dosdisk
import patches
import roms

CODE_BYTES = ddpayload.CODE_BYTES
FM_METHOD = {'fm-lite': 1, 'fm-fit': 2}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roms', type=Path, default=roms.DEFAULT)
    parser.add_argument('--revision', choices=tuple(roms.REVISIONS), help='explicit program revision for merged verification inputs')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--msdos4', type=Path, default=dosdisk.MSDOS4_DEFAULT, help='msdos4-pc88va-2hd.d88 (msdos4-va.2)')
    parser.add_argument('--background-cache', action=argparse.BooleanOptionalAction, default=False, help='live composited-tile cache')
    parser.add_argument('--service', action=argparse.BooleanOptionalAction, default=False, help='F10 service screen (DIP switches, sound test)')
    parser.add_argument('--test-round', type=int, default=0, help='test only: start rounds at N (1..255)')
    parser.add_argument('--test-align', nargs=2, type=int, metavar=('X','Y'), help='test only: preset alignment position (dots, lines)')
    parser.add_argument('--align-frames', type=int, default=None, help='alignment screen length in frames (default 300; 0: none)')
    parser.add_argument('--sound-log', action='store_true', help='test only: log each sound tick to GVRAM 13000h')
    parser.add_argument('--test-score', action='store_true', help='test only: keep player 1\'s score at 50000 or more (a high score)')
    parser.add_argument('--diag', action='store_true', help='test only: the load display (F9) on from the start')
    parser.add_argument('--test-keys', action='store_true', help='vaeg tests: M=F10, P=play, U/D/L/R')
    parser.add_argument('--sound-catchup', type=int, default=0, metavar='N',
                        help='keep undelivered sound NMIs, up to N, instead of dropping them (0: off)')
    parser.add_argument('--frame-debt', type=int, default=0, metavar='N',
                        help='make up overrun frames, up to N VRTCs behind, instead of dropping them (0: off)')
    parser.add_argument('--native-sound', action=argparse.BooleanOptionalAction, default=False,
                        help='native sound driver in place of the sound program (docs/SOUND-DRIVER.md)')
    parser.add_argument('--sound-priority', action=argparse.BooleanOptionalAction, default=False, help='finish pending sound work before other CPUs')
    parser.add_argument('--front-full', action=argparse.BooleanOptionalAction, default=False, help='SGP-clear whole reused front and batch all pieces')
    parser.add_argument('--front-hybrid', action=argparse.BooleanOptionalAction, default=False, help='per-update choice of merged CPU runs or whole-front SGP clearing')
    parser.add_argument('--front-threshold', type=int, default=512)
    parser.add_argument('--rect-sprites', action=argparse.BooleanOptionalAction, default=False, help='fronts by rectangle lists (src/m02/rect_sprites.inc)')
    parser.add_argument('--coalesce', action=argparse.BooleanOptionalAction, default=False, help='merge fully dirty sprite pieces into single blits')
    parser.add_argument('--ssg', action='store_true', help='alias for --audio ssg')
    parser.add_argument('--audio', choices=('off','ssg','fm-lite','fm-fit'), default='off')
    parser.add_argument('--render-period', type=int, default=1, help='scheduler frames between rendering attempts, 1..8 (default: 1, 60 frames a second when there is time)')
    parser.add_argument('--auto', action='store_true', help='script coin/start/movement for testing')
    parser.add_argument('--capture-state', action='store_true', help='diagnostic-only video-state export to unused GVRAM')
    args = parser.parse_args(argv)
    if args.ssg:
        if args.audio not in ('off','ssg'):
            parser.error('--ssg cannot be combined with an FM mode')
        args.audio = 'ssg'
    if args.output is None:
        args.output = d88.REPO / (f'build/m03-{args.audio}.d88' if args.audio != 'off' else 'build/m02-live.d88')
    if not 1 <= args.render_period <= 8:
        parser.error('--render-period must be 1..8')
    source = roms.load(args.roms)
    images = patches.apply(*roms.programs(args.roms,args.revision))
    profiles = None
    if args.audio.startswith('fm-'):
        from fmvoice import generate
        profiles = generate(source['waves'],args.audio,d88.REPO/'build/fm-cache')
    program = images.main_segment + images.sound_segment
    fm = ddpayload.fm_file(profiles, FM_METHOD[args.audio]) if profiles is not None else None
    data = dosdisk.game_files(source, images.revision, program, fm)
    defines = ['KEEP_CAPACITY=512', f'L_RENDER_PERIOD={args.render_period}']
    if args.service:
        defines += ['SERVICE_MENU=1']
    if args.test_keys:
        defines += ['TEST_KEYS=1']
    if args.test_align:
        defines += [f'ALIGN_TEST_X={args.test_align[0]}', f'ALIGN_TEST_Y={args.test_align[1]}']
    if args.align_frames is not None:
        defines += [f'ALIGN_FRAMES={args.align_frames}']
    if args.test_score:
        defines += ['TEST_SCORE=1']
    if args.diag:
        defines += ['DIAG=1']
    if args.sound_log:
        defines += ['SOUND_LOG=1']
    if args.test_round:
        if not 1 <= args.test_round <= 255:
            parser.error('--test-round must be 1..255')
        defines += [f'TEST_ROUND={args.test_round}']
    if args.background_cache:
        defines += ['BACKGROUND_CACHE=1']
    if args.coalesce:
        defines += ['SPRITE_COALESCE=1']
    if args.front_full and args.front_hybrid:
        parser.error('choose --front-full or --front-hybrid')
    if not 1 <= args.front_threshold <= 512:
        parser.error('--front-threshold must be 1..512')
    if args.front_full:
        defines += ['FRONT_FULL=1']
    if args.front_hybrid:
        defines += ['FRONT_HYBRID=1', f'FRONT_THRESHOLD={args.front_threshold}']
    if args.rect_sprites:
        defines += ['RECT_SPRITES=1']
    if args.frame_debt:
        defines += [f'FRAME_DEBT={args.frame_debt}']
    if args.audio != 'off':
        defines += ['M03_AUDIO=1']
        if args.sound_priority:
            defines += ['SOUND_PRIORITY=1']
        if args.native_sound:
            defines += ['NATIVE_SOUND=1']
        elif args.sound_catchup:
            defines += [f'SOUND_CATCHUP={args.sound_catchup}']
    if profiles is not None:
        defines += ['M03_FM=1']
    if args.auto:
        defines += ['LIVE_AUTO=1']
    if args.capture_state:
        defines += ['LIVE_CAPTURE=1']
    if images.symbols != patches.static_symbols():
        raise SystemExit('error: patch symbols differ from the ROM-free game code')
    import tempfile
    with tempfile.TemporaryDirectory(prefix='dd-live-') as tmp:
        com = dosdisk.assemble(Path(tmp), defines, args.output.with_suffix('.lst'))
    files = {'DD.COM': com, 'AUTOEXEC.BAT': dosdisk.AUTOEXEC, **data}
    dosdisk.make_disk(files, args.output, args.msdos4)
    if profiles is not None:
        args.output.with_suffix('.fm.bin').write_bytes(profiles)
    print(f'{args.output}: MS-DOS 4.0 game disk, {images.revision}; DD.COM {len(com)} bytes, '
          f'DDGAME.DAT {len(data["DDGAME.DAT"])} bytes; auto={args.auto}; capture={args.capture_state}; '
          f'period={args.render_period}; audio={args.audio}')


if __name__ == '__main__':
    main()
