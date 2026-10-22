# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Replay first-use sprite states through native composition without eviction.

The background is frozen from a supplied snapshot. Sprite RAM comes from
the every-frame compact trace; states introducing no new keys are skipped.
This is a synthetic integration test, not a scheduler/game execution test.
"""

import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trace_cache import records, RECORD_BYTES, REPO


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('background', type=Path)
    parser.add_argument('--planes', action='store_true', help='packed two-screen backend')
    parser.add_argument('--vaeg', required=True, type=Path)
    parser.add_argument('--bios', required=True, type=Path)
    args = parser.parse_args()
    data = args.trace.read_bytes()
    base = args.background.read_bytes()
    if len(base) != 65536:
        parser.error('background snapshot must be 64 KiB')
    root = REPO / 'build/retained-native'
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    keys, paths = set(), []
    most_visible = -1
    warmest = None
    for i, (frame, pieces) in enumerate(records(data)):
        current = {(a,b,c) for a,b,c,d in pieces}
        added = current - keys
        keys.update(current)
        if not added and frame != 1 and (i+1)*RECORD_BYTES != len(data):
            continue
        memory = bytearray(base)
        record = data[i*RECORD_BYTES:(i+1)*RECORD_BYTES]
        for j, address in enumerate((0x8b80, 0x9380, 0x9b80)):
            memory[address:address+128] = record[4+j*128:4+(j+1)*128]
        memory[0xa007] = record[-1]
        if len(pieces) > most_visible:
            most_visible, warmest = len(pieces), bytes(memory)
        path = out / f'{frame:06}.memory'
        path.write_bytes(memory)
        paths.append(path)
    capacity = 512 if args.planes else 440
    if not paths or len(keys) > capacity:
        sys.exit(f'requires a nonempty trace fitting {capacity} retained slots')
    # Return to the most visible state and change the background bank. The
    # packed backend may reuse an already valid front; 8bpp redraws it.
    memory = bytearray(warmest)
    memory[0xa000] ^= 1
    final = out / 'warm.memory'
    final.write_bytes(memory)
    paths.append(final)
    command = [sys.executable, '-I', str(REPO / 'tools/check_native.py'), '--planes' if args.planes else '--sgp',
               '--vaeg', str(args.vaeg.resolve()), '--bios', str(args.bios.resolve()), str(paths[0])]
    for path in paths[1:]:
        command += ['--next-snapshot', str(path)]
    with (out / 'check.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
    text = (out / 'check.log').read_text()
    states = re.findall(r'Cache: hits=(\d+), misses=(\d+), fallbacks=(\d+), resident=(\d+)', text)
    if (len(states) != len(paths) or int(states[-1][3]) != len(keys)
            or any(int(s[2]) for s in states) or int(states[-1][1]) or not int(states[-1][0])):
        sys.exit(f'cache counts differ: {out}')
    summary = f'{len(paths)} states, {len(keys)} retained keys; matching pixels, zero fallbacks, protected memory intact\n'
    (out / 'summary.txt').write_text(summary)
    print(summary + str(out))


if __name__ == '__main__':
    main()
