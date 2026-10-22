# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Per-frame CPU budget of the running game, from a vaeg instruction trace.

Builds an automatic-input game disk (MS-DOS, DD), lets play run, then traces
SEGMENTS windows of up to 1M instructions, each starting at a VRTC. Every
traced instruction's consumed clocks are attributed by CS:IP:

    main / sub / Z80 stubs   compatible mode, CS 5000h (IP < 4000h / < 6000h / above)
    sound program            CS 6000h
    render                   native video: snapshot, composition, presentation
    sound update             native SSG/FM register updates
    scheduler                context switches, frame start, input
    custom I/O               06xx/51xx/53xx emulation
    VRTC ISR                 the vertical interrupt handler
    idle                     waiting for the next VRTC with nothing to run
    other                    BIOS, DOS and anything else

Frames run from one VRTC handler entry to the next. Time not charged to any
instruction (vaeg's per-access CPU charge for SGP transfers, and similar)
is the frame period (133460 clocks, measured) minus the attributed sum:
"unattributed". Also counts sound NMI entries (sound program at 0066h) per
frame: the game's sound runs on two per frame. Emulator timing only.
"""

import argparse
from collections import Counter, defaultdict
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d88
import roms
from check_pages import address

FRAME = 133460
LINE = re.compile(r'^\s*\d+\s+([0-9A-F]{8})\s')
LABEL = re.compile(r'^\s*\d+\s+(?:[0-9A-F]{8}\s+\S+\s+)?(?:<\d+>\s+)?([A-Za-z_][A-Za-z0-9_]*):')
GROUPS = (
    ('idle', ('idle_spin',)),
    ('VRTC ISR', ('vrtc', 'live_video_vrtc')),
    ('sound update', ('m03_',)),
    ('custom I/O', ('io_', 'm51_', 'm53_', 'raw_joy')),
    ('render', ('native', 'planes_', 'background_cache', 'keep_', 'live_', 'service_build', 'svc_',
                'tsp_')),
    ('scheduler', ('g_', 'run_cpu', 'inject', 'resume', 'yield_h', 'new_frame', 'scan_', 'auto_keys',
                   'service_', 'sound_in', 'sound_out', 'sound_sync', 'ctx_', 'ctxs')),
)


def labels(listing):
    pending, table = [], []
    for line in listing.splitlines():
        found = LABEL.match(line)
        if found:
            pending.append(found[1])
        at = LINE.match(line)
        if at and pending:
            table.extend((int(at[1], 16), name) for name in pending)
            pending = []
    table.sort()
    return table


def group_of(name):
    for group, prefixes in GROUPS:
        if any(name == p or name.startswith(p) for p in prefixes):
            return group
    return 'native other'


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--vaeg', type=Path, required=True, help='a trace-enabled vaeg build')
    parser.add_argument('--bios', type=Path, required=True)
    parser.add_argument('--roms', type=Path, default=roms.DEFAULT)
    parser.add_argument('--start', type=int, default=3000, help='guest frame of the first window')
    parser.add_argument('--segments', type=int, default=3)
    parser.add_argument('--gap', type=int, default=600, help='guest frames between windows')
    parser.add_argument('--trace-dir', type=Path, default=Path('/tmp'))
    parser.add_argument('--switches', type=int, default=750, help='Z80 runs timed in the second pass')
    parser.add_argument('--top', type=int, default=0, help='also list the N costliest native routines')
    parser.add_argument('--count', default='', help='comma-separated labels: entries per frame')
    parser.add_argument('--ips', default='', help='comma-separated routines: clocks by instruction')
    parser.add_argument('--no-z80', action='store_true', help='skip the second (Z80 run) pass')
    parser.add_argument('build', nargs='*', help='extra build_m03.py options (after --)')
    args = parser.parse_args()
    root = d88.REPO / 'build/frame-budget'
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    disk = out / 'budget.d88'
    subprocess.run([sys.executable, '-I', str(d88.REPO / 'tools/build_m03.py'), '--auto', '--roms',
                    str(args.roms.resolve()), '--output', str(disk), *args.build], check=True,
                   stdout=subprocess.DEVNULL)
    listing = disk.with_suffix('.lst').read_text()
    table = labels(listing)
    starts = [a for a, _ in table]
    vrtc = int(address(listing, 'vrtc').split(':')[1], 16)
    traces = Path(tempfile.mkdtemp(prefix='dd-budget-', dir=args.trace_dir))
    script = ['debug-script 1', f'limit-frame {args.start + args.segments * args.gap + 600}']
    for i in range(args.segments):
        script += [f'wait-frame {args.start + i * args.gap}', f'wait-pc 2000:{vrtc:04X} 1',
                   f'trace seg{i} 1000000']
    (out / 'run.debug').write_text('\n'.join(script + [f'wait-frame {args.start + args.segments * args.gap}',
                                                        'exit']) + '\n')
    (out / 'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\n')
    with (out / 'vaeg.log').open('w') as log:
        subprocess.run([str(args.vaeg.resolve()), '--cfg', str(out / 'va.cfg'), '--no-bkupmem', '--nowait',
                        '--mute', '--roms', str(args.bios.resolve()), '--fdd1', str(disk),
                        '--debug-script', str(out / 'run.debug'), '--debug-output-dir', str(traces)],
                       env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'),
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)

    import bisect
    counted = {int(address(listing, name).split(':')[1], 16): name for name in args.count.split(',') if name}
    entries = Counter()
    frames = []                     # (Counter of clocks by group, sound NMIs)
    routines = Counter()            # native clocks by label, over all complete frames
    pending = Counter()
    wanted = set(args.ips.split(',')) - {''}
    by_ip, ip_count = Counter(), Counter()
    for i in range(args.segments):
        path = traces / f'seg{i}.trace.log'
        current, nmis, started = None, 0, False
        cs = ip = None
        with path.open() as stream:
            for line in stream:
                if line.startswith('begin '):
                    cs = line[line.index('cs=') + 3:line.index('cs=') + 7]
                    ip = int(line[line.index('ip=') + 3:line.index('ip=') + 7], 16)
                    if cs == '2000' and ip == vrtc:
                        if started:
                            frames.append((current, nmis))
                            routines.update(pending)
                        current, nmis, started = Counter(), 0, True
                        pending = Counter()
                    if cs == '6000' and ip == 0x0066:
                        nmis += 1
                    if started and cs == '2000' and ip in counted:
                        pending['#' + counted[ip]] += 1
                elif line.startswith('end ') and started:
                    consumed = int(line[line.index('consumed=') + 9:].split()[0], 16)
                    if cs == '5000':
                        group = 'main' if ip < 0x4000 else 'sub' if ip < 0x6000 else 'Z80 stubs'
                    elif cs == '6000':
                        group = 'sound program'
                    elif cs == '2000':
                        k = bisect.bisect_right(starts, ip) - 1
                        group = group_of(table[k][1]) if k >= 0 else 'native other'
                        pending[table[k][1] if k >= 0 else '?'] += consumed
                        if k >= 0 and table[k][1] in wanted:
                            by_ip[ip] += consumed
                            ip_count[ip] += 1
                    else:
                        group = 'other'
                    current[group] += consumed
        path.unlink()
    shutil.rmtree(traces)
    if not frames:
        sys.exit('no complete frame traced')
    # The trace records native (V30) instructions only: Z80 code, timed in
    # the second pass, is part of 'unattributed' here, with SGP waits.
    order = ['render', 'sound update', 'scheduler', 'custom I/O', 'VRTC ISR', 'native other', 'other',
             'idle', 'unattributed']
    per = defaultdict(list)
    for counter, _ in frames:
        attributed = sum(counter.values())
        for group in order[:-1]:
            per[group].append(counter.get(group, 0))
        per['unattributed'].append(max(0, FRAME - attributed))
    busy = [FRAME - f['idle'] for f, _ in frames]
    rows = ['group,mean_clocks,mean_percent,max_clocks']
    for group in order:
        values = per[group]
        rows.append(f'{group},{statistics.mean(values):.0f},{100 * statistics.mean(values) / FRAME:.1f},'
                    f'{max(values)}')
    report = '\n'.join(rows) + '\n'
    report += (f'frames: {len(frames)}; frames with no idle time: '
               f'{sum(1 for f, _ in frames if f["idle"] == 0)}; mean busy {statistics.mean(busy) / FRAME:.1%}\n')
    ranked = sorted(busy)
    report += ('busy per frame: median %.1f%%, 90th percentile %.1f%%, max %.1f%%\n'
               % tuple(100 * ranked[min(len(ranked) - 1, int(q * len(ranked)))] / FRAME for q in (0.5, 0.9, 1)))
    for name in counted.values():
        report += f'{name}: {routines["#" + name] / len(frames):.3f} entries per frame\n'
    if wanted:
        text = {}
        for line in listing.splitlines():
            at = LINE.match(line)
            if at:
                text.setdefault(int(at[1], 16), line.split('>', 1)[-1].strip() if '<' in line else line[40:].strip())
        report += '\nip,clocks_per_frame,executions_per_frame,instruction\n'
        for ip in sorted(by_ip):
            report += (f'{ip:04X},{by_ip[ip] / len(frames):.0f},{ip_count[ip] / len(frames):.2f},'
                       f'{text.get(ip, "")}\n')
    if args.top:
        report += '\nroutine,group,mean_clocks,mean_percent\n'
        for name, clocks in [r for r in routines.most_common() if not r[0].startswith('#')][:args.top]:
            mean = clocks / len(frames)
            report += f'{name},{group_of(name)},{mean:.0f},{100 * mean / FRAME:.1f}\n'
    report = ('Native code per frame (instruction trace; "unattributed" is Z80 code and SGP waits):\n'
              + report)

    if args.no_z80:
        (out / 'budget.csv').write_text(report)
        print(report + str(out))
        return

    # Second pass: the trace above sees native code only. Every Z80 run
    # starts at resume (BX = its context) and returns to native code at
    # g_sched (yield or VRTC preemption): time those, from vaeg's clock.
    resume = address(listing, 'resume')
    sched = address(listing, 'g_sched')
    contexts = {}
    for name, cpu in (('ctx_main', 'main'), ('ctx_sub', 'sub'), ('ctx_sound', 'sound')):
        found = re.search(r'^\s*\d+\s+([0-9A-F]{8})\s.*\s' + name + r'\s+times', listing, re.MULTILINE)
        contexts[int(found[1], 16)] = cpu
    z80 = out / 'z80'
    z80.mkdir()
    chunk = 125                     # the debug script holds 512 commands
    for first in range(0, args.switches, chunk):
        part = z80 / f'part{first}'
        part.mkdir()
        script = ['debug-script 1', f'limit-frame {args.start + 4000}', f'wait-frame {args.start}']
        for i in range(first, min(first + chunk, args.switches)):
            # vaeg is deterministic: skip the runs timed by earlier parts.
            skip = first + 1 if i == first else 1
            script += [f'wait-pc {resume} {skip}', f'capture r{i} registers',
                       f'wait-pc {sched} 1', f'capture s{i} registers']
        (part / 'run.debug').write_text('\n'.join(script + ['exit']) + '\n')
        with (part / 'vaeg.log').open('w') as log:
            subprocess.run([str(args.vaeg.resolve()), '--cfg', str(out / 'va.cfg'), '--no-bkupmem', '--nowait',
                            '--mute', '--roms', str(args.bios.resolve()), '--fdd1', str(disk),
                            '--debug-script', str(part / 'run.debug'), '--debug-output-dir', str(z80)],
                           env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'),
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
    from check_pages import registers
    runs = []
    for i in range(args.switches):
        a = registers(z80 / f'r{i}.registers.tsv')
        b = registers(z80 / f's{i}.registers.tsv')
        runs.append((contexts.get(int(a['bx'], 16), '?'), int(a['clock']), int(b['clock'])))
    begin, end = runs[0][1], runs[-1][2]
    window = (end - begin) / FRAME
    by_cpu = Counter()
    count = Counter()
    per_frame = defaultdict(Counter)
    for cpu, start, stop in runs:
        by_cpu[cpu] += stop - start
        count[cpu] += 1
        per_frame[(start - begin) // FRAME][cpu] += stop - start
    native = (end - begin) - sum(by_cpu.values())
    rows = ['part,mean_clocks_per_frame,mean_percent,max_frame_clocks,runs_per_frame']
    for cpu in ('main', 'sub', 'sound'):
        mean = by_cpu[cpu] / window
        rows.append(f'{cpu} Z80 run,{mean:.0f},{100 * mean / FRAME:.1f},'
                    f'{max(f[cpu] for f in per_frame.values())},{count[cpu] / window:.2f}')
    rows.append(f'native (everything between Z80 runs),{native / window:.0f},{100 * native / window / FRAME:.1f},,')
    report += ('\nZ80 runs (second pass, %.0f frames; a run includes the native CALLN/VRTC entry,\n'
               '06xx I/O handled during it and, for sound, its register update):\n' % window)
    report += '\n'.join(rows) + '\n'
    (out / 'budget.csv').write_text(report)
    print(report + str(out))


if __name__ == '__main__':
    main()
