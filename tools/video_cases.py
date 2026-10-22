# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Create deterministic video-state cases from a user's private snapshot.

Outputs contain captured state and are kept under ignored build/. Use each
pair with check_native.py --next-snapshot, in both directions. No ROM assets
are embedded here; geometry and synthetic register values are test inputs.
"""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import tile_index


def cases(source: bytes) -> dict[str, bytes]:
    if len(source) != 65536:
        raise ValueError('expected a 64 KiB snapshot')
    result = {'base': source}
    memory = bytearray(source)
    memory[0x8000 + tile_index(4, 10)] ^= 17
    result['tile'] = bytes(memory)
    memory = bytearray(source)
    memory[0xa004] ^= 1
    result['latch'] = bytes(memory)
    memory = bytearray(source)
    memory[0x9381] = (memory[0x9381] + 8) & 255
    result['sprite'] = bytes(memory)

    # Most unused entries are outside the vertical viewport (Y register 0).
    base = bytearray(source)
    for start in (0x8b80, 0x9380, 0x9b80):
        base[start:start + 128] = bytes(128)

    def entry(memory, i, x, y, code, flip, colour=0):
        off = i * 2
        memory[0x8b80 + off] = code
        memory[0x8b81 + off] = colour
        memory[0x9381 + off] = (x + 39) & 255
        memory[0x9380 + off] = (257 - y - 32 - 16 * (code >> 7)) & 255
        memory[0x9b80 + off] = flip

    placements = [(1, -15, 0, 0), (15, 0, 1, 1), (16, 208, 2, 2),
                  (-1, 223, 3, 3), (208, 80, 128, 0), (100, 80, 128, 1),
                  (144, 144, 128, 2), (32, 144, 128, 3), (104, 84, 0, 0)]
    for i, placement in enumerate(placements):
        entry(base, i, *placement)
    result['edges'] = bytes(base)
    moved = bytearray(base)
    for i, (x, y, code, flip) in enumerate(placements):
        entry(moved, i, x + 9, y - 7, code ^ 128, flip ^ 3, (i + 1) % 6)
    # Disappearance, appearance and wrap across the 256-dot boundary.
    entry(moved, 1, 15, -32, 1, 0)
    entry(moved, 9, -8, 112, 128, 1)
    result['moved'] = bytes(moved)
    overlap = bytearray(base)
    for x, y, _, _ in placements:
        if 16 <= x + 8 < 272 and 0 <= y + 8 < 224:
            overlap[0x8000 + tile_index((x + 8) // 8, (y + 8) // 8)] ^= 17
    result['overlap'] = bytes(overlap)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    args = parser.parse_args()
    out = Path(__file__).resolve().parents[1] / 'build' / 'video-cases'
    out.mkdir(parents=True, exist_ok=True)
    for name, memory in cases(args.snapshot.read_bytes()).items():
        path = out / f'{name}.memory'
        path.write_bytes(memory)
        print(path)


if __name__ == '__main__':
    main()
