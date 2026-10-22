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

"""Check the relocated sub program against the original in MAME.

Runs the arcade board in MAME twice with the same inputs: once as it is,
once with the sub CPU reading tools/patches.py's relocated program at
4000h-5FFFh and the main program at 0000h-3FFFh (as on the PC-88VA),
reset and interrupt entries redirected to 4000h and 4038h. Only the
relocation and the checksum compensation are applied; the yield patches
need the uPD9002. Any address the relocation missed reads the main
program instead and changes the run. Compares tile RAM and the sprite
registers frame by frame. The redirected entries cost a few cycles, so a
screen update can straddle a frame's end differently: a single differing
frame whose neighbours agree is reported as timing, anything else fails.

    python3 -I tools/check_sub.py --mame PATH --system NAME --rompath DIR
                                  [--frames N] [--saved-earom]

NAME is MAME's name of the ROM set of the revision found in --roms
(tools/roms.py; for rev1 the clone set); DIR holds it, its parent and the
custom I/O chips' ROM sets. The view file (ROM-derived) and the run logs
go to build/mame/, which git ignores.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import patches  # noqa: E402
import roms  # noqa: E402
import z80  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def sub_view(revision: str, main: bytes, sub: bytes) -> bytes:
    rev = patches.REVISIONS[revision]
    relocated = bytearray(patches.relocate_sub(rev, sub, main))
    covered = patches._covered(z80.trace(sub, patches.sub_entries(rev, sub)))
    for b in range(2):
        f = patches._filler(sub, b * 0x1000, covered, avoid=range(0x1FFE, 0x2000))
        relocated[f] = (relocated[f] + sub[0x1FFE + b]
                        - patches._block_sums(relocated)[b]) & 0xFF
    view = bytearray(main)
    view[0x0000:0x0006] = bytes((0xF3, 0xED, 0x56, 0xC3)) + (patches.SUB_BASE + 0x68).to_bytes(2, "little")
    view[0x0038:0x003B] = b"\xC3" + (patches.SUB_BASE + 0x38).to_bytes(2, "little")
    return bytes(view) + bytes(relocated)


def run(args, out: Path, view: Path | None, nvram: Path | None = None,
        keep: Path | None = None) -> list[str]:
    """One run with default settings, from an empty EAROM (MAME's NVRAM)
    or from a copy of NVRAM; KEEP receives the NVRAM saved at the end."""
    env = dict(os.environ, DD_OUT=str(out), DD_FRAMES=str(args.frames),
               DD_VIEW=str(view) if view else "")
    with tempfile.TemporaryDirectory(prefix="dd-mame-") as tmp:
        if nvram is not None:
            shutil.copytree(nvram, tmp, dirs_exist_ok=True)
        subprocess.run([args.mame, args.system, "-rompath", str(args.rompath),
                        "-nvram_directory", tmp, "-cfg_directory", tmp,
                        "-video", "none", "-sound", "none", "-nothrottle", "-skip_gameinfo",
                        "-autoboot_script", str(REPO / "tools/mame/sub_check.lua")],
                       env=env, check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        if keep is not None:
            shutil.copytree(tmp, keep, dirs_exist_ok=True)
    return out.read_text().splitlines()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--roms", type=Path, default=roms.DEFAULT,
                        help="zip or directory with the ROM files (default: $DD_ROMS)")
    parser.add_argument("--mame", required=True, help="MAME executable")
    parser.add_argument("--system", required=True, help="MAME's name of the ROM set")
    parser.add_argument("--rompath", type=Path, required=True, help="MAME's ROM path")
    parser.add_argument("--frames", type=int, default=6000)
    parser.add_argument("--saved-earom", action="store_true",
                        help="start both runs from the EAROM saved by a first run")
    args = parser.parse_args()

    revision, main_, sub, _ = roms.programs(args.roms)
    work = REPO / "build/mame"
    work.mkdir(parents=True, exist_ok=True)
    view = work / "subview.bin"
    view.write_bytes(sub_view(revision, main_, sub))
    nvram = None
    if args.saved_earom:
        nvram = work / "nvram"
        shutil.rmtree(nvram, ignore_errors=True)
        run(args, work / "first.txt", None, keep=nvram)
    original = run(args, work / "original.txt", None, nvram)
    relocated = run(args, work / "relocated.txt", view, nvram)
    if len(original) != args.frames or len(relocated) != args.frames:
        sys.exit("error: a run ended early")
    same = [a.split()[1:3] == b.split()[1:3] for a, b in zip(original, relocated)]
    timing = [i + 1 for i in range(1, len(same) - 1)
              if not same[i] and same[i - 1] and same[i + 1]]
    differ = [i + 1 for i in range(len(same)) if not same[i] and i + 1 not in timing]
    in_sub = sum(1 for line in relocated
                 if patches.SUB_BASE <= int(line.split()[3], 16) < patches.SUB_BASE + 0x2000)
    print(f"{revision}, {args.frames} frames; sub PC in the relocated program at {in_sub} "
          f"frame ends; single frames differing by timing: {len(timing)}"
          + (f" ({' '.join(map(str, timing[:8]))})" if timing else "")
          + f"; other differing frames: {len(differ)}"
          + (f" (first {differ[0]})" if differ else ""))
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main())
