# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Exhaustively run the guest SSG period routine on every nonzero 20-bit F."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
import d88
from check_pages import address, registers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vaeg',type=Path,required=True)
    parser.add_argument('--bios',type=Path,required=True)
    parser.add_argument('--mode',choices=('ssg','fm-lite','fm-fit'),default='ssg')
    args = parser.parse_args()
    root = d88.REPO/'build/sound-math'
    root.mkdir(parents=True,exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-',dir=root))
    disk = out/'math.d88'
    defines = [] if args.mode == 'ssg' else ['MATH_FM=1','M03_FM=1']
    if args.mode == 'fm-fit':
        defines += ['M03_FM_FIT=1']
    d88.build_boot_disk(d88.REPO/'src/m03/math_probe.asm','',b'',disk,'DDM03MATH',4096,defines,
                        listing=disk.with_suffix('.lst'))
    done = address(disk.with_suffix('.lst').read_text(),'math_done')
    (out/'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\n')
    (out/'run.debug').write_text(f'debug-script 1\nlimit-frame 10000\nwait-pc {done} 1\n'
                                 'capture math registers\nexit\n')
    with (out/'vaeg.log').open('w') as log:
        subprocess.run([str(args.vaeg.resolve()),'--cfg',str(out/'va.cfg'),'--no-bkupmem',
                        '--nowait','--mute','--roms',str(args.bios.resolve()),'--fdd1',str(disk),
                        '--debug-script',str(out/'run.debug'),'--debug-output-dir',str(out)],
                       env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy'),
                       stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300)
    state = registers(out/'math.registers.tsv')
    total = parity = 0
    from fmvoice import pitch
    for frequency in range(1,1 << 20):
        period = max(1,min(4095,1363148//frequency)) if args.mode == 'ssg' else pitch(frequency,args.mode == 'fm-fit')
        total += period
        parity ^= period
    total &= 0xffffffff
    actual = int(state['ax'],16)|(int(state['dx'],16) << 16)
    if actual != total or int(state['bx'],16) != parity or int(state['si'],16) != 16:
        sys.exit(f'exhaustive period checksum differs: {out}')
    report = f'{args.mode}: all 1048575 nonzero 20-bit inputs completed; sum/xor match host arithmetic ({total}/{parity}).\n'
    (out/'result.txt').write_text(report)
    print(report+str(out))


if __name__ == '__main__':
    main()
