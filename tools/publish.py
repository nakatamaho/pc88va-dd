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

"""Make the public repository: one commit holding a snapshot of this one.

This repository is private and keeps the whole history. The public one,
in a directory of its own, gets a single commit with the files of REF
(default HEAD) as they are tracked here, and nothing else. Before writing
anything the snapshot is checked:

- the working tree is clean;
- no file holds 8 consecutive bytes of a ROM (--roms; windows of a single
  repeated byte are not counted);
- no file name or content holds a word of --names, a file kept outside
  the repository with one forbidden word or phrase a line (the arcade
  game's, its characters' and its makers' names), matched without regard
  to case.

    python3 -I tools/publish.py --dest DIR --names FILE [--roms PATH]
                                [--ref REF] [--message TEXT] [--replace]

DIR must not exist, or with --replace be an earlier result of this tool,
whose history is then replaced by the new single commit. Nothing is
pushed.
"""

import argparse
import io
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roms  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
MARK = "publish-snapshot"      # in .git: identifies a directory made by this tool
WINDOW = 8


def git(*args, cwd=REPO, **kw) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, **kw).stdout


def snapshot(ref: str) -> dict[str, tuple[bytes, int]]:
    """Path -> (contents, mode) of the files of REF."""
    data = subprocess.run(["git", "archive", "--format=tar", ref], cwd=REPO,
                          check=True, capture_output=True).stdout
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar.getmembers():
            if member.isfile():
                files[member.name] = (tar.extractfile(member).read(), member.mode)
    return files


def rom_windows(source: Path) -> set[bytes]:
    """The 8-byte windows of every file of up to 4 KiB in SOURCE and of
    the ROMs found in it. A DLL holding ROMs counts only by those ROMs,
    not by the rest of its contents."""
    pieces = [data for data in roms._files(source) if len(data) <= 4096]
    pieces += roms._find(source, roms.ROMS).values()
    for table in roms.REVISIONS.values():
        pieces += roms._find(source, table).values()
    windows = set()
    for data in pieces:
        for i in range(len(data) - WINDOW + 1):
            w = data[i:i + WINDOW]
            if w.count(w[0]) != WINDOW:
                windows.add(w)
    return windows


def check(files, windows: set[bytes], names: list[str]) -> list[str]:
    problems = []
    for path, (content, _) in sorted(files.items()):
        lowered_path = path.lower()
        for name in names:
            if name in lowered_path:
                problems.append(f"{path}: file name holds a forbidden word")
        text = content.decode("latin-1").lower()
        for name in names:
            if name in text:
                problems.append(f"{path}: holds a forbidden word")
        for i in range(len(content) - WINDOW + 1):
            if content[i:i + WINDOW] in windows:
                problems.append(f"{path}: holds ROM bytes at offset {i}")
                break
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--names", type=Path, required=True,
                        help="forbidden words, one a line (kept outside the repository)")
    parser.add_argument("--roms", type=Path, default=roms.DEFAULT,
                        help="zip or directory with the ROM files (default: $DD_ROMS)")
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--message", default="The Game DD: a PC-88VA port of an arcade game")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    dest = args.dest.resolve()
    if dest == REPO or REPO in dest.parents:
        sys.exit("error: --dest must be outside this repository")
    if git("status", "--porcelain"):
        sys.exit("error: the working tree is not clean")
    if args.roms is None:
        sys.exit("error: no ROM source for the check: give --roms PATH or set DD_ROMS")
    names = [line.strip().lower() for line in args.names.read_text().splitlines()
             if line.strip() and not line.startswith("#")]
    if not names:
        sys.exit("error: --names lists no words")
    if dest.exists():
        if not args.replace or not (dest / ".git" / MARK).exists():
            sys.exit(f"error: {dest} exists (use --replace on an earlier result)")

    files = snapshot(args.ref)
    problems = check(files, rom_windows(args.roms), names)
    if problems:
        print("\n".join(problems))
        sys.exit("error: the snapshot is not publishable")

    source = git("rev-parse", "--short", args.ref).strip()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for path, (content, mode) in files.items():
        out = dest / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
        out.chmod(mode & 0o777)
    git("init", "-q", "-b", "main", cwd=dest)
    git("add", "-A", cwd=dest)
    git("commit", "-q", "-m", args.message, cwd=dest)
    (dest / ".git" / MARK).write_text(f"snapshot of private {source}\n")
    print(f"{dest}: one commit with {len(files)} files from {args.ref} ({source}); "
          "checked for ROM bytes and forbidden words; not pushed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
