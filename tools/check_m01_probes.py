# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Boot the compatible-mode regression probes and require four PASS results."""

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
from check_pages import address


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vaeg',type=Path,required=True)
    parser.add_argument('--bios',type=Path,required=True)
    parser.add_argument('--roms',type=Path,default=roms.DEFAULT)
    parser.add_argument('--revision',choices=tuple(roms.REVISIONS))
    args = parser.parse_args()
    root = d88.REPO/'build/m01-probe-check'
    root.mkdir(parents=True,exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-',dir=root))
    disk = out/'probes.d88'
    revision_args = ['--revision',args.revision] if args.revision else []
    subprocess.run([sys.executable,'-I',str(d88.REPO/'tools/build_m01.py'),'--probes',*revision_args,
                    '--roms',str(args.roms.resolve()),'--output',str(disk)],check=True)
    wait = address(disk.with_suffix('.lst').read_text(),'wait_key')
    (out/'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\n')
    (out/'run.debug').write_text(f'debug-script 1\nlimit-frame 2000\nwait-pc {wait} 1\n'
                                 'capture probes registers tvram screen\nexit\n')
    with (out/'vaeg.log').open('w') as log:
        subprocess.run([str(args.vaeg.resolve()),'--cfg',str(out/'va.cfg'),'--no-bkupmem','--nowait',
                        '--mute','--roms',str(args.bios.resolve()),'--fdd1',str(disk),
                        '--debug-script',str(out/'run.debug'),'--debug-output-dir',str(out)],
                       env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy'),
                       stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
    raw = (out/'probes.tvram.bin').read_bytes()
    if raw[:8] != b'VAEGSCN1':
        sys.exit('bad TVRAM capture')
    runid, = struct.unpack_from('<I',raw,12)
    start = 44+runid
    text = raw[start:start+8000:2].decode('ascii',errors='replace')
    if text.count('PASS') != 4 or 'FAIL' in text:
        sys.exit(f'probe verdicts differ: {out}')
    (out/'text.txt').write_text('\n'.join(text[i:i+80] for i in range(0,len(text),80)))
    print(f'Four compatible-mode probes PASS; {out}')


if __name__ == '__main__':
    main()
