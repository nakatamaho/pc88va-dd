# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Replay synthetic sound states through native SSG/FM and check all targets.

No game programs or graphics. Optional user waveforms supply FM profiles;
without ROMs, synthetic sinusoidal waveforms keep this test ROM-free.
Includes request decoding, pitch/level conversion, changed-register writes
and bounded OPN busy waits. Source copying/export/initialization excluded.
"""

import argparse
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
import d88
import roms
from check_pages import address, registers
from sound import check_ssg
from fmvoice import generate, check_registers


def make_state(frequency, volume, waveform):
    raw = bytearray([0xb0])*32
    for channel, end in enumerate((0x14,0x19,0x1e)):
        start = 0x10 if channel == 0 else end-3
        f = frequency if channel == 0 else frequency >> 4
        for index in range(start,end+1):
            raw[index] = 0xa0|((f >> (4*(index-start)))&15)
        raw[end+1] = 0xa0|volume
        raw[5+channel*5] = 0xf8|((waveform+channel)&7)
    return bytes(raw)


def cases():
    result = []
    for waveform in range(8):
        for frequency in (2048,12288):
            result.append(make_state(frequency,1+2*waveform,waveform))
    for frequency in (0,1,332,333,256,6291,6292,65535,65536,681574,681575,1048575):
        result.append(make_state(frequency,15,frequency&7))
    result.append(make_state(65536,0,0))
    # Only one voice changes (others' registers as before): the update
    # skips unchanged voices, so the changed one alone must be rewritten.
    base = bytearray(make_state(12288, 9, 2))
    result.append(bytes(base))
    step = bytearray(base); step[0x1a] = 0xa0 | 4; result.append(bytes(step))       # voice 1 volume
    step = bytearray(step); step[0x1c] = 0xa0 | 7; result.append(bytes(step))       # voice 2 frequency
    step = bytearray(step); step[0x05] = 0xf8 | 6; result.append(bytes(step))       # voice 0 waveform
    step = bytearray(step); step[0x10] = 0xa0 | 9; result.append(bytes(step))       # voice 0 low nibble
    step = bytearray(step); step[0x1f] = 0xa0; result.append(bytes(step))           # voice 2 off
    return [state for state in result for _ in range(2)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vaeg',type=Path,required=True)
    parser.add_argument('--bios',type=Path,required=True)
    parser.add_argument('--roms',type=Path,default=roms.DEFAULT)
    parser.add_argument('--mode',choices=('ssg','fm-lite','fm-fit'),default='ssg')
    args = parser.parse_args()
    root = d88.REPO/'build/sound-check'
    root.mkdir(parents=True,exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-',dir=root))
    states = cases()
    data = b''.join(states)
    profiles = None
    defines = []
    if args.mode != 'ssg':
        if args.roms is None:
            prom = bytes(round(7.5+7.5*math.sin(2*math.pi*(wave+1)*i/32)) for wave in range(8) for i in range(32))
        else:
            prom = roms.load(args.roms,('waves',))['waves']
        profiles = generate(prom,args.mode,d88.REPO/'build/fm-cache')
        defines += ['M03_FM=1']
    if args.mode == 'fm-fit':
        defines += ['M03_FM_FIT=1']
    include = f'%define P_STATES 4096\n%define P_COUNT {len(states)}\n%define N_FM_VOICES {4096+len(data)}\n'
    if profiles is not None:
        data += profiles
    disk = out/'sound.d88'
    d88.build_boot_disk(d88.REPO/'src/m03/sound_probe.asm',include,data,disk,'DDM03SOUND',4096,defines,
                        listing=disk.with_suffix('.lst'))
    listing = disk.with_suffix('.lst').read_text()
    begin,end,export = (address(listing,label) for label in ('sound_begin','sound_end','sound_exported'))
    script = 'debug-script 1\nlimit-frame 1500\n'
    for i in range(len(states)):
        script += (f'wait-pc {begin} 1\ncapture begin{i} registers\n'
                   f'wait-pc {end} 1\ncapture end{i} registers\n'
                   f'wait-pc {export} 1\ncapture state{i} registers gvram\n')
    (out/'run.debug').write_text(script+'exit\n')
    (out/'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\n')
    with (out/'vaeg.log').open('w') as log:
        subprocess.run([str(args.vaeg.resolve()),'--cfg',str(out/'va.cfg'),'--no-bkupmem',
                        '--nowait','--mute','--roms',str(args.bios.resolve()),'--fdd1',str(disk),
                        '--debug-script',str(out/'run.debug'),'--debug-output-dir',str(out)],
                       env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy'),
                       stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
    report = ['case,pass,active_voices,opn_writes,clocks']
    for i,state in enumerate(states):
        a = registers(out/f'begin{i}.registers.tsv')
        b = registers(out/f'end{i}.registers.tsv')
        c = registers(out/f'state{i}.registers.tsv')
        raw = (out/f'state{i}.gvram.bin').read_bytes()
        if int(a['ax'],16) != i or int(c['ax'],16) != i or raw[0x30000:0x30020] != state or raw[0x30120]:
            sys.exit(f'bad sound export/timeout: case {i}; {out}')
        if profiles is None:
            active = check_ssg(state,raw[0x30020:0x30030])
        else:
            active = check_registers(state,raw[0x30020:0x30120],raw[0x30121:0x30124],profiles,args.mode == 'fm-fit')
        writes = int(c['bx'],16)
        if i&1 and writes:
            sys.exit(f'unchanged replay wrote OPN registers: {i}; {out}')
        report.append(f'{i//2},{"repeat" if i&1 else "changed"},{active},{writes},{int(b["clock"])-int(a["clock"])}')
    text = '\n'.join(report)+'\n'
    (out/'results.csv').write_text(text)
    print(f'{args.mode}: all {len(states)} native OPN target states match; {out}')
    print(text)


if __name__ == '__main__':
    main()
