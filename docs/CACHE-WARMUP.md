# Retained sprite cache and startup warm-up

## Policy

Populate the coloured sprite cache on first use during startup and retain
its entries afterwards. Include glyph, colour and X flip in the key; SGP
negative source pitch handles Y flip without another bitmap. Later game
states can append combinations not displayed during startup.

This concerns 16x16 **sprite pieces**, not all foreground/background tiles.
Startup is not assumed to exercise every possible combination or round.

## Every-frame reference trace

`tools/trace_cache.py` records only the three sprite RAM windows and the
screen-flip latch on every reference-emulator frame. The input script is
the same as the earlier screen comparison: coin at 900, start at 1000,
then movement and button pulses. EAROM starts empty. No custom I/O reads
are made. The trace's sprite requests matched all 200 previously captured
sample states exactly.

| Through frame | Distinct keys | Coloured pixels, KiB | Nonempty keys |
|---|---:|---:|---:|
| 120 | 0 | 0.00 | 0 |
| 180 | 190 | 47.50 | 171 |
| 300 | 191 | 47.75 | 172 |
| 899 | 281 | 70.25 | 247 |
| 999 | 281 | 70.25 | 247 |
| 1200 | 299 | 74.75 | 264 |
| 1800 | 315 | 78.75 | 280 |
| 3000 | 332 | 83.00 | 294 |
| 6000 | 341 | 85.25 | 302 |

The old 30-frame sampling found only 246 keys (61.5 KiB). **That was an
undercount, not a sufficient capacity estimate.** Every-frame tracing
exceeds 256 keys at frame 719. Even omitting fully transparent images,
the final 302 keys need 75.5 KiB. The current probe includes those empty
images to remain comparable with its unculled request stream.

Before scripted start, 281 of the eventual 341 keys have appeared. The
remaining 60 first appear at or after frame 1000. The largest bursts are
54 new keys at frame 125 and 88 at frame 719. These are frame observations,
not assertions about exact boot-test or gameplay phase boundaries.

Visibility here is bounding-box visibility, not final pixel visibility:
fully transparent or obscured pieces are counted. This is one 6000-frame
input path, not all rounds, all states or the game's maximum requirements.
The trace itself is a RAM trace, not a new every-frame pixel comparison.

## Guest retained-directory probe (initial isolated evaluation)

A newer [native integration](NATIVE-SGP.md) now preserves the Z80 banks
and avoids expansion RAM, using 440 slots across standard RAM and spare
GVRAM. The 512-slot layout and timings below describe the earlier isolated
experiment, not the current native backend.

The existing direct-map baselines remain available. Two added passes use:

- 512 retained pixel slots, 256 bytes each: 128 KiB reserved;
- 1024 open-addressed buckets, with full key and slot index: 4 KiB;
- linear probing on collisions; no replacement or eviction;
- explicit capacity failure rather than silently reusing a live slot.

The directory persists from the cold pass to the warm pass. Its hit/miss,
resident-slot and probe counts are checked against an independent host
model. The current hash is simple and still has clustering costs; it is
not the final lookup optimization. Initialization of the directory and
initial expansion of source pens are outside the timed drawing passes.

The isolated probe stores expanded pens at 4000:0000, retained pixels at
5000:0000 and 6000:0000, and the SGP command list at 8000:0000. **The pixel
banks conflict with existing Z80 context allocations. This is not a live
game memory layout and must not be integrated without relocating either
the cache or those contexts.** Hardware RAM accessibility also remains a
gate; emulator results alone are insufficient.

`--first-use` replays the trace's first-use manifest in chronological order,
then repeats it with the directory retained. Images use a synthetic grid,
reusing positions after 128 requests. This exercises the retained slots,
including crossing the 64 KiB bank boundary, not a real game-frame raster.

| Input | CPU direct clocks | Retained cold clocks | Retained warm clocks | Warm hits/misses |
|---|---:|---:|---:|---:|
| Frame 1200, 25 pieces / 14 keys | 375497 | 294297 | 74135 | 25 / 0 |
| Edge fixture, 21 pieces / 12 keys | 315177 | 252927 | 63431 | 21 / 0 |
| Complete 341-key first-use manifest | 5016689 | 6309457 | 1169949 | 341 / 0 |

All 11 CPU/SGP passes for each input matched expected pixels; the untouched
background page also matched. The complete manifest retained all 341
entries (85.25 KiB used) with no eviction. Its repeat produced identical
timings and 3641 directory probes per pass. The edge fixture confirms that
X/Y flip combinations no longer cause direct-map eviction; it contains
10 X-flipped and 10 Y-flipped requests.

These are isolated vaeg timings. The manifest's total cost is **not a
single gameplay frame cost**, nor a prediction of boot duration: actual
first uses are spread over 6000 frames. Request selection, background
restoration and game execution are excluded. Source-pens storage and
lookup instrumentation changed since the earlier baseline, so small
clock differences from [SGP-CACHE.md](SGP-CACHE.md) are expected.

## Remaining integration work

- The native snapshot backend now separates the cache from Z80 banks;
  live code/payload loading within that layout remains to be implemented.
- Connect the native renderer's first-use conversion to live scheduler
  startup rather than replayed snapshots.
- Measure complete frames and budget cold bursts during startup. Do not
  extrapolate synthetic-grid timings to game speed.
- The native backend now falls back to CPU rendering on capacity exhaustion;
  extend coverage to later states and rounds.
- Extend state/round coverage and verify SGP pitch and RAM use on VA/VA2.

## Reproduction

```
DD_ROMS=PATH python3 -I tools/trace_cache.py --mame EXE --system SYSTEM --rompath DIR
DD_ROMS=PATH python3 -I tools/check_sgp_cache.py --vaeg EXE --bios DIR \
  --first-use build/cache-trace/RUN/first-use.csv CAPTURE.memory
python3 -I tools/test_cache_growth.py
```

`--until-frame 999` restricts the first-use manifest to the pre-start prefix.
Trace, manifest, images and disks remain private under ignored `build/`.
The optional native snapshot renderer now has an SGP backend; the live
scheduler has not yet been connected to it.
