# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""ROM-free test of background G1 plus alternating transparent G0 pages.

Check all three GVRAM images AND the final rendered RGB mixer output.
No scheduler, sprite cache, or damage renderer is involved in this probe.
"""

import argparse
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from PIL import Image
import d88
from build_screen import palette_word, rle, source_palette
from render import Renderer
import roms
from check_pages import address, registers


def fixture():
    colours = [((i & 3)*85, ((i >> 2) & 3)*85, (i >> 4)*255) for i in range(32)]
    colours[0], colours[17] = (17,34,51), (0,0,0)
    background = bytes(((x//10)+(y//16)) & 15 for y in range(224) for x in range(320))
    fronts = []
    for shift in (0, 19):
        pixels = bytearray(71680)
        for y in range(17,224):
            for x in range(33+shift,288+shift):
                pixels[y*320+x] = ((x-shift)//8+7*(y//8)) & 15
        fronts.append(bytes(pixels))
    return colours, background, fronts


def compose(background, foreground, transparent=True):
    if len(background) != len(foreground):
        raise ValueError('plane sizes differ')
    return bytes(b if transparent and f == 0 else 16+f for b,f in zip(background, foreground))


def packed(pixels):
    if len(pixels) % 2 or any(p > 15 for p in pixels):
        raise ValueError('packed pixels must be pairs of 4-bit indices')
    return bytes((a << 4) | b for a,b in zip(pixels[::2], pixels[1::2]))


def material_fixture(source, first, second):
    renderer = Renderer(source)
    backgrounds, fronts = [], []
    for memory in (first, second):
        full = renderer.render(memory)
        bare = bytearray(memory)
        bare[0x8b80:0x8c00] = bytes(128)
        bare[0x9380:0x9400] = bytes(128)
        bg = renderer.render(bytes(bare))
        def pad(pixels):
            return bytearray(b''.join(bytes(16)+pixels[y*288:(y+1)*288]+bytes(16) for y in range(224)))
        background = pad(bg)
        foreground = pad(bytes(p-15 if p >= 16 else 0 for p in full))
        # Palette control pixels in the otherwise unused left margin.
        for i in range(16):
            background[i*320] = foreground[i*320] = i
        backgrounds.append(bytes(background))
        fronts.append(bytes(foreground))
    if backgrounds[0] != backgrounds[1]:
        raise ValueError('static two-plane probe requires matching backgrounds')
    original = source_palette(source['palette'])
    words = original[:16] + original[31:32] + original[16:31]
    colours = [(((w >> 6)&15)*17, ((w >> 12)&15)*17, ((w >> 1)&15)*17) for w in words]
    return colours, backgrounds[0], fronts


def find_image(screen, expected):
    """Require the entire 320x224 raster; permit only integer display scaling."""
    screen = screen.convert('RGB')
    for sx, sy in ((2,2), (2,1), (1,1)):
        enlarged = expected.resize((320*sx,224*sy), Image.Resampling.NEAREST)
        w,h = enlarged.size
        if w > screen.width or h > screen.height:
            continue
        wanted = enlarged.tobytes()
        first_row = wanted[:w*3]
        for y in range(screen.height-h+1):
            for x in range(screen.width-w+1):
                if screen.crop((x,y,x+w,y+1)).tobytes() != first_row:
                    continue
                if screen.crop((x,y,x+w,y+h)).tobytes() == wanted:
                    return x,y,sx,sy
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vaeg', type=Path, required=True)
    parser.add_argument('--bios', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--next-snapshot', type=Path)
    parser.add_argument('--roms', type=Path, default=roms.DEFAULT)
    args = parser.parse_args()
    if bool(args.snapshot) != bool(args.next_snapshot):
        parser.error('supply both --snapshot and --next-snapshot')
    root = d88.REPO / 'build/two-planes'
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    if args.snapshot:
        colours, background, fronts = material_fixture(roms.load(args.roms), args.snapshot.read_bytes(), args.next_snapshot.read_bytes())
    else:
        colours, background, fronts = fixture()
    data = bytearray(struct.pack('<32H', *(palette_word(*c) for c in colours)) + rle(packed(fronts[0])))
    front = 4096 + len(data)
    data.extend(rle(packed(fronts[1])))
    back = 4096 + len(data)
    data.extend(rle(packed(background)))
    disk = out / 'two-planes.d88'
    d88.build_boot_disk(d88.REPO / 'src/m02/screen.asm',
                        f'%define T_FRONT_B {front}\n%define T_BACKGROUND {back}\n', bytes(data), disk,
                        'DDM02PLANES', 4096, ['TWO_PLANES=1'], listing=disk.with_suffix('.lst'))
    shown = address(disk.with_suffix('.lst').read_text(), 'two_shown')
    script = 'debug-script 1\nlimit-frame 1000\n'
    phases = (0,1,2,3,4,3,4)
    for i in range(len(phases)):
        script += f'wait-pc {shown} 1\ncapture phase{i} registers gvram screen\n'
    (out / 'run.debug').write_text(script+'exit\n')
    (out / 'va.cfg').write_text('[NekoProjectII]\nMonitor15kHz=true\nMonitor15kHzFill=true\nGUI_scale=2\nGUI_win_cx=640\nGUI_win_cy=470\n')
    with (out / 'vaeg.log').open('w') as log:
        subprocess.run([str(args.vaeg.resolve()), '--cfg', str(out / 'va.cfg'),
                        '--no-bkupmem', '--nowait', '--frameskip', 'full', '--effect', 'unfiltered', '--scaling', 'native', '--mute', '--roms', str(args.bios.resolve()),
                        '--fdd1', str(disk), '--debug-script', str(out / 'run.debug'),
                        '--debug-output-dir', str(out)],
                       env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'),
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    # Calibrate RGB from opaque control phases, avoiding assumptions about
    # DAC expansion and SDL quantization. Require 32 distinct near-target colours.
    controls = [Image.open(out / f'phase{i}.screen.bmp').convert('RGB') for i in (1,2)]
    samples = []
    for index in range(32):
        pixels = background if index < 16 else fronts[0]
        pos = pixels.index(index & 15)
        x,y = pos % 320, pos // 320
        colour = controls[index // 16].getpixel((x*2+1,y*2+23))
        if max(abs(a-b) for a,b in zip(colour,colours[index])) > 20:
            sys.exit(f'palette control mismatch at {index}: {colour}; {out}')
        samples.append(colour)
    if not args.snapshot and len(set(samples)) != 32:
        sys.exit(f'palette banks alias: {out}')
    palette = [v for c in samples for v in c] + [0]*672
    expected = [compose(background, fronts[0]), background, compose(background, fronts[0], False),
                compose(background, fronts[1]), compose(background, fronts[0])]
    placements = []
    for i, phase in enumerate(phases):
        indices = expected[phase]
        state = registers(out / f'phase{i}.registers.tsv')
        if int(state['ax'],16) != phase:
            sys.exit(f'nonconsecutive phase: {out}')
        raw = (out / f'phase{i}.gvram.bin').read_bytes()
        if (len(raw) != 262144 or raw[:35840] != packed(fronts[0])
                or raw[35840:71680] != packed(fronts[1])
                or raw[0x20000:0x28c00] != packed(background)):
            sys.exit(f'GVRAM mismatch, phase {i}: {out}')
        image = Image.frombytes('P', (320,224), indices)
        image.putpalette(palette)
        image = image.convert('RGB')
        image.save(out / f'expected{i}.png')
        screen = Image.open(out / f'phase{i}.screen.bmp')
        placement = find_image(screen, image)
        if placement is None:
            sys.exit(f'Final RGB mismatch, phase {i}, screen {screen.size}: {out}')
        placements.append(placement)
    if len(set(placements)) != 1:
        sys.exit(f'unstable raster placement: {placements}')
    report = f'All seven RGB captures and all three GVRAM pages match. Raster placement: {placements[0]}\n'
    (out / 'result.txt').write_text(report)
    print(report+str(out))


if __name__ == '__main__':
    main()
