# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Check live three-CPU/packed-renderer snapshots against host pixels.

A diagnostic-only build exports its exact video snapshot to unused GVRAM.
This checks internal composition, not lockstep execution against MAME or
final RGB at the instantaneous display-start swap event. Screenshots are
for observation only. All generated outputs contain user assets.
"""

import argparse
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
import d88
import roms
from render import Renderer
from check_pages import address, registers
from check_native import framebuffer, EXPORT, EXPORT_TRIPLE, BG_CACHE
from sound import check_ssg


def pending_rows(raw, export_base):
    """Background rows (8 lines each) the renderer has still to redraw."""
    return {row for row in range(28) if raw[export_base + 0x760 + row]}


def mismatches(expected, actual, skip_rows):
    """Differing pixels outside the rows in SKIP_ROWS (320x224 images)."""
    return sum(x != y for i, (x, y) in enumerate(zip(expected, actual)) if i // (320 * 8) not in skip_rows)


def snapshot(raw, export_base=0x30000):
    if len(raw) != 262144:
        raise ValueError('expected all GVRAM')
    state = raw[export_base:export_base+1416]
    memory = bytearray(65536)
    for begin, end, target in ((0,1024,0x8000),(1024,1152,0x8b80),
                               (1152,1280,0x9380),(1280,1408,0x9b80),(1408,1416,0xa000)):
        memory[target:target+end-begin] = state[begin:end]
    metadata = struct.unpack_from('<11H',raw,export_base+1416)
    cleaned = bytearray(raw)
    cleaned[export_base:export_base+1438] = bytes([0x5a])*1438
    return bytes(memory), metadata, bytes(cleaned)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vaeg',type=Path,required=True)
    parser.add_argument('--bios',type=Path,required=True)
    parser.add_argument('--roms',type=Path,default=roms.DEFAULT)
    parser.add_argument('--background-cache',action='store_true')
    parser.add_argument('--sound-priority',action='store_true')
    parser.add_argument('--sound-catchup',type=int,default=0)
    parser.add_argument('--test-round',type=int,default=0)
    parser.add_argument('--test-score',action='store_true',help='keep player 1\'s score at 50000 or more (the high score path)')
    parser.add_argument('--frame-debt',type=int,default=0)
    parser.add_argument('--native-sound',action='store_true')
    parser.add_argument('--rect-sprites',action='store_true')
    parser.add_argument('--no-m03-defaults',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--coalesce',action='store_true')
    parser.add_argument('--front-full',action='store_true')
    parser.add_argument('--front-hybrid',action='store_true')
    parser.add_argument('--ssg',action='store_true',help='alias for --audio ssg')
    parser.add_argument('--audio',choices=('off','ssg','fm-lite','fm-fit'),default='off')
    parser.add_argument('--no-export',action='store_true',help='production-path liveness/guard check only; no host pixel comparison')
    parser.add_argument('--revision',choices=tuple(roms.REVISIONS))
    parser.add_argument('--render-period',type=int,default=1)
    parser.add_argument('--samples',default='1,30,120,180,300,600,900,1000,1100,1200,1500')
    args = parser.parse_args()
    if args.ssg:
        if args.audio not in ('off','ssg'):
            parser.error('choose one audio mode')
        args.audio = 'ssg'
    counts = [int(s) for s in args.samples.split(',')]
    if not counts or counts != sorted(set(counts)) or counts[0] < 1:
        parser.error('--samples must be increasing positive update ordinals')
    root = d88.REPO / 'build/live-check'
    root.mkdir(parents=True,exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-',dir=root))
    disk = out / 'live.d88'
    revision_args = ['--revision',args.revision] if args.revision else []
    capture_args = [] if args.no_export else ['--capture-state']
    capture_args += ['--audio',args.audio]
    if args.sound_priority:
        capture_args += ['--sound-priority']
    if args.sound_catchup:
        capture_args += ['--sound-catchup',str(args.sound_catchup)]
    if args.test_round:
        capture_args += ['--test-round',str(args.test_round)]
    if args.test_score:
        capture_args += ['--test-score']
    if args.frame_debt:
        capture_args += ['--frame-debt',str(args.frame_debt)]
    if args.native_sound:
        capture_args += ['--native-sound']
    if args.rect_sprites:
        capture_args += ['--rect-sprites']
    if args.background_cache:
        capture_args += ['--background-cache']
    if args.coalesce:
        capture_args += ['--coalesce']
    if args.front_full:
        capture_args += ['--front-full']
    if args.front_hybrid:
        capture_args += ['--front-hybrid']
    subprocess.run([sys.executable,'-I',str(d88.REPO/'tools/build_live.py'),'--auto',*capture_args,*revision_args,
                    '--roms',str(args.roms.resolve()),'--render-period',str(args.render_period),'--output',str(disk)],check=True)
    listing = disk.with_suffix('.lst').read_text()
    begin,end,sample = (address(listing,label) for label in ('live_render_begin','live_render_end','live_sample'))
    script = f'debug-script 1\nlimit-frame {max(6000,counts[-1]*5) + 1000}\n'   # MS-DOS boots first
    previous = 0
    for count in counts:
        script += (f'wait-pc {begin} {count-previous}\ncapture begin{count} registers\n'
                   f'wait-pc {end} 1\ncapture end{count} registers\n'
                   f'wait-pc {sample} 1\ncapture sample{count} registers gvram screen\n')
        previous = count
    (out/'run.debug').write_text(script+'exit\n')
    (out/'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\nMonitor15kHzFill=true\nGUI_win_cx=640\nGUI_win_cy=470\n')
    with (out/'vaeg.log').open('w') as log:
        subprocess.run([str(args.vaeg.resolve()),'--cfg',str(out/'va.cfg'),'--no-bkupmem',
                        '--nowait','--mute','--frameskip','full','--effect','unfiltered','--scaling','native',
                        '--roms',str(args.bios.resolve()),'--fdd1',str(disk),
                        '--debug-script',str(out/'run.debug'),'--debug-output-dir',str(out)],
                       env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy'),
                       stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300)
    renderer = Renderer(roms.load(args.roms))
    profiles = disk.with_suffix('.fm.bin').read_bytes() if args.audio.startswith('fm-') else None
    export_base = (EXPORT_TRIPLE if args.rect_sprites else EXPORT) if args.background_cache else 0x30000
    active_samples = 0
    pending_samples = 0
    cache_rows = ['update,resident,hits,misses,fallbacks,filled,skipped']
    sound_rows = ['update,game_frame,nmi_delivered,nmi_dropped']
    rows = ['update,game_frame,vrtc,lost_frames,late_frames,render_clocks,bg_tiles,hits,misses,fallbacks,resident,cleared,page']
    for count in counts:
        a = registers(out/f'begin{count}.registers.tsv')
        b = registers(out/f'end{count}.registers.tsv')
        c = registers(out/f'sample{count}.registers.tsv')
        raw = (out/f'sample{count}.gvram.bin').read_bytes()
        if args.no_export:
            meta = (int(c['ax'],16),int(c['bx'],16),*(int(b[r],16) for r in ('ax','bx','cx','dx','si','bp','di')),int(c['si'],16),0)
            cleaned = raw
        else:
            memory, meta, cleaned = snapshot(raw, export_base)
            if args.audio != 'off':
                error_offset = export_base + (0x720 if profiles is not None else 0x630)
                if raw[error_offset]:
                    sys.exit(f'OPN busy timeout: {out}')
                if profiles is not None:
                    from fmvoice import check_registers
                    active_samples += bool(check_registers(raw[export_base+0x600:export_base+0x620],raw[export_base+0x620:export_base+0x720],
                                                          raw[export_base+0x721:export_base+0x724],profiles,args.audio == 'fm-fit'))
                    export_end = export_base+0x724
                else:
                    active_samples += bool(check_ssg(raw[export_base+0x600:export_base+0x620],raw[export_base+0x620:export_base+0x630]))
                    export_end = export_base+0x631
                cleaned = bytearray(cleaned)
                cleaned[export_base+0x600:export_end] = bytes([0x5a])*(export_end-export_base-0x600)
                delivered,dropped = struct.unpack_from('<2H',raw,export_base+0x750)
                sound_rows.append(f'{count},{meta[0]},{delivered},{dropped}')
                cleaned[export_base+0x750:export_base+0x754] = bytes([0x5a])*4
        frame,tick,tiles,hits,misses,fallbacks,resident,cleared,page,updates,rejected = meta
        if (updates != count or int(c['si'],16) != count or rejected
                or frame != int(a['ax'],16) or frame != int(c['ax'],16)
                or page != int(b['di'],16)):
            sys.exit(f'sample sequence or unsupported flip: {meta}; {out}')
        if args.background_cache:
            cleaned = bytearray(cleaned)
            cleaned[BG_CACHE:BG_CACHE+65536] = bytes([0x5a])*65536
            if not args.no_export:
                used,bg_hits,bg_misses,bg_full,bg_filled,bg_skipped = struct.unpack_from('<6H',raw,export_base+0x740)
                if used > 2048 or bg_hits+bg_misses+bg_full+bg_filled+bg_skipped != tiles:
                    sys.exit(f'background cache accounting differs: {out}')
                cache_rows.append(f'{count},{used},{bg_hits},{bg_misses},{bg_full},{bg_filled},{bg_skipped}')
                cleaned[export_base+0x740:export_base+0x74c] = bytes([0x5a])*12
        pending = pending_rows(raw, export_base)
        cleaned = bytearray(cleaned)
        cleaned[export_base+0x760:export_base+0x77c] = bytes([0x5a])*28
        pending_samples += bool(pending)
        actual = framebuffer(bytes(cleaned),True,page)  # validates unassigned-GVRAM canaries
        if not args.no_export:
            picture = renderer.render(memory)
            expected = b''.join(bytes(16)+picture[y*288:(y+1)*288]+bytes(16) for y in range(224))
            differences = mismatches(expected, actual, pending)
            if differences:
                sys.exit(f'update {count}: {differences} pixels differ; {out}')
            bare = bytearray(memory)
            bare[0x8b80:0x8c00] = bytes(128)
            bare[0x9380:0x9400] = bytes(128)
            bg = renderer.render(bytes(bare))
            bg = b''.join(bytes(16)+bg[y*288:(y+1)*288]+bytes(16) for y in range(224))
            actual_bg = bytes(v for byte in raw[0x20000:0x28c00] for v in (byte >> 4,byte & 15))
            if mismatches(bg, actual_bg, pending):
                sys.exit(f'update {count}: independent background differs; {out}')
            (out/f'{frame:06}.memory').write_bytes(memory)
        clocks = int(b['clock'])-int(a['clock'])
        rows.append(f'{count},{frame},{tick},{int(c["cx"],16)},{int(c["dx"],16)},'
                    f'{clocks},{tiles},{hits},{misses},{fallbacks},{resident},{cleared},{page}')
    report = '\n'.join(rows)+'\n'
    (out/'results.csv').write_text(report)
    if pending_samples:
        report += f'{pending_samples} samples had background rows still pending (compared outside them)\n'
    if args.audio != 'off':
        (out/'sound-timing.csv').write_text('\n'.join(sound_rows)+'\n')
    if args.background_cache:
        (out/'background-cache.csv').write_text('\n'.join(cache_rows)+'\n')
    if args.audio != 'off' and not args.no_export:
        print(f'{args.audio} register targets matched; {active_samples} sampled states had active voices.')
    if args.no_export:
        print('Production-path liveness and GVRAM guards only; no host pixel comparison.')
    print(report+str(out))


if __name__ == '__main__':
    main()
