# M02: CPU versus SGP pseudo-sprite experiment

## Scope

The implementation follows the sibling emulator's
`demos/sgp-pseudo-sprite/256/sgp_sprite_256.asm` interface: SET_WORK,
SET_SOURCE/DESTINATION in 8bpp, BITBLT 0005h for restoration and 0105h
for source-zero transparency, END, and bounded busy polling. GVRAM
addresses use the SGP's 200000h space, not the CPU aperture. Odd X uses
an aligned address and descriptor start-dot bit 4.

This is a synthetic microbenchmark, **not the live game renderer**.
It uses the M02 indexed 8bpp screen and two 70 KiB areas. Both methods
restore the same rectangles from cached GVRAM, then paint the same
16x16 or 32x32 sources from RAM in painter order. There are 1, 8, 32 or
64 sprites, including odd X addresses and overlapping large sprites.
One quarter of source pixels are transparent (0); opaque index 16 is
black, testing that black is copied rather than treated as transparent.

CPU: REP MOVSW restores and byte-loop transparency. SGP: construct a
fresh command list, submit it and wait for END. Timing includes all
these costs, but excludes one-time initialization, position generation
and bitmap preparation. The SGP is used synchronously; useful CPU work
during DMA and interaction with the game scheduler are not tested.

## Reproduction

```
python3 -I tools/test_sgp.py
python3 -I tools/check_sgp.py --vaeg EXE --bios DIR
python3 -I tools/build_screen.py --sgp-bench --output build/m02sgp.d88
```

No game ROMs are required. `src/m02/sgp_bench.inc` is the guest; output
under `build/sgp-check/` includes listings, register/GVRAM captures and
`results.csv`. The test verifies both outputs against an independent
Python image and verifies that the cached background was not altered.
It arms each debug wait for the **next** occurrence (ordinal 1).

## vaeg results

All eight CPU and SGP images matched. Two repeated runs produced identical
counts. Clock counts below include restore plus paint, not paint alone.

| Size | Count | CPU clocks | SGP list build | SGP submit/wait | SGP total | CPU/SGP |
|---|---:|---:|---:|---:|---:|---:|
| 16x16 | 1 | 10326 | 498 | 4187 | 4685 | 2.20 |
| 16x16 | 8 | 82911 | 3333 | 32072 | 35405 | 2.34 |
| 16x16 | 32 | 331408 | 13053 | 127328 | 140381 | 2.36 |
| 16x16 | 64 | 662884 | 26013 | 254278 | 280291 | 2.36 |
| 32x32 | 1 | 39412 | 498 | 13200 | 13698 | 2.88 |
| 32x32 | 8 | 317260 | 3333 | 102759 | 106092 | 2.99 |
| 32x32 | 32 | 1268949 | 13053 | 408452 | 421505 | 3.01 |
| 32x32 | 64 | 2537826 | 26013 | 816033 | 842046 | 3.01 |

At approximately 133460 guest clocks per display frame, eight 16x16
sprites cost 0.62 frames on CPU versus 0.27 with SGP; eight 32x32 sprites
cost 2.38 versus 0.79. These are isolated workload costs, not game FPS.

Measured executable SHA-256:
`3e9d5e09993aa659d3843e987e26f466824ef369aec9bbd2129a5eddefb4b3c6`.
Sibling source checkout HEAD at measurement:
`f81b1af9ae820b15c7ac29ac2fe29d8a641883bc` (not proof of executable provenance).

The emulator's SGP specification explicitly marks command costs and bus
contention as provisional. This result does not establish PC-88VA/VA2
performance or a hardware sprite-count limit.

## Implications for the port

SGP is promising for rectangle restoration and prepared sprite blits.
However, the native reference currently stores 2bpp source pens expanded
to bytes, not palette-mapped SGP images. The game uses palette entry 31
for sprite transparency, whereas this SGP mode skips source zero. A real
backend must prepare/cache coloured images, mapping transparent pixels
to zero while retaining opaque index 16 for black. That work, cache size,
flip handling and clipping must be measured before selecting a backend.

A follow-up now measures real-source conversion, reflection and cache
hits/misses: see [SGP cache evaluation](SGP-CACHE.md). It confirms Y
reflection via source pitch and quantifies cold and warm conversion costs.

Existing native timings also include dirty-state detection, source lookup,
clipping and priority-preserving cell masks. Do not apply this table's
speedup directly to those complete frame timings. The benchmark does not
replace `native.inc`; the game's prototype still uses CPU drawing.
