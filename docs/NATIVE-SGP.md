# Native retained-sprite backend

`--native-sgp` now connects retained coloured sprites to the existing native
background, foreground, clipping and damage compositor. The CPU backend
remains available for comparison and as the capacity fallback. This still
replays captured states: the live three-program scheduler is not connected.

## Standard-memory allocation

The manual's memory map (BNN, printed pp. 47-48) identifies 00000h..7FFFFh
as standard installed RAM; 80000h..9FFFFh must not be assumed present.
An initial emulator-only placement in that upper region was discarded.
The native backend uses no expansion RAM and leaves both Z80 banks intact:

| Physical CPU range | Use |
|---|---|
| 20000h..2FFFFh | Native code/data and stacks; loader enforces payload limit |
| 30000h..37FFFh | Expanded character/background pens |
| 38000h..38587h | Previous video state (moved from 70000h) |
| 38600h..38727h maximum | One SGP command list, at most nine rectangles |
| 40000h..4FFFFh | Expanded sprite pens |
| 50000h..5FFFFh | Reserved for existing main/sub Z80 context |
| 60000h..6FFFFh | Reserved for existing sound Z80 context |
| 70000h..7FFFFh | First 256 retained images (64 KiB) |

The final 184 images occupy GVRAM offsets 34800h..3FFFFh (46 KiB).
Their CPU aperture is D4800h..DFFFFh, and SGP addresses are
234800h..23FFFFh. Thus the native capacity is **440 images / 110 KiB**,
not the earlier isolated probe's 512 images / 128 KiB. Directory storage
is 4 KiB inside the code/data segment. The observed 341 images fit with
99 slots spare; that is not an all-round upper bound.

All three 70 KiB GVRAM pages remain separate: output at 00000h, background
cache at 11800h, and future alternating output at 23000h. The retained
GVRAM images begin exactly after the third page. Hardware accessibility,
SGP pitch behavior and contention still require VA/VA2 testing.

## Composition and lifetime

`retained.inc` is shared by the isolated experiment and this backend.
It resolves collisions by linear probing, assigns stable slots on first
use, and never evicts. Native initialization resets it once; full redraws
and video-latch changes do not reset it. Misses perform palette conversion,
transparent-zero remapping and X reflection. Y reflection uses SGP pitch.

For a full redraw, each clipped piece uses one transparent BITBLT. For an
incremental update, the clipped rectangle is intersected with changed
8x8 cells. Only those intersections are transferred, preserving priority
outside restored cells. A piece can require up to nine rectangles. Each
list is submitted and completed before reusing the list or returning.
Destination addresses handle the 64 KiB boundary within the 70 KiB page.

When the selected capacity is full, a new key returns to the original CPU
sprite path. Existing cache entries remain intact. SGP busy timeout instead
halts the probe: drawing concurrently with an unfinished SGP is unsafe.
Global screen flip remains rejected by the host builder.

Character changes also gained a shared CPU/SGP optimization: continue
REPE CMPSW through changed words, use an inverse RAM-to-row table to mark
only affected rows, and skip all other rows. Matching spans no longer
force a full board-raster scan. Conservative marking of both bytes in a
changed word can visit an extra row but cannot omit a changed cell.

## Verification

- Both CPU and SGP replayed all 60 consecutive primary transitions from
  frames 1200 to 1260 in one run, with every full framebuffer matching.
- Two rev2 snapshots (frames 780 and 1200) also matched through a full
  latch-changing transition with the SGP backend.
- Nine mixed fixture transitions passed with the normal 440-slot capacity
  and again with **one slot**, forcing CPU fallback without changing pixels.
- A separate 59-state replay retained all **341 keys**, including images
  in the GVRAM tail. It uses first-use sprite states with a frozen background,
  then reuses the most sprite-heavy retained state. Pixels match, no entries
  are lost, no fallback occurs, and the final replay has zero cache misses.
  This is a synthetic integration test, not a replay of complete game frames.
- Every checked render preserves canaries over the complete 128 KiB of
  Z80 context banks and the reserved third 70 KiB GVRAM page.
- 39 ROM-free unit tests passed; the isolated retained-cache probe also
  passed after extracting the shared directory.

Snapshot following-states are encoded as byte deltas, permitting the long
runs to fit the single-segment payload. State loading and memory-guard
checks occur outside the measured renderer interval. `--memory-guards`
is test-only and must never be enabled when real Z80 programs occupy the
protected banks. `check_native.py` automatically enables those guards.

## Complete renderer costs in vaeg

These include background/foreground handling, damage detection, cache
lookup and conversion, list building, submission and busy wait. They
exclude initial source expansion, snapshot loading, memory guard scans
and the game scheduler. Both backends include the new character-row scan.

| Changed cells | Updates in the 60-frame sequence | CPU clocks | SGP clocks |
|---|---:|---:|---:|
| 0 | 41 | 6512 | 6556 |
| 2 | 2 | 113189-113204 | 76638-76662 |
| 5 | 2 | 138731-139055 | 102188-102512 |
| 6 | 15 | 118673-118724 | 80868-98194 |
| All 60 updates, summed | 60 | 2551675 | 1903143 |

SGP reduces this complete sequence's rendering cost by about 25%, rather
than the isolated warm-sprite microbenchmark's fivefold speedup. The
six-cell range includes one new cached image; resident count grows from
14 to 15. At roughly 133460 guest clocks per display frame, the maximum
sampled SGP update is about 0.77 frames **before game execution**. This is
not proof of 60 Hz operation. Larger fixture changes and full redraws are
much slower; a full first composition here is about 4.65 million clocks.

## Reproduction

```
DD_ROMS=PATH python3 -I tools/check_native.py --sgp --vaeg EXE --bios DIR \
  FIRST.memory --next-snapshot SECOND.memory
DD_ROMS=PATH python3 -I tools/check_native.py --sgp --cache-slots 1 \
  --vaeg EXE --bios DIR FIRST.memory --next-snapshot SECOND.memory
DD_ROMS=PATH python3 -I tools/check_retained_native.py --vaeg EXE --bios DIR \
  build/cache-trace/RUN/sprites.bin BACKGROUND.memory
```

To build a display probe without test guards, use `build_screen.py
--native-sgp --snapshot ...`. All images, disks, captures and state deltas
remain private under ignored build/. No public snapshot or remote is updated.

## Next hardware check

Private local artifacts prepared for the maintainer:

- `build/m02-native-cpu.d88`: CPU reference, ending on the edge fixture.
- `build/m02-native-sgp.d88`: the same sequence and final image using SGP.
- `build/m02-native-edges.png`: expected final image for those two disks.
- `build/m02-native-retained.d88`: the 59-state, 341-key retention test,
  including source pixels in the GVRAM tail and a final 89-hit/zero-miss redraw.
- `build/m02-native-retained.png`: its different expected final image.

Use 15 kHz, reset between disks, and allow time for the repeated guard
scans (the retention test takes about 16 emulated seconds; hardware time
is unknown). These are display probes, not playable disks. Compare CPU
and SGP output and the retention image, including bottom/right clipping,
flips and opaque-black pixels. Report the machine model, completion/hang,
and photos. No emulator throughput claim is a hardware acceptance result.

Negative source pitch and mixed main-RAM/GVRAM sources are the next hardware
gate before relying on this backend for live scheduling. These local disks
contain user assets and must not be committed or redistributed.

Next: integrate state acquisition and pacing with the three-program
scheduler, including startup; resolve code/payload loading within the
shared code segment; then measure combined execution and alternating-page
costs. The memory-map separation alone does not establish live integration.
