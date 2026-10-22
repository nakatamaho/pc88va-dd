# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Build the sprite benchmark disk: MS-DOS 4.0 with SPRBENCH.COM (no ROM data).

    python3 -I tools/build_sprbench.py [--output build/sprbench.d88]

The disk starts SPRBENCH from AUTOEXEC.BAT; see docs/SPRITE-BENCH.md.
"""

import argparse
import hashlib
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d88  # noqa: E402
import dosdisk  # noqa: E402
import sprbench  # noqa: E402

AUTOEXEC = b'@ECHO OFF\r\nPATH A:\\\r\nVER\r\nSPRBENCH\r\n'


def assemble(listing: Path) -> bytes:
    with tempfile.TemporaryDirectory(prefix='dd-sprbench-') as tmp:
        work = Path(tmp)
        (work / 'bench_data.inc').write_text(sprbench.include())
        d88.nasm([f'-I{work}/', '-l', str(listing), '-o', str(work / 'SPRBENCH.COM'),
                  str(d88.REPO / 'src/bench/sprbench.asm')])
        program = (work / 'SPRBENCH.COM').read_bytes()
    if len(program) + 0x100 > 0xf000:
        raise SystemExit('error: SPRBENCH.COM reaches its stack')
    return program


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--output', type=Path, default=d88.REPO / 'build/sprbench.d88')
    parser.add_argument('--msdos4', type=Path, default=dosdisk.MSDOS4_DEFAULT)
    args = parser.parse_args()
    listing = args.output.with_suffix('.lst')
    listing.parent.mkdir(parents=True, exist_ok=True)
    program = assemble(listing)
    dosdisk.make_disk({'AUTOEXEC.BAT': AUTOEXEC, 'SPRBENCH.COM': program}, args.output, args.msdos4)
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(f'{args.output}: MS-DOS 4.0 with SPRBENCH.COM ({len(program)} bytes); SHA-256 {digest}')


if __name__ == '__main__':
    main()
