# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Build the dd-pc88va distribution: an MS-DOS 4.0 disk with DD.COM, and
install_roms.py.

    python3 -I tools/build_dist.py [--msdos4 PATH] [--with-roms SOURCE]

Needs no ROMs. DD.COM (src/dos/dd.asm) holds the game's native code, which
is revision-independent, and loads DDGAME.DAT and FMVOICE.DAT, which
install_roms.py builds on the user's PC (tools/ddpayload.py). The disk is a
copy of the FreeDOS-88VA project's MS-DOS 4.0 for the PC-88VA (MIT licence,
release msdos4-va.2, msdos4-pc88va-2hd.d88, checked by its SHA-256) keeping
the system files, the licence and the readme, plus DD.COM, DD.TXT,
DDLICENS.TXT and an AUTOEXEC.BAT that starts DD. Output, in build/dist/
(ignored by git):

    dd-msdos4.d88    the disk, without game data
    DD.COM
    install_roms.py  and the modules it uses, with pcengine_disk.py (vaeg)
    DD.TXT           docs/dist/DD.TXT
    DDLICENS.TXT     LICENSE
    dd-pc88va.zip    all of the above

With --with-roms SOURCE, install_roms.py --fit-fm is also run on that
source (build/dd-msdos4-roms.d88, private, for tests). --test-keys and
--capture-state make a test variant in build/dist-test/, never distributed.
"""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d88  # noqa: E402
import dosdisk  # noqa: E402

MODULES = ('install_roms.py', 'ddpayload.py', 'roms.py', 'patches.py', 'z80.py', 'gfx.py',
           'render.py', 'fmfit.py', 'fmvoice.py')
DEFINES = ['DIST=1', 'M03_AUDIO=1', 'M03_FM=1', 'BACKGROUND_CACHE=1', 'SPRITE_COALESCE=1',
           'FRONT_HYBRID=1', 'FRONT_THRESHOLD=512', 'SERVICE_MENU=1', 'KEEP_CAPACITY=512',
           'L_RENDER_PERIOD=1', 'NATIVE_SOUND=1', 'FRAME_DEBT=3', 'RECT_SPRITES=1']


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--msdos4', type=Path, default=dosdisk.MSDOS4_DEFAULT,
                        help=f'msdos4-pc88va-2hd.d88 of {dosdisk.MSDOS4_RELEASE}')
    parser.add_argument('--with-roms', type=Path, metavar='SOURCE')
    parser.add_argument('--test-keys', action='store_true')
    parser.add_argument('--capture-state', action='store_true')
    args = parser.parse_args()
    dosdisk.check_msdos4(args.msdos4)
    test = args.test_keys or args.capture_state
    out = d88.REPO / ('build/dist-test' if test else 'build/dist')
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    extra = (['TEST_KEYS=1'] if args.test_keys else []) + (['LIVE_CAPTURE=1'] if args.capture_state else [])
    with tempfile.TemporaryDirectory(prefix='dd-dist-') as tmp:
        com = dosdisk.assemble(Path(tmp), DEFINES + extra, out.parent / (out.name + '.lst'))
    files = {'DD.COM': com, 'DD.TXT': dosdisk.text(d88.REPO / 'docs/dist/DD.TXT'),
             'DDLICENS.TXT': dosdisk.text(d88.REPO / 'LICENSE'), 'AUTOEXEC.BAT': dosdisk.AUTOEXEC}
    disk = out / 'dd-msdos4.d88'
    dosdisk.make_disk(files, disk, args.msdos4)
    packaged = [disk]
    for name in ('DD.COM', 'DD.TXT', 'DDLICENS.TXT'):
        (out / name).write_bytes(files[name])
        packaged.append(out / name)
    for name in MODULES:
        shutil.copy2(d88.REPO / 'tools' / name, out / name)
        packaged.append(out / name)
    shutil.copy2(dosdisk.VAEG_DISK_TOOL, out / 'pcengine_disk.py')
    packaged.append(out / 'pcengine_disk.py')
    if not test:
        with zipfile.ZipFile(out / 'dd-pc88va.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in packaged:
                archive.write(path, f'dd-pc88va/{path.name}')
    print(f'{disk}: MS-DOS 4.0 and DD.COM ({len(com)} bytes)' + (' (test variant)' if test else ''))
    if args.with_roms:
        target = d88.REPO / ('build/dd-msdos4-test-roms.d88' if test else 'build/dd-msdos4-roms.d88')
        for path in (target, target.with_name('FMVOICE.DAT')):
            path.unlink(missing_ok=True)
        subprocess.run([sys.executable, '-I', str(out / 'install_roms.py'), '--fit-fm', str(disk),
                        str(args.with_roms.resolve()), str(target)], check=True)


if __name__ == '__main__':
    main()
