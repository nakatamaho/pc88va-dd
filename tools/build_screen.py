# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Build the M02 static 32-colour display probe (not the running game).

Without --snapshot this uses a synthetic ruler and needs no ROMs.
With --snapshot it renders a main-memory capture using the user's ROMs.
"""

import argparse
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d88
import roms
from ddpayload import rle, tile_rows, palette_word, source_palette  # noqa: F401 (re-exported)
from render import Renderer, tile_index


def video_state(memory: bytes) -> bytes:
    return (memory[0x8000:0x8400] + memory[0x8b80:0x8c00]
            + memory[0x9380:0x9400] + memory[0x9b80:0x9c00]
            + bytes(x & 1 for x in memory[0xa000:0xa008]))


def state_delta(before: bytes, after: bytes) -> bytes:
    if len(before) != 1416 or len(after) != 1416:
        raise ValueError('video state must be 1416 bytes')
    return b''.join(struct.pack('<HB', i, b) for i, (a, b) in enumerate(zip(before, after)) if a != b) + b'\xff\xff'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--next-snapshot', type=Path, action='append', default=[],
                        help='following native video state; may be repeated (payload size limited)')
    parser.add_argument('--pages', action='store_true', help='copy and cycle through three 70 KiB pages')
    parser.add_argument('--sgp-bench', action='store_true', help='synthetic CPU/SGP sprite benchmark')
    parser.add_argument('--sgp-direction', action='store_true', help='asymmetric SGP traversal/reflection tests')
    parser.add_argument('--native', action='store_true', help='compose the snapshot on the V30, not the host')
    parser.add_argument('--memory-guards', action='store_true', help='snapshot test only: protect future Z80 banks')
    parser.add_argument('--coalesce', action='store_true', help='merge fully dirty packed sprite pieces')
    parser.add_argument('--front-full', action='store_true', help='clear whole reused front by SGP and batch all pieces')
    parser.add_argument('--front-hybrid', action='store_true', help='choose CPU runs or whole-front clearing per update')
    parser.add_argument('--front-threshold', type=int, default=16)
    parser.add_argument('--rect-sprites', action='store_true', help='fronts by rectangle lists (rect_sprites.inc)')
    parser.add_argument('--front-cpu-clear', action='store_true', help='comparison: whole-front clear by CPU instead of SGP')
    parser.add_argument('--cpu-run-clear', action='store_true', help='comparison: merge damaged cells into CPU runs')
    parser.add_argument('--native-planes', action='store_true', help='packed G1 background and alternating G0 fronts')
    parser.add_argument('--native-sgp', action='store_true', help='use retained SGP sprites with the native compositor')
    parser.add_argument('--cache-slots', type=int, help='retained slots (default: 440 for 8bpp, 512 for packed planes)')
    parser.add_argument('--roms', type=Path, default=roms.DEFAULT)
    parser.add_argument('--output', type=Path, default=d88.REPO / 'build/m02screen.d88')
    args = parser.parse_args()
    if args.front_full and args.front_hybrid:
        parser.error('choose --front-full or --front-hybrid')
    if args.front_cpu_clear and not (args.front_full or args.front_hybrid):
        parser.error('--front-cpu-clear requires a whole-front policy')
    if not 1 <= args.front_threshold <= 512:
        parser.error('--front-threshold must be 1..512')
    if (args.coalesce or args.front_full or args.front_hybrid or args.cpu_run_clear) and not args.native_planes:
        parser.error('--coalesce/--front-full require --native-planes')
    if args.native_sgp and args.native_planes:
        parser.error('choose one native backend')
    if args.native_sgp or args.native_planes:
        args.native = True
    capacity_limit = 512 if args.native_planes else 440
    if args.cache_slots is None:
        args.cache_slots = capacity_limit
    if not 1 <= args.cache_slots <= capacity_limit:
        parser.error(f'--cache-slots must be 1..{capacity_limit}')
    code_bytes = 13312 if (args.native_planes or args.native_sgp) else 4096
    if (args.sgp_bench or args.sgp_direction) and (args.native or args.pages or args.snapshot):
        parser.error('SGP tests are standalone synthetic tests')
    if args.sgp_bench and args.sgp_direction:
        parser.error('choose one SGP test')
    if args.next_snapshot and not args.native:
        parser.error('--next-snapshot requires --native')
    if args.native and (not args.snapshot or args.pages):
        parser.error('--native requires --snapshot and cannot be combined with --pages')
    if args.snapshot:
        source = roms.load(args.roms)
        renderer = Renderer(source)
        memory = args.snapshot.read_bytes()
        picture = renderer.render(memory)
        palette = source_palette(source['palette'])
        if args.native_planes:
            palette = palette[:16] + palette[31:32] + palette[16:31]
        pixels = b''.join(bytes(16) + picture[y*288:(y+1)*288] + bytes(16) for y in range(224))
    else:
        palette = [palette_word((i & 3) * 85, ((i >> 2) & 3) * 85, (i >> 4) * 255) for i in range(32)]
        if args.sgp_bench:
            palette[16] = 0       # opaque black must not act as source-zero transparency
        pixels = bytearray(320 * 224)
        for y in range(224):
            for x in range(320):
                pen = x // 10
                if x in (0, 319) or y in (0, 223):
                    pen = 31
                elif y % 8 == 0 and x < (16 if y % 32 == 0 else 8):
                    pen = 31
                pixels[y * 320 + x] = pen
        pixels = bytes(pixels)
    packed = rle(pixels)
    data = bytearray(struct.pack('<32H', *palette))
    include = ''
    defines = ['PAGE_TEST=1'] if args.pages else []
    if args.sgp_bench:
        defines = ['SGP_BENCH=1']
    if args.sgp_direction:
        defines = ['SGP_DIRECTION=1']
    if args.native:
        defines = ['NATIVE_RENDER=1']
        if args.memory_guards:
            defines += ['VIDEO_GUARDS=1']
        if args.coalesce:
            defines += ['SPRITE_COALESCE=1']
        if args.front_full:
            defines += ['FRONT_FULL=1']
        if args.front_cpu_clear:
            defines += ['FRONT_CPU_CLEAR=1']
        if args.front_hybrid:
            defines += ['FRONT_HYBRID=1', f'FRONT_THRESHOLD={args.front_threshold}']
        if args.cpu_run_clear:
            defines += ['CPU_RUN_CLEAR=1']
        if args.rect_sprites:
            defines += ['RECT_SPRITES=1']
        if args.native_planes:
            defines += ['NATIVE_PLANES=1', f'CODE_BYTES={code_bytes}', f'KEEP_CAPACITY={args.cache_slots}']
        if args.native_sgp:
            defines += ['NATIVE_SGP=1', f'CODE_BYTES={code_bytes}', f'KEEP_CAPACITY={args.cache_slots}']
        assets = {
            'CHARS': rle(renderer.chars), 'BG': rle(renderer.bg),
            'SPRITES': rle(renderer.sprites), 'MAPS': source['bgmaps'],
            'BGLOOKUP': source['bglookup'], 'SPRLOOKUP': source['spritelookup'],
            'VRAM': memory[0x8000:0x8400], 'OBJECT': memory[0x8b80:0x8c00],
            'POSITION': memory[0x9380:0x9400], 'FLIP': memory[0x9b80:0x9c00],
            'LATCH': bytes(x & 1 for x in memory[0xa000:0xa008]),
            'INDEX': b''.join(struct.pack('<H', tile_index(x, y)) for y in range(28) for x in range(36)),
            'ROWS': tile_rows(),
        }
        next_pictures = []
        if args.next_snapshot:
            assets['NEXT'] = b''
            previous = video_state(memory)
            for path in args.next_snapshot:
                following = path.read_bytes()
                next_pictures.append(renderer.render(following))  # validate before assembly
                current = video_state(following)
                assets['NEXT'] += state_delta(previous, current)
                previous = current
            defines += ['NEXT_STATE=1', 'NEXT_DELTA=1', f'NEXT_COUNT={len(args.next_snapshot)}']
        for name, asset in assets.items():
            include += f'%define N_{name} {code_bytes + len(data)}\n'
            data.extend(asset)
    else:
        data.extend(packed)
    sectors = d88.build_boot_disk(d88.REPO / 'src/m02/screen.asm', include, bytes(data),
                                 args.output, 'DDM02SCREEN', code_bytes, defines,
                                 listing=args.output.with_suffix('.lst'))
    # The expected framebuffer is private test output, not a shipped asset.
    args.output.with_suffix('.expected').write_bytes(pixels)
    if args.next_snapshot:
        for i, picture in enumerate(next_pictures, 1):
            next_pixels = b''.join(bytes(16) + picture[y*288:(y+1)*288] + bytes(16) for y in range(224))
            suffix = '.next.expected' if i == 1 else f'.next{i}.expected'
            args.output.with_suffix(suffix).write_bytes(next_pixels)
    mode = 'packed 4bpp dual-screen' if args.native_planes else 'indexed 8bpp'
    print(f'{args.output}: static 320x224 {mode}; {len(data)} asset bytes, {sectors} sectors')


if __name__ == '__main__':
    main()
