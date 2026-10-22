# M02: packed-4bpp retained-source transfer

This follows [the two-screen display probe](TWO-PLANES.md). It validates
runtime source conversion and SGP transfer separately before replacing the
8bpp native compositor. It is not yet an alternating-page damage renderer.

## Representation and memory

`retained.inc` now supports packed sources: each converted 16x16 image is
128 bytes, so all 512 retained slots fit in standard RAM 70000h..7FFFFh.
The full glyph/colour/X-flip directory is unchanged. Y flip does not enter
the key; a negative source pitch reflects the already cached image. (This
probe only: on the VA and VA2 the negative pitch garbled the game's
sprites, and the game now caches Y-flipped images too; docs/NATIVE-PLANES.md.)

Source lookup indices 0..14 become nibbles 1..15. Lookup index 15 becomes
transparent nibble zero. Thus original opaque black is nibble one, never
confused with transparent zero. Two source pixels become one byte, left
pixel first in the high nibble. Colour lookup, transparency remapping and
X reflection are performed by the guest on first use, not by the host.

`packed_probe.inc` expands raw source pens at 40000h, uses the retained
bank at 70000h and a short SGP list at 39000h. It does not use expansion
RAM. Complete 50000h..6FFFFh canaries protect the future Z80 contexts.
GVRAM fronts are at 00000h and 08C00h. The upper screen holds a uniform
packed background template at 20000h; all other GVRAM bytes have canaries.

The shared directory's original 8bpp addressing remains the default;
`KEEP_PACKED` selects 128-byte slots only for this new probe.

## Transfer details

Each request identifies a complete source tile plus a clipped rectangle.
The SGP descriptor specifies packed 4bpp (format 1). Its start-dot field
selects one of four pixels in the aligned source/destination word. Tests
exercise source left offsets 0,1,2,3, odd destination X, widths 11,13,15,16,
and top/bottom clipping. Source row pitch is eight bytes. The emulator's
encoded negative pitch is FFF6h for -8 bytes; this still needs hardware
confirmation, as does the previously tested negative 8bpp pitch.

The front-B destination adds 08C00h and correctly carries into the address
high word. Requests near the bottom of front B cross its 64 KiB address
boundary and end exactly at 117FFh without corrupting adjacent bytes.

Three measured passes run after initial source expansion and directory
initialization:

1. Cold front A: convert missing complete tiles and transfer clipped pieces.
2. Warm front A: repeat the same requests with the cache retained.
3. Warm front B: draw the requests with **opposite Y flips**, retaining the
   same keys and pixels. No additional images should be generated.

Each pass first resets its destination from the background template. This
is a whole-page CPU copy **outside the measured interval**, not the planned
per-front footprint clear. Do not infer frame-render cost from these numbers.
The measured interval includes record processing, directory lookup, misses,
conversion, list building, submission and synchronous bounded SGP wait.
An unexpected full cache or SGP timeout halts this isolated probe.

## Results in vaeg

| Input | Requests/pass | Unique keys | Cold A clocks | Warm A clocks | Warm B/opposite Y clocks |
|---|---:|---:|---:|---:|---:|
| Asymmetric synthetic tiles | 160 | 32 | 629921 | 331974 | 332249 |
| Full-capacity synthetic stress | 512 | 512 | 5829525 | 1062363 | 1063357 |
| Real-source edge fixture | 105 | 12 | 335214 | 223437 | 223597 |

The real-source fixture is repeated over five clipping shapes; 105 requests
are **not** a claim of 105 independent sprites in a gameplay frame. The
512-key stress similarly exercises storage capacity, not a game scene.
Positions are reused after 128 requests, preserving draw-order overlaps.

All three full 256 KiB GVRAM captures per input matched independent host
composition, including the untouched page/template and every guard byte.
Guest hits, misses, resident count and probe count matched the host model.
Warm passes have zero misses, including the opposite-Y pass. The full
capacity run reaches offset FF80h for its final 128-byte source tile.
The full Z80-bank canaries also match after every render.

This probe checks GVRAM and guest directory state. The separate two-screen
probe checks final RGB composition; combining runtime SGP transfers with
that final mixer check is part of the next integration, not yet complete.

```
python3 -I tools/check_packed_sgp.py --vaeg EXE --bios DIR
python3 -I tools/check_packed_sgp.py --stress --vaeg EXE --bios DIR
DD_ROMS=PATH python3 -I tools/check_packed_sgp.py --vaeg EXE --bios DIR \
  --snapshot EDGE.memory
python3 -I tools/test_two_planes.py
```

Artifacts live under ignored `build/packed-sgp/`. Real-source artifacts
contain user assets and must not be distributed. The existing 8bpp native
CPU/SGP renderer remains available; no live game backend is changed here.

The follow-up [native packed compositor](NATIVE-PLANES.md) now implements
background/foreground drawing, page-local damage, transparent clearing and
VRTC front swaps. It includes an identical-sequence timing comparison with
clearing and preparation included. The isolated probe here remains available.
