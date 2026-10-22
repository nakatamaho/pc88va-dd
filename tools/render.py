# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Host reference composition in board raster orientation (288x224).

Input is a 64 KiB main address-space snapshot, including video latches.
Output holds palette indices 0..31, not RGB. No target colour reduction.
"""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gfx

WIDTH, HEIGHT = 288, 224


def tile_index(col: int, row: int) -> int:
    row += 2
    col -= 2
    return row + ((col & 31) << 5) if col & 32 else col + (row << 5)


class Renderer:
    def __init__(self, roms: dict[str, bytes]):
        self.chars = gfx.characters(roms['chars'])
        self.bg = gfx.background(roms['bgtiles'])
        self.sprites = gfx.sprites(b''.join(roms[f'sprites{i}'] for i in range(1, 5)))
        self.maps = roms['bgmaps']
        self.bglookup = roms['bglookup']
        self.sprlookup = roms['spritelookup']

    def render(self, memory: bytes) -> bytes:
        if len(memory) != 65536:
            raise ValueError('expected a 64 KiB main address-space snapshot')
        if memory[0xa007] & 1:
            raise ValueError('flipped-screen composition is not implemented yet')
        latch = [memory[0xa000 + i] & 1 for i in range(6)]
        page = latch[0] | latch[1] << 1
        bank = latch[4] << 4 | latch[5] << 5
        out = bytearray(WIDTH * HEIGHT)
        for row in range(28):
            for col in range(36):
                index = tile_index(col, row)
                bgcode = self.maps[page * 1024 + index]
                bgcolour = (15 if latch[3] else bgcode >> 4) | bank
                char = memory[0x8000 + index]
                fgcolour = char & 15 if latch[2] else ((char >> 4) & 14) | ((char >> 3) & 2)
                for y in range(8):
                    dest = (row * 8 + y) * WIDTH + col * 8
                    for x in range(8):
                        pixel = y * 8 + x
                        pen = self.bg[bgcode * 64 + pixel]
                        colour = self.bglookup[bgcolour * 4 + pen] & 15
                        # Bit 7 selects colour, not the normal-screen glyph.
                        if self.chars[(char & 127) * 64 + pixel]:
                            colour = fgcolour
                        out[dest + x] = colour
        for off in range(0, 128, 2):
            code = memory[0x8b80 + off]
            colour = memory[0x8b81 + off] & 63
            sx = memory[0x9381 + off] - 39
            size = code >> 7
            sy = ((257 - memory[0x9380 + off] - 16 * size) & 255) - 32
            flip = memory[0x9b80 + off]
            fx, fy = flip & 1, (flip >> 1) & 1
            if size:
                code = (code & 192) | ((code & 63) << 2)
            for ty in range(size + 1):
                for tx in range(size + 1):
                    tile = (code + (ty ^ (size * fy)) * 2 + (tx ^ (size * fx))) & 255
                    xbase = (sx + tx * 16) & 255
                    for wrap in (0, 256):
                        for y in range(16):
                            dy = sy + ty * 16 + y
                            if not 0 <= dy < HEIGHT:
                                continue
                            source_y = 15 - y if fy else y
                            for x in range(16):
                                dx = xbase + wrap + x
                                if not 16 <= dx < 272:
                                    continue
                                source_x = 15 - x if fx else x
                                pen = self.sprites[tile * 256 + source_y * 16 + source_x]
                                pal = 16 | (self.sprlookup[colour * 4 + pen] & 15)
                                if pal != 31:
                                    out[dy * WIDTH + dx] = pal
        return bytes(out)


def main():
    import roms
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--roms', type=Path, default=roms.DEFAULT)
    args = parser.parse_args()
    source = roms.load(args.roms)
    pixels = Renderer(source).render(args.snapshot.read_bytes())
    out = Path(__file__).resolve().parents[1] / 'build' / 'gfx'
    out.mkdir(parents=True, exist_ok=True)
    # This PGM visualizes indices only; it is not a colour screenshot.
    (out / 'frame.pgm').write_bytes(b'P5\n288 224\n31\n' + pixels)
    (out / 'frame.indices').write_bytes(pixels)
    print(f'{out}/frame.indices: {len(set(pixels))} palette indices used')


if __name__ == '__main__':
    main()
