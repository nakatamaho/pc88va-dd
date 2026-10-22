# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Decode graphics into row-major source pens, without colour reduction.

Generated data belongs in build/ only and must never be distributed.
Layout bit offsets count from the most significant bit of each byte;
the first listed plane supplies the most significant output bit.
"""

import argparse
from pathlib import Path
import sys


def decode(data: bytes, xoffs: tuple, yoffs: tuple,
           planes: tuple, stride: int) -> bytes:
    """Decode every complete character; offsets and stride are in bits."""
    if not data or stride <= 0 or len(data) * 8 % stride:
        raise ValueError("graphics size must be a nonzero multiple of stride")
    if not xoffs or not yoffs or not planes:
        raise ValueError("empty layout")
    if min(xoffs + yoffs + planes) < 0:
        raise ValueError("negative layout offset")
    if max(xoffs) + max(yoffs) + max(planes) >= stride:
        raise ValueError("layout exceeds character stride")
    out = bytearray()
    for base in range(0, len(data) * 8, stride):
        for y in yoffs:
            for x in xoffs:
                pen = 0
                for plane in planes:
                    bit = base + y + x + plane
                    pen = (pen << 1) | ((data[bit // 8] >> (7 - bit % 8)) & 1)
                out.append(pen)
    return bytes(out)


def characters(data: bytes) -> bytes:
    return decode(data, tuple(range(7, -1, -1)),
                  tuple(range(0, 64, 8)), (0,), 64)


def background(data: bytes) -> bytes:
    return decode(data, (64, 65, 66, 67, 0, 1, 2, 3),
                  tuple(range(0, 64, 8)), (0, 4), 128)


def sprites(data: bytes) -> bytes:
    return decode(data, tuple(group * 64 + x for group in range(4) for x in range(4)),
                  tuple(group * 256 + y * 8 for group in range(2) for y in range(8)),
                  (0, 4), 512)


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import roms
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roms', type=Path, default=roms.DEFAULT)
    args = parser.parse_args()
    roles = ('chars', 'bgtiles', 'sprites1', 'sprites2', 'sprites3', 'sprites4')
    source = roms.load(args.roms, roles)
    out = Path(__file__).resolve().parents[1] / 'build' / 'gfx'
    out.mkdir(parents=True, exist_ok=True)
    images = {
        'chars.pens': characters(source['chars']),
        'bgtiles.pens': background(source['bgtiles']),
        'sprites.pens': sprites(b''.join(source[f'sprites{i}'] for i in range(1, 5))),
    }
    for name, data in images.items():
        (out / name).write_bytes(data)
        print(f'{name}: {len(data)} bytes')


if __name__ == '__main__':
    main()
