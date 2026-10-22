# SGP direction and real-source cache evaluation

## Traversal versus reflection

`io/sgp.c` in the sibling emulator advances both source and destination
in the direction selected by HD/VD. Opaque copies starting at matching
corners therefore preserve the image. The asymmetric 16x16 test confirms
this for all four directions, at odd destination X.

Transparent Y reflection works with the source starting on its bottom
row and a negative source pitch, while the destination walks downward.
For a 16-byte pitch, this vaeg implementation decodes FFEEh as -16
(mask bit 0, interpret signed, then add 2). No Y-reflected bitmap is needed.
This encoding and timing still need hardware verification.

Transparent X reflection can be performed without CPU pixel conversion
by issuing one width-one BITBLT for each column in reverse source order.
The test deliberately does not combine HD with transparency, a combination
the emulator's validation identifies as outside documented combinations.

| 16x16 operation | BITBLTs | Build clocks | Submit/wait clocks | Total |
|---|---:|---:|---:|---:|
| Opaque forward | 1 | 253 | 2483 | 2736 |
| Opaque HD | 1 | 269 | 2547 | 2816 |
| Opaque VD | 1 | 276 | 2483 | 2759 |
| Opaque HD+VD | 1 | 292 | 2547 | 2839 |
| Transparent forward | 1 | 251 | 2541 | 2792 |
| Transparent Y reflection, negative pitch | 1 | 267 | 2541 | 2808 |
| Transparent X reflection, column lists | 16 | 3134 | 14914 | 18048 |
| Transparent XY reflection, column lists | 16 | 3140 | 14914 | 18054 |

All eight full-frame outputs and unchanged background caches matched the
independent Python oracle. Column reflection costs about 6.5 times the
normal transparent copy in this model. The following experiment therefore
caches X-reflected pixels but uses SGP pitch for Y reflection.

## Real-source experiment

The user's primary assets and captured video state select 16x16 pieces,
including the four pieces of large sprites and their colour/flip flags.
The selected pieces are arranged in a synthetic grid, not their original
screen positions. Reports state both selected and total counts. No pieces
were dropped in the reported runs. The newer retained-cache probe supports
512 requests, reusing grid positions after 128.

Each run includes a direct CPU renderer and cold/warm SGP passes with
1, 16, 64 and 128 slots. Both methods begin with the same background.
A newer 512-slot retained backend is described in [CACHE-WARMUP.md](CACHE-WARMUP.md).
CPU directly reads source pens, applies colour lookup and X/Y flips,
and skips the transparent colour. SGP cache misses convert the whole
16x16 image to coloured 8bpp, mapping source palette 31 to transparent
zero while keeping opaque black at 16. Only X flip is materialized.
Cache hits reuse the converted image. SGP uses a fresh per-piece command
list and synchronous busy wait, so eviction cannot overwrite an in-flight
source. There is no unmeasured asynchronous work.

Keys contain glyph (8 bits), colour (6 bits), and X flip (1 bit), not Y
flip. This prototype is direct-mapped: slot = (key_low XOR key_high) AND
(slot_count - 1), with a full key tag. This deliberately simple policy
can conflict even when the number of unique keys is below capacity.
128 slots occupy 32 KiB main RAM plus 256 bytes of tags, not GVRAM.

Included: request handling, cache hash/tag checks and replacement, palette
conversion, X flip on miss, Y-pitch selection, command building, submission
and waiting. Excluded: initial packed-ROM decoding (pens are build-time
expanded as in the native reference), position/visibility selection,
clipping, dirty-region detection/restoration, and game CPU execution.
Warm means replaying the identical request list, not an animation sequence.
These costs must not be presented as game-frame performance.

## Initial direct-map measurements (guest clocks, commit 4622879)

These historical measurements precede the retained-cache extension and
source-bank changes. See [CACHE-WARMUP.md](CACHE-WARMUP.md) for current costs
and every-frame startup/cache-growth measurements.

All 27 CPU/SGP outputs across the three inputs matched independently
computed expected images. Background cache bytes were also unchanged.
The emulator binary is the one identified in [the earlier benchmark](SGP-BENCH.md).

| Source state | Pieces | Keys | CPU direct | SGP cold, 128 slots | SGP warm, 128 slots | Warm hits/misses |
|---|---:|---:|---:|---:|---:|---:|
| Primary frame 1200 | 25 | 14 | 375184 | 290937 | 71447 | 25 / 0 |
| Primary frame 780 | 89 | 89 | 1311132 | 1598746 | 254456 | 89 / 0 |
| Synthetic edge state, primary graphics | 21 | 12 | 314912 | 264219 | 185159 | 13 / 8 |

The edge input contains 10 X-flipped and 10 Y-flipped pieces; it exercises
all local flip combinations using real graphics. The two captured states
have respectively 1/0 and 0/1 X/Y-flipped pieces.

Capacity and conflict effects in the warm pass:

| Input | 1 slot hits/misses; clocks | 16 slots | 64 slots | 128 slots |
|---|---|---|---|---|
| Frame 1200 | 11/14; 290937 | 14/11; 244207 | 19/6; 166687 | 25/0; 71447 |
| Frame 780 | 0/89; 1598746 | 0/89; 1598746 | 39/50; 1021506 | 89/0; 254456 |
| Edge state | 1/20; 376499 | 1/20; 376499 | 1/20; 376499 | 13/8; 185159 |

At 128 slots, the two captured inputs are about 5.2 times faster than CPU
when fully cached. The 89-key cold pass is about 22% slower than CPU.
The edge input demonstrates persistent direct-map conflicts despite only
12 unique keys. A better replacement/associativity policy and real temporal
animation sequences are needed before choosing cache size or backend.

## Reproduction

```
python3 -I tools/test_sgp_material.py
python3 -I tools/check_sgp_direction.py --vaeg EXE --bios DIR
DD_ROMS=PATH python3 -I tools/check_sgp_cache.py --vaeg EXE --bios DIR CAPTURE.memory
```

`src/m02/sgp_direction.inc` and `sgp_cache.inc` are separate probes.
`build/sgp-direction/` and `build/sgp-cache/` contain listings, register and
GVRAM captures, disks and CSV reports. Real-source outputs must never be
committed or distributed. An optional retained SGP backend is now connected
to the native snapshot compositor; see [NATIVE-SGP.md](NATIVE-SGP.md).
The live game scheduler is not yet connected.

These are vaeg results. SGP timing/contention is provisional in the
emulator; no original VA or VA2 hardware speed is established here.
