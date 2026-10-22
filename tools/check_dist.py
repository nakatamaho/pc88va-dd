# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""End-to-end check of the dd-pc88va distribution (vaeg and your ROMs).

1. Build it without ROMs. Scan our packaged files for ROM bytes and
   forbidden words (heuristic, like publish.py): text files as publish.py
   does, DD.COM against this game's identified ROMs. The MS-DOS disk must
   hold DOS's files plus exactly ours, with no game data.
2. Boot the disk without game data: DD must say so and return to DOS.
3. Unpack the zip elsewhere and run install_roms.py there, as a user would:
   --fit-fm; again with --fmvoice (identical); without FM; from the DLL.
4. DDGAME.DAT and FMVOICE.DAT must equal the development FM-fit build's
   payload.
5. Boot the installed disk (MS-DOS, AUTOEXEC.BAT, DD) well into attract.
6. Run check_service.py on the installed test variant (SSG first, F10 to FM).
"""

import argparse
import importlib.util
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d88
import publish
import roms
from check_pages import address, registers

DOS_FILES = {'IO.SYS', 'MSDOS.SYS', 'COMMAND.COM', 'CONFIG.SYS', 'LICENSE.TXT', 'README.TXT'}
OUR_FILES = {'DD.COM', 'DD.TXT', 'DDLICENS.TXT', 'AUTOEXEC.BAT'}
LOAD_SEGMENTS = ('1DDC', '1DDB', '1DDD', '1DDA', '1DDE')     # where MS-DOS 4.0 runs DD.COM


def disk_tool():
    path = d88.REPO.parent / 'vaeg/tools/pc88va/pcengine_disk.py'
    spec = importlib.util.spec_from_file_location('pcengine_disk', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def disk_files(tool, path: Path) -> dict[str, bytes]:
    disk = tool.PcEngineDisk(path.read_bytes(), require_system_files=False)
    files = {}
    for _, entry in tool.iter_entries(disk.root):
        if entry[11] & 0x18:
            continue
        name = tool.display_name(bytes(entry[:11]))
        cluster, size = struct.unpack_from('<HI', entry, 26)
        files[name] = b''.join(disk.read_cluster(c) for c in disk.cluster_chain(cluster))[:size] if cluster else b''
    return files


def run_vaeg(args, disk, script, out):
    out.mkdir(parents=True, exist_ok=True)
    (out / 'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\n')
    (out / 'run.debug').write_text(script)
    with (out / 'vaeg.log').open('w') as log:
        subprocess.run([str(args.vaeg.resolve()), '--cfg', str(out / 'va.cfg'), '--no-bkupmem', '--nowait',
                        '--mute', '--roms', str(args.bios.resolve()), '--fdd1', str(disk),
                        '--debug-script', str(out / 'run.debug'), '--debug-output-dir', str(out)],
                       env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'),
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--vaeg', type=Path, required=True)
    parser.add_argument('--bios', type=Path, required=True)
    parser.add_argument('--roms', type=Path, default=roms.DEFAULT)
    parser.add_argument('--dll', type=Path, help='the re-release plugin DLL: install from it too and compare')
    parser.add_argument('--scan-roms', type=Path, action='append', default=[],
                        help='more ROM sources whose bytes must not appear (e.g. a reference set)')
    parser.add_argument('--names', type=Path, default=d88.REPO.parent / 'pc88va-dd.names')
    args = parser.parse_args()
    if args.roms is None:
        parser.error('give --roms or set DD_ROMS')
    py = [sys.executable, '-I']
    env = {k: v for k, v in os.environ.items() if k != 'DD_ROMS'}
    tool = disk_tool()
    report = []

    subprocess.run(py + [str(d88.REPO / 'tools/build_dist.py')], check=True, env=env, stdout=subprocess.DEVNULL)
    dist = d88.REPO / 'build/dist'
    with zipfile.ZipFile(dist / 'dd-pc88va.zip') as archive:
        files = {info.filename: (archive.read(info), 0o100644) for info in archive.infolist()}
    names = [s.strip().lower() for s in args.names.read_text().splitlines()
             if s.strip() and not s.startswith('#')]
    windows = set()
    for source in [args.roms, *args.scan_roms]:
        windows |= publish.rom_windows(source)
    text = {k: v for k, v in files.items() if k.endswith(('.py', '.TXT'))}
    problems = publish.check(text, windows, names)
    # DD.COM is binary: compare it with this game's identified ROMs (all
    # roles, every revision found), with windows of at least four distinct
    # bytes; zero runs with a byte or two, as in padding, match anything.
    known = []
    for source in [args.roms, *args.scan_roms]:
        known += list(roms._find(source, roms.ROMS).values())
        for table in roms.REVISIONS.values():
            known += list(roms._find(source, table).values())
    role_windows = {data[i:i + 8] for data in known for i in range(len(data) - 7)
                    if len(set(data[i:i + 8])) >= 4}
    com = files['dd-pc88va/DD.COM'][0]
    problems += publish.check({'DD.COM': (com, 0)}, role_windows, names)
    on_disk = disk_files(tool, dist / 'dd-msdos4.d88')
    if set(on_disk) != DOS_FILES | OUR_FILES:
        problems.append(f'dd-msdos4.d88 holds {sorted(on_disk)}')
    elif on_disk['DD.COM'] != com:
        problems.append('DD.COM on the disk differs from the packaged one')
    if problems:
        sys.exit('package scan: ' + '; '.join(problems))
    report.append(f'package: {len(files)} files; no ROM bytes or forbidden words (heuristic; DD.COM against '
                  f'{len(known)} identified ROMs); the disk holds MS-DOS and our files only')

    root = d88.REPO / 'build/dist-check'
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    dd_listing = (d88.REPO / 'build/dist-dd.lst').read_text()
    fail = int(address(dd_listing, 'fail').split(':')[1], 16) + 0x100 + 3     # after printing
    message = None
    for segment in LOAD_SEGMENTS:
        target = out / f'norom-{segment}'
        run_vaeg(args, dist / 'dd-msdos4.d88', f'debug-script 1\nlimit-frame 2000\n'
                 f'wait-pc {segment}:{fail:04X} 1\ncapture norom tvram\nexit\n', target)
        if (target / 'norom.tvram.bin').exists():
            raw = (target / 'norom.tvram.bin').read_bytes()
            message = raw[44 + struct.unpack_from('<I', raw, 12)[0]:][:8000:2].decode('ascii', 'replace')
            break
    if message is None or 'DDGAME.DAT not found' not in message:
        sys.exit(f'disk without game data: no message from DD; {out}')
    report.append(f'disk without game data: MS-DOS starts DD (at {segment}h), which says DDGAME.DAT is missing')

    user = out / 'user'
    with zipfile.ZipFile(dist / 'dd-pc88va.zip') as archive:
        archive.extractall(user)
    package = user / 'dd-pc88va'
    rom_source = args.roms.resolve()
    subprocess.run(py + ['install_roms.py', '--fit-fm', 'dd-msdos4.d88', str(rom_source)], cwd=package,
                   check=True, env=env, stdout=subprocess.DEVNULL)
    installed = package / 'dd-msdos4-roms.d88'
    if (package / '__pycache__').exists():
        sys.exit('install_roms.py left __pycache__ in the package directory')
    subprocess.run(py + ['install_roms.py', '--fmvoice', 'FMVOICE.DAT', 'dd-msdos4.d88', str(rom_source),
                         'again.d88'], cwd=package, check=True, env=env, stdout=subprocess.DEVNULL)
    if disk_files(tool, installed) != disk_files(tool, package / 'again.d88'):
        sys.exit('reinstall with --fmvoice differs')
    subprocess.run(py + ['install_roms.py', 'dd-msdos4.d88', str(rom_source), 'ssg.d88'], cwd=package,
                   check=True, env=env, stdout=subprocess.DEVNULL)
    if 'FMVOICE.DAT' in disk_files(tool, package / 'ssg.d88'):
        sys.exit('install without --fit-fm wrote an FMVOICE.DAT')
    report.append('install_roms.py from the unpacked zip: --fit-fm, --fmvoice (same files), no FM option (SSG only)')
    if args.dll:
        subprocess.run(py + ['install_roms.py', '--fmvoice', 'FMVOICE.DAT', 'dd-msdos4.d88',
                             str(args.dll.resolve()), 'dll.d88'], cwd=package, check=True, env=env,
                       stdout=subprocess.DEVNULL)
        if disk_files(tool, package / 'dll.d88') != disk_files(tool, installed):
            sys.exit('install from the DLL differs from the install from ROM files')
        report.append('install from the plugin DLL: same files as from ROM files')

    dev = out / 'dev.d88'
    subprocess.run(py + [str(d88.REPO / 'tools/build_m03.py'), '--audio', 'fm-fit', '--roms', str(rom_source),
                         '--output', str(dev)], check=True, stdout=subprocess.DEVNULL)
    wanted = disk_files(tool, dev)
    got = disk_files(tool, installed)
    if any(got.get(name) != wanted.get(name) or name not in got for name in ('DDGAME.DAT', 'FMVOICE.DAT')):
        sys.exit('installed DDGAME.DAT/FMVOICE.DAT differ from the development build')
    report.append('DDGAME.DAT and FMVOICE.DAT equal the development FM-fit disk\'s')

    listing = (d88.REPO / 'build/dist.lst').read_text()
    run_vaeg(args, installed, f'debug-script 1\nlimit-frame 4000\nwait-frame 3500\n'
             f'wait-pc {address(listing, "live_sample")} 1\ncapture late registers\nexit\n', out / 'boot')
    updates = int(registers(out / 'boot/late.registers.tsv')['si'], 16)
    if updates < 500:
        sys.exit(f'installed disk: only {updates} picture updates by frame 3500; {out}')
    report.append(f'installed disk: MS-DOS, AUTOEXEC.BAT, DD; {updates} picture updates by frame 3500')

    test_disk = d88.REPO / 'build/dd-msdos4-test-roms.d88'
    subprocess.run(py + [str(d88.REPO / 'tools/build_dist.py'), '--test-keys', '--capture-state',
                         '--with-roms', str(rom_source)], check=True, env=env, stdout=subprocess.DEVNULL)
    result = subprocess.run(py + [str(d88.REPO / 'tools/check_service.py'), '--disk', str(test_disk),
                                  '--listing', str(d88.REPO / 'build/dist-test.lst'),
                                  '--fmvoice', str(test_disk.with_name('FMVOICE.DAT')), '--start', '1600',
                                  '--vaeg', str(args.vaeg), '--bios', str(args.bios), '--roms', str(rom_source)],
                            capture_output=True, text=True)
    if result.returncode:
        sys.exit('test variant: ' + (result.stdout + result.stderr).strip())
    report.append('test variant: ' + '; '.join(result.stdout.splitlines()[:-1]))
    text = '\n'.join(report) + '\n'
    (out / 'result.txt').write_text(text)
    print(text + str(out))


if __name__ == '__main__':
    main()
