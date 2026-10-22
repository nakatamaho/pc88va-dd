# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Build the SGP benchmark disk: MS-DOS 4.0 with SGPBENCH.COM (no ROM data).

    python3 -I tools/build_sgpbench.py [--output build/sgpbench.d88]

The disk starts SGPBENCH from AUTOEXEC.BAT; see docs/SGP-HW-BENCH.md.
"""

import argparse
import hashlib
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d88  # noqa: E402
import dosdisk  # noqa: E402
import sgpbench  # noqa: E402

AUTOEXEC = b'@ECHO OFF\r\nPATH A:\\\r\nVER\r\nSGPBENCH\r\n'


def assemble(listing: Path) -> bytes:
    with tempfile.TemporaryDirectory(prefix='dd-sgpbench-') as tmp:
        work = Path(tmp)
        (work / 'bench_data.inc').write_text(sgpbench.include())
        d88.nasm([f'-I{work}/', '-l', str(listing), '-o', str(work / 'SGPBENCH.COM'),
                  str(d88.REPO / 'src/bench/sgpbench.asm')])
        program = (work / 'SGPBENCH.COM').read_bytes()
    if len(program) + 0x100 > 0xf000:
        raise SystemExit('error: SGPBENCH.COM reaches its stack')
    return program


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--output', type=Path, default=d88.REPO / 'build/sgpbench.d88')
    parser.add_argument('--msdos4', type=Path, default=dosdisk.MSDOS4_DEFAULT)
    args = parser.parse_args()
    listing = args.output.with_suffix('.lst')
    listing.parent.mkdir(parents=True, exist_ok=True)
    program = assemble(listing)
    dosdisk.make_disk({'AUTOEXEC.BAT': AUTOEXEC, 'SGPBENCH.COM': program}, args.output, args.msdos4)
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(f'{args.output}: MS-DOS 4.0 with SGPBENCH.COM ({len(program)} bytes); SHA-256 {digest}')


if __name__ == '__main__':
    main()
