# Native packed two-screen compositor

The optional `--native-planes` backend connects runtime packed background
and sprite drawing to [the two-screen layout](TWO-PLANES.md). It replays
video snapshots, not the live three-program scheduler. The CPU and retained
8bpp SGP backends remain available as references.

## Allocation

| CPU physical address | Use |
|---|---|
| 20000h..2FFFFh | Code, lookup data, packed assets, state deltas, stack |
| 30000h..37FFFh | Expanded character/background pens |
| 38000h..38587h | Previous global video state |
| 38600h..38DFFh | Two 1024-byte front footprint maps |
| 39000h..39127h maximum | One SGP list, up to nine clipped rectangles |
| 39800h..39AFFh | Two previous front sprite-state records, 384 bytes each |
| 40000h..4FFFFh | Expanded sprite pens |
| 50000h..6FFFFh | Reserved Z80 contexts; unchanged by rendering |
| 70000h..7FFFFh | 512 retained 128-byte coloured sprite pieces |

No expansion RAM is used. The build reserves 13 KiB for code and directory
and enforces the existing F000h combined payload limit to protect the stack.
GVRAM uses front A at 00000h, front B at 09100h and background at 20000h,
35840 bytes per image. Eight blank lines (1280 bytes, plus 8 for a sideways
move) follow each image and precede it at the top of its 128 KiB region
(1FB00h, 3FB00h), so that the alignment screen can move the picture by DSA
(docs/M03.md). Front B was at 08C00h before. The checker requires the
margins to stay zero and every other unused byte to keep its canary. No GVRAM sprite-cache tail is needed for this backend.

An early local test caught an overlap between front-A history and the SGP
list; the corrected allocation above is covered by long alternating-state
checks. The two history maps and per-page sprite records are separate from
the command list and global shadow.

## Update and presentation

- Background and character tiles are decoded directly as packed bytes into
  G1. Changed character rows use the existing inverse RAM-to-row map. Full
  latch changes redraw the background, but do not invalidate sprite images.
- Each G0 front has its own previous sprite-state record. Reusing that front
  compares the current sprite state against **that page's previous state**.
  The old and new clipped/wrapped footprints form an 8x8-cell damage map.
- Clear damaged front cells to transparent zero. Skip unaffected rows.
  Repaint intersecting sprites in source priority order, restricted to dirty
  cells. A list may contain up to nine clipped rectangles per 16x16 piece.
- First-use colour/X-flip/Y-flip conversion uses the retained packed cache
  (key glyph | colour << 8 | X flip << 14 | Y flip << 15; FFFFh, the empty
  tag, is drawn by the CPU). Y flip used a negative source pitch (FFF6h)
  before; on the VA and VA2 every sprite drawn that way was garbled
  (left-facing characters, the game's raster being rotated), while vaeg
  drew it correctly. The traces show 358-367 keys with Y flip (338-346
  without), within the 512 slots. At capacity, uncached CPU drawing preserves pixels
  and also respects dirty-cell masking. Existing entries are never evicted.
- If sprite state is identical to the currently displayed state, keep that
  front displayed. Background-only changes need no front repaint or swap.
  Avoiding unnecessary swaps is important: otherwise every movement causes
  two updates as both fronts catch up on consecutive input frames.
- After SGP completion, switch G0 DSA just after a VRTC. Never modify the
  currently displayed front. The background remains one live page; its
  updates are not yet constrained to blanking, so tearing remains possible.

The native report returns background tiles in AX, cache hits/misses/fallbacks
in BX/CX/DX, resident keys in SI, cleared front cells in BP and the composed
front offset in DI. `--planes` checks that the same front is presented.

## Verification

- All 60 consecutive primary transitions from frames 1200 to 1260 pass.
- Eleven mixed transitions pass at capacity 512 and again at **capacity 1**,
  forcing CPU fallback. They include unchanged state, character/latch changes,
  clipping, wrapping, size/colour/flips, overlap, disappearance and return.
- A 59-state first-use replay retains all **341 observed keys** (42.625 KiB
  of packed pixels) and finishes with 89 hits and zero misses/fallbacks.
  Its background is frozen except for the final bank change: this is not
  a complete game-frame trace, nor proof of all-round cache capacity.
- Rev2 frames 780 and 1200 also pass a two-state transition.
- Every packed render checks an independently generated background plane,
  composed indices, all unused GVRAM bytes and the full Z80 context banks.
  The preceding displayed front must remain byte-identical during rendering.
- Every checked packed presentation checks final RGB over the complete
  640x448 doubled raster and the reported presented front. The expected RGB
  is computed from programmed palette words and emulator DAC expansion,
  with at most three RGB888 levels allowed for SDL surface quantization.
  This is not a physical monitor colour-accuracy test.
- 46 ROM-free unit tests pass. The older 8bpp references still pass the same
  60-transition sequence with unchanged timing results.

Palette words are applied a second time at packed initialization because
current vaeg adjusts DAC low bits after each byte write; the first pair can
retain one red low bit from the old BIOS palette. Reapplying settles those
low bits. This is an emulator-observed detail, not a claimed hardware bug.

## Timing comparison in vaeg

Measured renderer intervals include background updates, page-specific damage,
transparent clearing, cache conversion/lookup, list construction and bounded
synchronous SGP completion. They exclude initial pen expansion, state loading,
VRTC presentation waits, test-only settling and memory-canary scans. The
packed renderer runs with the VRTC handler active; interrupt overhead during
rendering is included. No game CPU execution is included in any backend.

| Same 60 input transitions | Total renderer clocks | Maximum update clocks |
|---|---:|---:|
| 8bpp CPU | 2551675 | 139055 |
| 8bpp retained SGP | 1903143 | 102512 |
| Packed two-screen retained SGP | 1802894 | 117901 |

This sequence's packed rendering sum is about **5.3% lower** than the 8bpp
SGP reference, not a large overall speedup. Its peak is higher because the
second front's first use draws all visible pieces. Detailed packed costs:

| Update type | Count | Guest clocks |
|---|---:|---:|
| Unchanged video state | 41 | 8356 |
| Two background cells, unchanged sprites | 2 | 27889-27895 |
| Five background cells, unchanged sprites | 2 | 49159-49479 |
| Warm front movement | 14 | 81273-86291 |
| First use of front B, one new key | 1 | 117901 |

The 8bpp reference spends about 77k/102k on the corresponding two/five-cell
character updates, so background separation helps those cases substantially.
Warm sprite movement is similar to the existing 8bpp path (about 81k-98k),
not an automatic gain from halving bytes. Unchanged packed checks cost more.
At roughly 133460 clocks/display frame, the packed maximum is about 0.88
frames **before game execution**, while warm movement is about 0.61-0.65.
Larger fixture changes cost much more. Full first composition here takes
about 3.58 million clocks. These are not a 60 Hz acceptance result.

The initial local whole-front redraw version was considerably slower. The
page-local damage and unchanged-display reuse above are required for the
reported results. Never compare the packed-transfer microbenchmark, which
excluded clearing, directly with this complete renderer.

## Reproduction and next steps

```
DD_ROMS=PATH python3 -I tools/check_native.py --planes --vaeg EXE --bios DIR \
  FIRST.memory --next-snapshot SECOND.memory
DD_ROMS=PATH python3 -I tools/check_native.py --planes --cache-slots 1 \
  --vaeg EXE --bios DIR FIRST.memory --next-snapshot SECOND.memory
DD_ROMS=PATH python3 -I tools/check_retained_native.py --planes \
  --vaeg EXE --bios DIR TRACE.bin BACKGROUND.memory
```

A verified private display disk is `build/m02-native-planes.d88`, with final
verified RGB in `build/m02-native-planes.png`. It replays base/edge/movement/
overlap/edge states and ends on the edge image; it is not playable. These
files use user graphics and must not be distributed.

Build without guards with `build_screen.py --native-planes --snapshot ...`.
`check_native.py` enables destructive test-only memory guards and two VRTC
settling intervals before each RGB capture. These are outside renderer clocks
and must never be enabled alongside running Z80 programs. Generated disks,
images, source assets and traces stay private under ignored build/.

[The live candidate](LIVE-M02.md) now acquires scheduler state and queues
VRTC presentation without blocking. Its broader samples exceed the narrow
snapshot cost bound here; no full-rate speed acceptance is implied.
Next: reduce per-piece/list overhead and budget cold bursts, first-front
initialization and combined game/render execution. Decide the single-background update
policy using hardware evidence. External-character/text evaluation remains
separate. No VA/VA2 correctness, contention or speed acceptance is implied.
