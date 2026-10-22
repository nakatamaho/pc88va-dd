#!/usr/bin/env python3
# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Add the game data, built from your ROM files, to the dd-pc88va MS-DOS disk.

    python3 -I install_roms.py [--fit-fm] dd-msdos4.d88 SOURCE [OUTPUT.d88]

SOURCE is the plugin DLL of the current commercial re-release, or the
game's install folder (the DLL is found inside), or a zip file or a
directory holding the ROM files under any names. Each ROM is recognised by
size and CRC-32 and checked by SHA-1 (DD.TXT lists them).

On this PC the script checks the ROMs, patches the three programs and
decodes the graphics into DDGAME.DAT, and adds it to the root of a copy of
the disk: OUTPUT (default DISK-roms.d88). --fit-fm also fits the FM voices
to the waveform PROM (needs NumPy) and adds them as FMVOICE.DAT, also
written beside OUTPUT for reuse; without it the disk has SSG sound only.
--quick-fm adds approximate voices without NumPy; --fmvoice FILE adds
voices made before. DD.COM only loads these files and the game checks them
(CRC-32) at start; the PC-88VA does no FM fitting. The two files can also
be copied to the disk under MS-DOS.

Needs pcengine_disk.py (from the vaeg project) beside this script.

The output disk and FMVOICE.DAT hold data from your ROM files: keep them
for yourself, do not distribute them.
"""

import argparse
import importlib.util
from pathlib import Path
import sys
import tempfile
import time

# python3 -I does not put the script's directory on sys.path. Leave no
# __pycache__ in the package directory.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ddpayload  # noqa: E402
import patches  # noqa: E402
import roms  # noqa: E402

SIGNATURE = b'DD-PC88VA BOOT DISK 1'          # in DD.COM's game code


def load_disk_tool():
    here = Path(__file__).resolve().parent
    for path in (here / 'pcengine_disk.py', here.parents[1] / 'vaeg/tools/pc88va/pcengine_disk.py'):
        if path.exists():
            spec = importlib.util.spec_from_file_location('pcengine_disk', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    sys.exit('error: pcengine_disk.py not found beside install_roms.py')


def read_file(tool, disk, name: str) -> bytes | None:
    offset, exists = tool.find_entry(disk.root, tool.short_name(name))
    if not exists:
        return None
    import struct
    cluster, size = struct.unpack_from('<HI', disk.root, offset + 26)
    return b''.join(disk.read_cluster(c) for c in disk.cluster_chain(cluster))[:size] if cluster else b''


def fm_voices(prom: bytes, mode: str) -> tuple[bytes, int]:
    if mode == 'quick':
        import fmvoice
        return fmvoice.additive(prom), 1
    try:
        import numpy  # noqa: F401
    except ImportError:
        sys.exit('error: --fit-fm needs NumPy (pip install numpy); --quick-fm needs none; no output disk written')
    import fmfit
    print('Fitting 16 FM voices on this PC (takes a while; uses every CPU core)...', flush=True)
    started = time.monotonic()
    voices = fmfit.fm_voices(prom)
    print(f'  done in {time.monotonic() - started:.0f} s', flush=True)
    return voices, 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('disk', type=Path, help='the MS-DOS disk without game data, dd-msdos4.d88')
    parser.add_argument('source', type=Path, help='the DLL, the install folder, or a zip/directory of ROM files')
    parser.add_argument('output', type=Path, nargs='?')
    parser.add_argument('--fit-fm', action='store_true',
                        help='fit FM voices on this PC (NumPy) and add FMVOICE.DAT')
    parser.add_argument('--quick-fm', action='store_true',
                        help='add approximate FM voices instead (no NumPy)')
    parser.add_argument('--fmvoice', type=Path, help='add this FMVOICE.DAT made before')
    parser.add_argument('--revision', choices=tuple(roms.REVISIONS),
                        help='program revision, when SOURCE holds both')
    args = parser.parse_args(argv)
    if args.fit_fm + args.quick_fm + bool(args.fmvoice) > 1:
        parser.error('choose one of --fit-fm, --quick-fm and --fmvoice')
    output = args.output or args.disk.with_name(args.disk.stem + '-roms' + args.disk.suffix)
    fm_out = output.with_name('FMVOICE.DAT')
    if output.exists():
        sys.exit(f'error: {output} exists; remove it to replace it')
    tool = load_disk_tool()
    try:
        disk = tool.PcEngineDisk(args.disk.read_bytes(), require_system_files=False)
    except Exception as error:      # the tool raises its own DiskError and ValueError
        sys.exit(f'error: {args.disk}: {error}')
    program_file = read_file(tool, disk, 'DD.COM')
    if program_file is None or SIGNATURE not in program_file:
        sys.exit(f'error: {args.disk} has no DD.COM of this version')
    if read_file(tool, disk, 'DDGAME.DAT') is not None:
        sys.exit(f'error: {args.disk} already holds DDGAME.DAT; use the disk without game data')

    print(f'Checking the ROM files in {args.source}:')
    source = roms.load(args.source)
    revision, main, sub, sound = roms.programs(args.source, args.revision)
    for role, (size, crc, _) in roms.ROMS.items():
        print(f'  {role:<13}{size:5} bytes  CRC-32 {crc:08X}  SHA-1 ok')
    for role, (size, crc, _) in roms.REVISIONS[revision].items():
        print(f'  {role:<13}{size:5} bytes  CRC-32 {crc:08X}  SHA-1 ok ({revision})')

    images = patches.apply(revision, main, sub, sound)
    if images.symbols != patches.static_symbols():
        sys.exit('error: these tools do not match the boot disk')
    program = images.main_segment + images.sound_segment
    area = bytearray(ddpayload.staged(source, revision, program))
    print(f'Programs patched ({images.patches} patches, sub program relocated); graphics decoded.')

    fm = None
    if args.fmvoice:
        try:
            method, voices = ddpayload.parse_fm_file(args.fmvoice.read_bytes())
        except (OSError, ValueError) as error:
            sys.exit(f'error: {args.fmvoice}: {error}')
        fm = ddpayload.fm_file(voices, method)
        print(f'FM voices from {args.fmvoice} ({ddpayload.FM_METHODS[method]}).')
    elif args.fit_fm or args.quick_fm:
        if fm_out.exists():
            sys.exit(f'error: {fm_out} exists; give it with --fmvoice, or remove it')
        voices, method = fm_voices(source['waves'], 'fit' if args.fit_fm else 'quick')
        fm = ddpayload.fm_file(voices, method)
    if fm is not None:
        area[ddpayload.FM_SLOT:ddpayload.FM_SLOT + len(fm)] = fm

    end = ddpayload.check_staged(bytes(area), program)['end']
    files = {'DDGAME.DAT': program + bytes(area[:end])}
    if fm is not None:
        files['FMVOICE.DAT'] = fm
    with tempfile.TemporaryDirectory(prefix='dd-install-') as tmp:
        for name, contents in files.items():
            path = Path(tmp) / name
            path.write_bytes(contents)
            try:
                tool.add_file(disk, disk.root, path)
            except Exception as error:
                sys.exit(f'error: {args.disk}: {error}; no output disk written')
    disk.flush()
    output.write_bytes(disk.image)
    if fm is not None and not args.fmvoice:
        fm_out.write_bytes(fm)
    voices_text = '' if fm is None else f' and {"fitted" if fm[6] == 2 else "quick"} FM voices'
    print(f'{output}: game data{voices_text} added ({revision}; private; do not distribute)')
    if fm is not None and not args.fmvoice:
        print(f'{fm_out}: the FM voices, for a later install with --fmvoice (private)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
