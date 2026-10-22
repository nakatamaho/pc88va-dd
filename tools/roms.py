# Copyright (c) 2026 Nakata Maho
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR "AS IS" AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
# OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
# USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
# THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""The arcade ROM files the build needs, found by content.

The ROMs are the user's own and are not part of the repository. SOURCE (a
zip file or a directory) may hold them under any names: each file is
recognised by its size and CRC-32 and then checked by SHA-1. SOURCE may
also be a DLL, or a directory holding one at any depth, in which the ROMs
are stored as they are (the plugin DLL of the current commercial
re-release, 394240 bytes, CRC-32 AA58DC77): it is searched for each ROM
by size, CRC-32 and SHA-1, so no offsets are assumed. The default SOURCE
is the DD_ROMS environment variable.

Two revisions of the main and sub programs are known (REVISIONS); the
sound program, graphics and colour PROMs are the same for both.
"""

import hashlib
import os
import sys
import zipfile
import zlib
from pathlib import Path

# role: (size, CRC-32, SHA-1), the same for every revision
ROMS = {
    "sound": (4096, 0xA41BCE72, "2b9b74f56aa7939d9d47cf29497ae11f10d78598"),
    "chars": (2048, 0xF14A6FE1, "0aa63300c2cb887196de590aceb98f3cf06fead4"),
    "sprites1": (4096, 0xE22957C8, "4700c63f4f680cb8ab8c44e6f3e1712aabd5daa4"),
    "sprites2": (4096, 0x2829EC99, "3e435c1afb2e44487cd7ba28a93ada2e5ccbb86d"),
    "sprites3": (4096, 0x458499E9, "578bd839f9218c3cf4feee1223a461144e455df8"),
    "sprites4": (4096, 0xC58252A0, "bd79e39e8a572d2b5c205e6de27ca23e43ec9f51"),
    "bgtiles": (4096, 0x7B383983, "57f1e8f5171d13f9f76bd091d81b4423b59f6b42"),
    "bgmaps": (4096, 0x2CF399C2, "317c48818992f757b1bd0e3997fa99937f81b52c"),
    "palette": (32, 0x4CB9DA99, "91a5852a15d4672c29fdcbae75921794651f960c"),
    "spritelookup": (256, 0x00C7C419, "7ea149e8eb36920c3b84984b5ce623729d492fd3"),
    "bglookup": (256, 0xE9B3E08E, "a294cc4da846eb702d61678396bfcbc87d30ea95"),
    "waves": (256, 0x7A2815B4, "085ada18c498fdb18ecedef0ea8fe9217edb7b46"),
}

# The main (4 x 4 KiB) and sub (2 x 4 KiB) programs by revision, preferred
# first. "rev1", the one in a current commercial re-release, is the main
# target; "rev2" is kept working.
REVISIONS = {
    "rev1": {
        "main1": (4096, 0xB9198079, "1d3fe04020f584ed250e32fdc6f6a3b769342884"),
        "main2": (4096, 0xB2ACBE49, "c8f713e8cfa70d3bc64d3002ff7bffc65ee138e2"),
        "main3": (4096, 0xD6407B49, "0e71a8f02778286488865e20439776dbb2a8ec78"),
        "main4": (4096, 0xF4CEBC16, "19b568f92069a1cfe1c07287408efe3b0e253375"),
        "sub1": (4096, 0x370EF9B4, "746b1fa15f5f2cfd69d8b5a7d6fb8c770abc3b4d"),
        "sub2": (4096, 0x361EEB71, "372c97c666411c3590d790213ae6fa1ccb5ffa1c"),
    },
    "rev2": {
        "main1": (4096, 0xA80EC984, "86689980410b9429cd7582c7a76342721c87d030"),
        "main2": (4096, 0x559F00BD, "fde17785df21956d6fd06bcfe675c392dadb1524"),
        "main3": (4096, 0x8CBC6FE1, "57b8a5777f8bb9773caf0cafe5408c8b9768cb25"),
        "main4": (4096, 0xD066F830, "b0a615fe4a5c8742c1e4ef234ef34c369d2723b9"),
        "sub1": (4096, 0x6687933B, "c16144de7633595ddc1450ddce379f48e7b2195a"),
        "sub2": (4096, 0x843D857F, "89b2ead7e478e119d33bfd67376cdf28f83de67a"),
    },
}
DEFAULT = Path(os.environ["DD_ROMS"]) if os.environ.get("DD_ROMS") else None


CONTAINER_LIMIT = 16 << 20     # largest DLL searched


def _files(source: Path):
    """ROM candidates (files of up to 4 KiB) and containers to search (DLLs)."""
    if source.is_dir():
        for path in sorted(source.iterdir()):
            if path.is_file() and path.stat().st_size <= 4096:
                yield path.read_bytes()
        for path in sorted(source.rglob('*')):
            if (path.is_file() and path.suffix.lower() == '.dll'
                    and path.stat().st_size <= CONTAINER_LIMIT):
                yield path.read_bytes()
    elif zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            for info in archive.infolist():
                if not info.is_dir() and info.file_size <= 4096:
                    yield archive.read(info)
    elif source.stat().st_size <= CONTAINER_LIMIT:
        yield source.read_bytes()             # one ROM file, or a DLL


def _search(data: bytes, table: dict, found: dict) -> None:
    """Find TABLE's ROMs stored as they are inside DATA (a DLL). Offsets
    that are multiples of 16 first, then every offset for what is missing."""
    view = memoryview(data)
    for step in (16, 1):
        for size in sorted({size for size, _, _ in table.values()}):
            wanted = {crc: role for role, (s, crc, _) in table.items() if s == size and role not in found}
            for offset in range(0, len(data) - size + 1, step):
                if not wanted:
                    break
                role = wanted.get(zlib.crc32(view[offset:offset + size]))
                if role is not None:
                    piece = bytes(view[offset:offset + size])
                    if hashlib.sha1(piece).hexdigest() == table[role][2]:
                        found[role] = piece
                        del wanted[table[role][1]]
        if all(role in found for role in table):
            return


def _find(source: Path | None, table: dict) -> dict[str, bytes]:
    if source is None:
        sys.exit("error: no ROM source: give --roms PATH or set DD_ROMS")
    by_key = {(size, crc): role for role, (size, crc, _) in table.items()}
    found = {}
    for data in _files(Path(source)):
        if len(data) > 4096:
            _search(data, table, found)
            continue
        role = by_key.get((len(data), zlib.crc32(data)))
        if role is not None and hashlib.sha1(data).hexdigest() == table[role][2]:
            found.setdefault(role, data)
    return found


def _missing(table: dict, roles) -> str:
    return ", ".join(f"{r} (CRC-32 {table[r][1]:08X}, {table[r][0]} bytes)" for r in roles)


def load(source: Path | None, roles=tuple(ROMS)) -> dict[str, bytes]:
    """The common ROMs of ROLES from SOURCE, by role."""
    found = _find(source, ROMS)
    missing = [r for r in roles if r not in found]
    if missing:
        sys.exit(f"error: {source} lacks the ROM(s) " + _missing(ROMS, missing))
    return {r: found[r] for r in roles}


def programs(source: Path | None, revision: str | None = None) -> tuple[str, bytes, bytes, bytes]:
    """The revision and the three CPUs' programs: main (16 KiB), sub
    (8 KiB), sound (4 KiB). By default use the first complete revision;
    REVISION can explicitly select one from a merged verification archive."""
    if revision is not None and revision not in REVISIONS:
        raise ValueError('unknown program revision')
    sound = load(source, ("sound",))["sound"]
    lacks = []
    for candidate, table in REVISIONS.items():
        if revision is not None and candidate != revision:
            continue
        found = _find(source, table)
        if len(found) == len(table):
            main = b"".join(found[f"main{i}"] for i in range(1, 5))
            return candidate, main, found["sub1"] + found["sub2"], sound
        lacks.append(f"{candidate}: " + _missing(table, [r for r in table if r not in found]))
    sys.exit(f"error: {source} holds no complete main and sub programs\n  "
             + "\n  ".join(lacks))
