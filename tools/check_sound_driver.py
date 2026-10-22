# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Check the sound driver model (tools/sound_driver.py) against MAME.

    python3 -I tools/check_sound_driver.py --mame PATH --system NAME --rompath DIR [--frames N]
    python3 -I tools/check_sound_driver.py --records FILE...

Runs the board in MAME twice (scripted play; play with random requests)
with tools/mame/sound_ticks.lua, then replays every recorded tick on the
model from the recorded state and requires the state after it (9A80h-9B7Fh,
which holds the register images) to match. Ticks during which main or sub
wrote the area are skipped. Prints which sounds and end routines occurred.
Recordings go to build/mame/ (ROM-derived; git ignores build/).

With --vaeg and --bios, the native driver (src/m03/sound_driver.inc) is
also checked: a selection of the recorded states (every kind of tick seen:
sounds playing, end routines, attract mode; then more at random) is run
through sd_tick by a self-booting probe (src/m03/driver_probe.asm; test
disks with the sound program under build/sound-driver/), and each result
(9A80h-9B3Ch and the registers 6800h-681Fh) must equal the model's. The
first ticks of each disk are timed.
"""

import argparse
import os
import random
from collections import Counter
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d88  # noqa: E402
import roms  # noqa: E402
from check_pages import address, registers  # noqa: E402
import sound_driver  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SIZE = 1 + 4 + 1 + 256 + 4 + 256 + 32


def records(path: Path):
    data = path.read_bytes()
    for offset in range(0, len(data) - SIZE + 1, SIZE):
        r = data[offset:offset + SIZE]
        if r[:1] != b'T':
            raise ValueError(f'{path}: bad record at {offset}')
        frame, disturbed = struct.unpack_from('<IB', r, 1)
        yield frame, disturbed, r[6:262], r[262:266], r[266:522]


def record(args, name: str, inject: bool) -> Path:
    out = REPO / 'build/mame' / f'sound-ticks-{name}.bin'
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='dd-mame-') as tmp:
        env = {'DD_OUT': str(out), 'DD_FRAMES': str(args.frames), 'DD_INJECT': '1' if inject else '0'}
        subprocess.run([args.mame, args.system, '-rompath', str(args.rompath), '-nvram_directory', tmp,
                        '-cfg_directory', tmp, '-video', 'none', '-sound', 'none', '-nothrottle',
                        '-skip_gameinfo', '-autoboot_delay', '0',
                        '-autoboot_script', str(REPO / 'tools/mame/sound_ticks.lua')],
                       env=dict(os.environ, **env), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--mame')
    parser.add_argument('--system', help="MAME's name of the rev1 (or rev2) set")
    parser.add_argument('--rompath', type=Path)
    parser.add_argument('--frames', type=int, default=20000)
    parser.add_argument('--roms', type=Path, default=roms.DEFAULT, help='ROM source for the sound program')
    parser.add_argument('--records', type=Path, nargs='*')
    parser.add_argument('--vaeg', type=Path)
    parser.add_argument('--bios', type=Path)
    parser.add_argument('--cases', type=int, default=1000, help='states run natively (default 1000)')
    args = parser.parse_args()
    if args.records:
        paths = args.records
    elif args.mame and args.system and args.rompath:
        paths = [record(args, 'play', False), record(args, 'inject', True)]
    else:
        parser.error('give --mame, --system and --rompath, or --records')
    program = roms.programs(args.roms)[3]
    played, ended = Counter(), Counter()
    kinds = {}
    routines = dict(sound_driver.END_ROUTINES)
    for address, routine in routines.items():
        sound_driver.END_ROUTINES[address] = (lambda a, r: lambda mem: (ended.update([a]), r(mem)))(address, routine)
    failed = False
    for path in paths:
        match = differ = skipped = 0
        first = None
        for frame, disturbed, before, inputs, after in records(path):
            if disturbed:
                skipped += 1
                continue
            mem = bytearray(65536)
            mem[:0x1000] = program
            mem[0x9A80:0x9B80] = before
            mem[0x8401], mem[0x8646], mem[0x8657], mem[0x87CF] = inputs
            before_ends = sum(ended.values())
            sound_driver.tick(mem)
            run = tuple(sorted(a for a, n in ended.items()))[-1:] if sum(ended.values()) > before_ends else ()
            kind = (tuple(n for n in range(0x15) if before[0x16 + n]), tuple(n for n in range(0x15) if before[n]),
                    run, inputs[2] & 2, inputs[3] & 0x10)
            kinds.setdefault(kind, []).append(bytes(before[:0xBD]) + bytes(inputs))
            played.update(n for n in range(0x15) if before[0x16 + n] or after[0x16 + n])
            wrong = [0x9A80 + i for i in range(256) if mem[0x9A80 + i] != after[i]]
            if wrong:
                differ += 1
                first = first or (frame, [(f'{a:04X}', mem[a], after[a - 0x9A80]) for a in wrong[:6]])
            else:
                match += 1
        print(f'{path.name}: {match} ticks match, {differ} differ, {skipped} skipped (main or sub wrote '
              f'meanwhile){"; first: " + str(first) if first else ""}')
        failed |= differ > 0
    print('sounds seen:', ' '.join(f'{n:02X}' for n in sorted(played)),
          '; not seen:', ' '.join(f'{n:02X}' for n in range(0x15) if not played[n]) or '-')
    print('end routines run:', ' '.join(f'{a:04X}' for a in sorted(ended)),
          '; not run:', ' '.join(f'{a:04X}' for a in sorted(routines) if not ended[a]) or '-')
    if args.vaeg and args.bios and not failed:
        failed = native(args, program, kinds)
    return 1 if failed else 0


STRIDE = 196            # driver_probe.asm: D_STRIDE, states per disk
PER_DISK = 65536 // STRIDE
TIMED = 60


def expected(program: bytes, state: bytes) -> bytes:
    mem = bytearray(65536)
    mem[:0x1000] = program
    mem[0x9A80:0x9A80 + 0xBD] = state[:0xBD]
    mem[0x8401], mem[0x8646], mem[0x8657], mem[0x87CF] = state[0xBD:0xC1]
    sound_driver.tick(mem)
    mem[sound_driver.BUSY] = 0          # the program clears it at the end
    return bytes(mem[0x9A80:0x9A80 + 0xBD] + mem[0x6800:0x6820])


def native(args, program: bytes, kinds: dict) -> bool:
    rng = random.Random(88)
    chosen = [states[0] for states in kinds.values()]
    rest = [s for states in kinds.values() for s in states[1:]]
    rng.shuffle(rest)
    chosen = (chosen + rest)[:max(args.cases, len(kinds))]
    print(f'native: {len(chosen)} states ({len(kinds)} kinds of tick)')
    root = REPO / 'build/sound-driver'
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    clocks, bad = [], 0
    for batch_start in range(0, len(chosen), PER_DISK):
        batch = chosen[batch_start:batch_start + PER_DISK]
        work = out / f'disk{batch_start // PER_DISK}'
        work.mkdir()
        disk = work / 'driver.d88'
        staged = b''.join(s + bytes(STRIDE - len(s)) for s in batch)
        d88.build_boot_disk(REPO / 'src/m03/driver_probe.asm', '', program, disk, 'DDM03DRV', 4096,
                            [f'P_COUNT={len(batch)}'], listing=disk.with_suffix('.lst'), staged=staged)
        listing = disk.with_suffix('.lst').read_text()
        begin, end, done = (address(listing, x) for x in ('driver_begin', 'driver_end', 'driver_done'))
        timed = min(TIMED, len(batch))
        script = 'debug-script 1\nlimit-frame 3000\n'
        for i in range(timed):
            script += f'wait-pc {begin} 1\ncapture b{i} registers\nwait-pc {end} 1\ncapture e{i} registers\n'
        script += f'wait-pc {done} 1\ncapture done registers gvram\nexit\n'
        (work / 'run.debug').write_text(script)
        (work / 'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\n')
        with (work / 'vaeg.log').open('w') as log:
            subprocess.run([str(args.vaeg.resolve()), '--cfg', str(work / 'va.cfg'), '--no-bkupmem', '--nowait',
                            '--mute', '--roms', str(args.bios.resolve()), '--fdd1', str(disk),
                            '--debug-script', str(work / 'run.debug'), '--debug-output-dir', str(work)],
                           env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'),
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
        for i in range(timed):
            a, b = registers(work / f'b{i}.registers.tsv'), registers(work / f'e{i}.registers.tsv')
            if int(a['ax'], 16) != i:
                sys.exit(f'probe out of step at {i}; {work}')
            clocks.append(int(b['clock']) - int(a['clock']))
        gvram = (work / 'done.gvram.bin').read_bytes()
        for i, state in enumerate(batch):
            got = gvram[i * 256:i * 256 + 0xBD + 32]
            want = expected(program, state)
            if got != want:
                bad += 1
                if bad <= 5:
                    diff = [(f'{(0x9A80 + k) if k < 0xBD else (0x6800 + k - 0xBD):04X}', got[k], want[k])
                            for k in range(len(want)) if got[k] != want[k]]
                    print(f'  state {batch_start + i}: native differs: {diff[:8]}')
    print(f'native: {len(chosen) - bad} of {len(chosen)} ticks equal to the model; clocks a tick '
          f'(first {len(clocks)}): mean {sum(clocks) // len(clocks)}, max {max(clocks)}; {out}')
    return bad > 0


if __name__ == '__main__':
    sys.exit(main())
