# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Disk payload of the live game: layout, tables, staged area, FMVOICE.DAT.

Shared by the development builders and by install_roms.py, which builds the
payload on the user's PC from the user's ROM files. The layout and the
assembler definitions depend only on fixed sizes, so the ROM-less boot disk
can be assembled without ROMs; everything ROM-derived is built at install.

Disk sectors (1024 bytes): 0 IPL; 1-24 native code (CODE_BYTES); 25-55 the
patched programs (PROGRAM_BYTES), loaded with the code to 2000:0000; 56-119
the staged area, loaded to 7000:0000 and consumed at start. Staged area:
a header, the lookup tables (copied to CS:CODE_BYTES), the RLE pens, and at
FM_SLOT the optional FMVOICE.DAT.
"""

import struct
import zlib

SECTOR = 1024
CODE_BYTES = 0x6000
PROGRAM_BYTES = 0x6800 + 0x1100           # main and sound segments
LOAD_SECTORS = (CODE_BYTES + PROGRAM_BYTES + SECTOR - 1) // SECTOR
STAGE_SECTORS = 64
STAGE_BYTES = STAGE_SECTORS * SECTOR
FM_SLOT = 0xFC00
STAGE_FIRST_SECTOR = 1 + LOAD_SECTORS
PROGRAM_OFFSET = (1 + CODE_BYTES // SECTOR) * SECTOR      # in the flat disk image
STAGE_OFFSET = STAGE_FIRST_SECTOR * SECTOR

# magic, version, header size, table bytes, chars/bg/sprites RLE offsets,
# end, revision (1 or 2), reserved, CRC-32 of [header size, end),
# CRC-32 of the programs, reserved
HEADER = struct.Struct("<4sHHHHHHHBBIII")
HEADER_MAGIC = b"DDGA"
HEADER_VERSION = 1

FM_HEADER = struct.Struct("<4sHHIHHI")    # magic, version, method, wave CRC, size, 0, CRC
FM_MAGIC = b"DDFM"
FM_BYTES = 144
FM_METHODS = {1: "quick", 2: "fit"}
WAVES_CRC = 0x7A2815B4


def palette_word(r: int, g: int, b: int) -> int:
    return (round(g * 15 / 255) << 12) | (round(r * 15 / 255) << 6) | (round(b * 15 / 255) << 1)


def source_palette(prom: bytes) -> list[int]:
    def channel(value, resistors):
        weights = [1 / r for r in resistors]
        return round(255 * sum(w for bit, w in enumerate(weights) if value & (1 << bit)) / sum(weights))
    return [palette_word(channel(v & 7, (1000, 470, 220)),
                         channel((v >> 3) & 7, (1000, 470, 220)),
                         channel(v >> 6, (470, 220))) for v in prom]


def rle(pixels: bytes) -> bytes:
    out = bytearray()
    pos = 0
    while pos < len(pixels):
        end = pos + 1
        while end < min(pos + 255, len(pixels)) and pixels[end] == pixels[pos]:
            end += 1
        out.extend((end - pos, pixels[pos]))
        pos = end
    out.append(0)
    return bytes(out)


def tile_rows() -> bytes:
    from render import tile_index
    rows = bytearray([255]) * 1024
    for y in range(28):
        for x in range(36):
            index = tile_index(x, y)
            if rows[index] != 255:
                raise ValueError('video RAM mapping is not injective')
            rows[index] = y
    return bytes(rows)


# (name, size) of the tables copied to CS:CODE_BYTES, in order. Fixed sizes:
# the assembler offsets below need no ROM.
TABLES = (("PALETTE", 64), ("MAPS", 4096), ("BGLOOKUP", 256), ("SPRLOOKUP", 256),
          ("VRAM", 1024), ("OBJECT", 128), ("POSITION", 128), ("FLIP", 128), ("LATCH", 8),
          ("INDEX", 2016), ("ROWS", 1024), ("FM_VOICES", FM_BYTES), ("EMPTY", 128))
TABLE_BYTES = sum(size for _, size in TABLES)


def include() -> str:
    """NASM definitions of the table offsets (CS) and their total size."""
    lines, offset = [], CODE_BYTES
    for name, size in TABLES:
        lines.append(f"%define N_{name} {offset}")
        offset += size
    lines.append(f"%define N_DRAWN {offset}")    # 1008 words, not staged
    offset += 2016
    lines += [f"%define L_TABLE_BYTES {TABLE_BYTES}", f"%define STAGE_HEADER {HEADER.size}",
              f"%define PROGRAM_BYTES {PROGRAM_BYTES}", f"%define FM_SLOT {FM_SLOT:#x}",
              f"%define FM_BYTES {FM_BYTES}"]
    if offset > 0x9000:
        raise ValueError('tables overlap the background cache directory at CS:9000h')
    return "\n".join(lines) + "\n"


def tables(source: dict, renderer) -> bytes:
    from render import tile_index
    palette = source_palette(source['palette'])
    palette = palette[:16] + palette[31:32] + palette[16:31]   # G1 bank 0, G0 bank 1
    data = {
        "PALETTE": struct.pack('<32H', *palette), "MAPS": source['bgmaps'],
        "BGLOOKUP": source['bglookup'], "SPRLOOKUP": source['spritelookup'],
        "INDEX": b''.join(struct.pack('<H', tile_index(x, y)) for y in range(28) for x in range(36)),
        "ROWS": tile_rows(),
        "EMPTY": bytes(int(not any(renderer.chars[i*64:(i+1)*64])) for i in range(128)),
    }
    out = bytearray()
    for name, size in TABLES:
        value = data.get(name, bytes(size))
        if len(value) != size:
            raise ValueError(f'table {name} has {len(value)} bytes, expected {size}')
        out += value
    return bytes(out)


def staged(source: dict, revision: str, program: bytes) -> bytes:
    """The staged area without FMVOICE.DAT (zeros at FM_SLOT)."""
    from render import Renderer
    if len(program) != PROGRAM_BYTES:
        raise ValueError('program payload has an unexpected size')
    renderer = Renderer(source)
    body = bytearray(tables(source, renderer))
    offsets = []
    for pens in (renderer.chars, renderer.bg, renderer.sprites):
        offsets.append(HEADER.size + len(body))
        body += rle(pens)
    end = HEADER.size + len(body)
    if end > FM_SLOT:
        raise ValueError('staged data overlaps the FMVOICE.DAT slot')
    header = HEADER.pack(HEADER_MAGIC, HEADER_VERSION, HEADER.size, TABLE_BYTES, *offsets, end,
                         int(revision[-1]), 0, zlib.crc32(body), zlib.crc32(program), 0)
    return header + bytes(body) + bytes(STAGE_BYTES - end)


def check_staged(area: bytes, program: bytes | None = None) -> dict:
    (magic, version, size, table, chars, bg, sprites, end, revision, _,
     crc, program_crc, _) = HEADER.unpack_from(area)
    if magic != HEADER_MAGIC or version != HEADER_VERSION or size != HEADER.size:
        raise ValueError('no game data installed')
    if table != TABLE_BYTES or not size + table <= chars < bg < sprites < end <= FM_SLOT:
        raise ValueError('staged header is inconsistent')
    if zlib.crc32(area[size:end]) != crc:
        raise ValueError('staged data CRC-32 mismatch')
    if program is not None and zlib.crc32(program) != program_crc:
        raise ValueError('program payload CRC-32 mismatch')
    return {"revision": f"rev{revision}", "end": end}


def fm_file(voices: bytes, method: int) -> bytes:
    """FMVOICE.DAT: header and the 16 voices (ROM-derived; never distributed)."""
    if method not in FM_METHODS or len(voices) != FM_BYTES:
        raise ValueError('invalid FM voices')
    for i in range(0, FM_BYTES, 9):
        v = voices[i:i + 9]
        if v[0] > 63 or any(v[j] > 15 or v[j + 1] > 127 for j in (1, 3, 5, 7)):
            raise ValueError('invalid FM voice parameters')
    return FM_HEADER.pack(FM_MAGIC, 1, method, WAVES_CRC, FM_BYTES, 0, zlib.crc32(voices)) + voices


def parse_fm_file(data: bytes) -> tuple[int, bytes]:
    magic, version, method, wave, size, _, crc = FM_HEADER.unpack_from(data)
    voices = data[FM_HEADER.size:FM_HEADER.size + FM_BYTES]
    if (magic != FM_MAGIC or version != 1 or method not in FM_METHODS or wave != WAVES_CRC
            or size != FM_BYTES or zlib.crc32(voices) != crc):
        raise ValueError('not a valid FMVOICE.DAT')
    return method, voices
