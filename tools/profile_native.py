# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Profile the exact mixed movement fixture, with cold and warm sprite keys.

Uses guest-PC clocks, not estimates from pixel counts. Each submission's
second newly armed planes_wait return is deliberate: pre-submit and post-
submit waits both return through that PC. No ROM/capture output is committed.
"""

import argparse
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
import d88
import roms
from check_pages import address as next_address, registers
from check_native import framebuffer


def address(listing, label):
    start = listing.index(label+':')
    prefix = listing[listing.rfind('\n',0,start)+1:start]
    match = re.match(r'\s*\d+\s+([0-9A-F]{8})\b',prefix)
    if match:
        return f'2000:{int(match[1],16):04X}'
    return next_address(listing,label)


def run(args, warm):
    root = d88.REPO/'build/native-profile'
    root.mkdir(parents=True,exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='warm-' if warm else 'cold-',dir=root))
    disk = out/'profile.d88'
    fixtures = args.fixtures.resolve()
    sequence = ['base','tile','latch','sprite','edges','moved']
    if warm:
        sequence *= 2
    command = [sys.executable,'-I',str(d88.REPO/'tools/build_screen.py'),'--native-planes','--coalesce',
               '--memory-guards','--snapshot',str(fixtures/'base.memory'),'--roms',str(args.roms.resolve()),
               '--output',str(disk)]
    for name in sequence:
        command += ['--next-snapshot',str(fixtures/(name+'.memory'))]
    subprocess.run(command,check=True)
    listing = disk.with_suffix('.lst').read_text()
    begin,end = (address(listing,label) for label in ('native_next_begin','native_next_end'))
    clear = address(listing,'planes_clear')
    clear_end = address(listing.split('planes_clear:',1)[1].split('planes_sprite:',1)[0],'.done')
    sprite = address(listing,'planes_sprite')
    build = address(listing,'planes_list')
    built = address(listing.split('planes_list:',1)[1].split('planes_emit:',1)[0],'.submit')
    submit = address(listing,'planes_run')
    done = address(listing.split('planes_wait:',1)[1].split('planes_ready:',1)[0],'.ready')
    script = 'debug-script 1\nlimit-frame 3000\n'
    script += f'wait-pc {address(listing,"native_end")} 1\n'
    for _ in sequence[:-1]:
        script += f'wait-pc {end} 1\n'
    script += f'wait-pc {begin} 1\ncapture begin registers\n'
    script += f'wait-pc {clear} 1\ncapture clear_begin registers\n'
    script += f'wait-pc {clear_end} 1\ncapture clear_end registers\n'
    for i in range(24):
        for name,pc,ordinal in (('sprite',sprite,1),('build',build,1),('built',built,1),('submit',submit,1),('done',done,2)):
            script += f'wait-pc {pc} {ordinal}\ncapture {name}{i} registers\n'
    script += f'wait-pc {end} 1\ncapture end registers gvram\nexit\n'
    (out/'run.debug').write_text(script)
    (out/'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\n')
    with (out/'vaeg.log').open('w') as log:
        subprocess.run([str(args.vaeg.resolve()),'--cfg',str(out/'va.cfg'),'--no-bkupmem','--nowait','--mute',
                        '--roms',str(args.bios.resolve()),'--fdd1',str(disk),'--debug-script',str(out/'run.debug'),
                        '--debug-output-dir',str(out)],env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy'),
                       stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
    def clock(name):
        return int(registers(out/(name+'.registers.tsv'))['clock'])
    state = registers(out/'end.registers.tsv')
    hits,misses = int(state['bx'],16),int(state['cx'],16)
    if hits+misses != 24 or (warm and misses) or (not warm and misses != 15):
        sys.exit(f'not the intended fixture/cache state: {out}')
    suffix = f'.next{len(sequence)}.expected'
    expected = disk.with_suffix(suffix).read_bytes()
    actual = framebuffer((out/'end.gvram.bin').read_bytes(),True,int(state['di'],16))
    if actual != expected:
        sys.exit(f'profiled image differs: {out}')
    totals = {'clear':clock('clear_end')-clock('clear_begin'),'prepare':0,'list_build':0,'submit_wait':0}
    for i in range(24):
        totals['prepare'] += clock(f'build{i}')-clock(f'sprite{i}')
        totals['list_build'] += clock(f'built{i}')-clock(f'build{i}')
        totals['submit_wait'] += clock(f'done{i}')-clock(f'submit{i}')
    total = clock('end')-clock('begin')
    totals['other'] = total-sum(totals.values())
    report = 'part,clocks\n'+''.join(f'{key},{value}\n' for key,value in totals.items())+f'total,{total}\n'
    (out/'results.csv').write_text(report)
    print(('WARM' if warm else 'COLD')+f': hits={hits}, misses={misses}, cleared={int(state["bp"],16)}\n'+report+str(out))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vaeg',type=Path,required=True)
    parser.add_argument('--bios',type=Path,required=True)
    parser.add_argument('--roms',type=Path,default=roms.DEFAULT)
    parser.add_argument('--fixtures',type=Path,default=d88.REPO/'build/video-cases')
    args = parser.parse_args()
    for warm in (False,True):
        run(args,warm)


if __name__ == '__main__':
    main()
