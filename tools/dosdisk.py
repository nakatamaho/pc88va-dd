# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Game disks: MS-DOS 4.0 with DD.COM, and DDGAME.DAT/FMVOICE.DAT.

Every game disk is a copy of the FreeDOS-88VA project's MS-DOS 4.0 for the
PC-88VA (release msdos4-va.2, msdos4-pc88va-2hd.d88, MIT licence, checked by
SHA-256) with DD.COM (src/dos/dd.asm around the game code src/m02/live.asm),
an AUTOEXEC.BAT that runs DD, and, for a disk with game data, DDGAME.DAT and
FMVOICE.DAT as install_roms.py makes them. The game code needs no ROM.
"""

import hashlib
import importlib.util
from pathlib import Path
import tempfile

import d88
import ddpayload
import patches

VAEG_DISK_TOOL = d88.REPO.parent / 'vaeg/tools/pc88va/pcengine_disk.py'
MSDOS4_RELEASE = 'https://github.com/FreeDOS-88VA/MS-DOS/releases/tag/msdos4-va.2'
MSDOS4_SHA256 = '7c4b141d31e0034120e0b07eb93b9bea808e1c54822e48e15189cc7398385db0'
MSDOS4_DEFAULT = Path.home() / '.cache/vaeg/msdos4-va.2/dl/msdos4-pc88va-2hd.d88'
FIXED_FAT_DATE = ((2026 - 1980) << 9) | (10 << 5) | 18      # 2026-10-18
AUTOEXEC = b'@ECHO OFF\r\nPATH A:\\\r\nPROMPT $P$G\r\nVER\r\nDD\r\n'
BOOT_FRAMES = 700        # about when MS-DOS has started DD in vaeg (first picture ~650)


def load_disk_tool():
    spec = importlib.util.spec_from_file_location('pcengine_disk', VAEG_DISK_TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.fat_now = lambda: (0, FIXED_FAT_DATE)
    return module


def check_msdos4(path: Path) -> None:
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != MSDOS4_SHA256:
        raise SystemExit(f'error: {path} is not msdos4-pc88va-2hd.d88 of {MSDOS4_RELEASE}')


def assemble(work: Path, defines: list[str], listing: Path) -> bytes:
    """DD.COM: the game code (as at 2000:0000) with its MS-DOS loader."""
    (work / 'patch.inc').write_text(patches.nasm_include_static() + ddpayload.include())
    d88.nasm([*(f'-D{d}' for d in defines), f'-I{work}/', f'-I{d88.REPO / "src/m02"}/',
              '-l', str(listing), '-o', str(work / 'game.bin'), str(d88.REPO / 'src/m02/live.asm')])
    if len((work / 'game.bin').read_bytes()) != ddpayload.CODE_BYTES:
        raise SystemExit('error: the game code does not fit CODE_BYTES')
    (work / 'game.inc').write_text(
        f'%define GAME_BIN "{work / "game.bin"}"\n'
        f'CODE_BYTES\tequ\t{ddpayload.CODE_BYTES:#x}\n'
        f'PROGRAM_BYTES\tequ\t{ddpayload.PROGRAM_BYTES:#x}\n'
        f'FM_SLOT\t\tequ\t{ddpayload.FM_SLOT:#x}\n')
    d88.nasm([f'-I{work}/', '-l', str(listing.with_name(listing.stem + '-dd.lst')),
              '-o', str(work / 'DD.COM'), str(d88.REPO / 'src/dos/dd.asm')])
    return (work / 'DD.COM').read_bytes()


def make_disk(files: dict[str, bytes], output: Path, msdos4: Path = MSDOS4_DEFAULT) -> None:
    """A vanilla copy of MS-DOS 4.0 with FILES added to the root."""
    check_msdos4(msdos4)
    tool = load_disk_tool()
    with tempfile.TemporaryDirectory(prefix='dd-dos-') as tmp:
        work = Path(tmp)
        vanilla = work / 'vanilla.d88'
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            tool.create_vanilla(str(msdos4), str(vanilla))
        disk = tool.PcEngineDisk(vanilla.read_bytes(), require_system_files=False)
        for name, contents in files.items():
            path = work / name
            path.write_bytes(contents)
            tool.add_file(disk, disk.root, path)
        disk.flush()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(disk.image)


def game_files(source: dict, revision: str, program: bytes, fm: bytes | None) -> dict[str, bytes]:
    """DDGAME.DAT (programs, then the staged area to its end) and FMVOICE.DAT."""
    area = ddpayload.staged(source, revision, program)
    end = ddpayload.check_staged(area, program)['end']
    files = {'DDGAME.DAT': program + area[:end]}
    if fm is not None:
        files['FMVOICE.DAT'] = fm
    return files


def read_files(path: Path) -> dict[str, bytes]:
    """The root files of an MS-DOS disk image."""
    import struct
    tool = load_disk_tool()
    disk = tool.PcEngineDisk(path.read_bytes(), require_system_files=False)
    files = {}
    for _, entry in tool.iter_entries(disk.root):
        if entry[11] & 0x18:
            continue
        name = tool.display_name(bytes(entry[:11]))
        cluster, size = struct.unpack_from('<HI', entry, 26)
        files[name] = b''.join(disk.read_cluster(c) for c in disk.cluster_chain(cluster))[:size] if cluster else b''
    return files


def text(path: Path) -> bytes:
    return path.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
