# M02: background plus two alternating foreground pages

## Correction to the initial 8bpp plan

Three 320x224 8bpp images total 210 KiB, but that alone does **not** prove
they fit a two-screen configuration. The BNN manual, display chapter,
single-plane graphics section, specifies that port 0100h bit 11 divides
GVRAM into two fixed 128 KiB regions in two-screen mode. Two 70 KiB front
images do not fit one region. One-screen mode does not permit using G1.
The earlier proposal overlooked this per-screen restriction.

The source compositor already separates colour indices:

- Background and character cells: indices 0..15.
- Opaque sprite pixels: indices 16..30; index 31 is transparent.

Two **packed-4bpp** screens therefore preserve the existing programmed
colours without reducing either layer's colours. Palette mode 2 selects
a different 16-entry palette bank for each screen.

## Validated allocation and palette mapping

| GVRAM offsets | Screen/use | Bytes |
|---|---|---:|
| 00000h..08BFFh | G0 front A | 35840 |
| 08C00h..117FFh | G0 front B (probe; the live game uses 09100h, docs/NATIVE-PLANES.md) | 35840 |
| 11800h..1FFFFh | Free lower-region space | 59392 |
| 20000h..28BFFh | G1 background | 35840 |
| 28C00h..3FFFFh | Free upper-region space | 95232 |

Total image storage: **105 KiB**, leaving 151 KiB, split between the two
regions. G0 presents A/B by changing its DSA. G1 stays at its region's
start (DSA zero, with implicit upper-region addressing). FB1's reserved
FSA/FBL/OFX/OFY words are written as zero, not used for relocation.

Both screens use a 160-byte pitch for 320 pixels. Bytes hold the left pixel
in the high nibble. Registers: GRMODE preserves BIOS settings and enables
bit 11, GRRES=1111h, palette mode=01A0h, palette composition=00BAh.
G0 has priority over G1; only G0 index zero is transparent.

G1 uses palette bank 0 unchanged. G0 uses bank 1:

- Packed pixel 0: transparent; palette entry 16 is not used for normal drawing.
- Packed pixels 1..15: original opaque sprite indices 16..30, respectively.
- Original opaque black at index 16 becomes packed pixel 1 / palette entry 17.

This is a palette permutation, not quantization to fewer colours. The two
banks hold 32 entries, with 16 background colours and 15 opaque foreground
colours usable together while transparency is enabled.

## Probe and verification

`src/m02/two_planes.inc` and `tools/check_two_planes.py` provide a separate
probe, not a replacement for the current 8bpp native renderer. The probe
first exercises five states:

1. Front A over background, zero transparent.
2. Background on top, hiding front A (priority control).
3. Front A on top with transparency disabled (zero-opacity control).
4. Front B over the unchanged background.
5. Front A restored.

It then alternates B/A once per 60 VRTCs for interactive viewing. The
checker captures two additional swaps. Display-start updates follow VRTC;
this is not yet proof of tear-free VA/VA2 hardware behavior.

Both the ROM-free asymmetric pattern and real-source edge/movement fixtures
passed all **seven final RGB captures**, with exact image matches over the
entire 320x224 raster. All three packed GVRAM images also matched in every
capture. The synthetic fixture distinguishes all 32 palette entries in its
opaque controls and specifically tests opaque black versus transparent zero.
43 ROM-free unit tests pass.

Unlike earlier GVRAM-only tests, this checks the final screen mixer. The
SDL rendered-window capture is configured to 640x470: a 22-pixel menu plus
the full 640x448 doubled raster, with filtering and scanline gaps disabled.
Otherwise the default window scales the raster down. Palette RGB is sampled
from the two opaque control phases to accommodate vaeg DAC expansion and
SDL surface quantization. Samples must be near their programmed colours;
the synthetic palette must remain 32 distinct colours. The pixel/priority/
transparency oracle uses independently composed indices, not screenshot
segmentation. This does not verify physical monitor colour calibration.

For real-source tests, the host reference separates sprite pixels from the
full render and renders the background with sprite entries disabled. The
pair must have the same background. Palette-control pixels occupy the
otherwise unused left margin; the game raster itself is unchanged. These
are precomposed images, not native runtime conversion or game execution.

```
python3 -I tools/check_two_planes.py --vaeg EXE --bios DIR
DD_ROMS=PATH python3 -I tools/check_two_planes.py --vaeg EXE --bios DIR \
  --snapshot FIRST.memory --next-snapshot SECOND.memory
python3 -I tools/test_two_planes.py
```

Private results and disks are under `build/two-planes/`. Convenience copies
are `build/m02-two-planes.d88` (synthetic) and
`build/m02-two-planes-material.d88` (user graphics); expected material images
are `build/m02-two-planes-material-a.png` and `-b.png`. After brief diagnostic
priority/transparency phases, the front images alternate over a fixed
background. Real-source outputs must not be distributed.

No emulator change
was required. The existing single-screen 8bpp CPU/SGP backend remains intact.

## Follow-up and remaining work

[The native packed compositor](NATIVE-PLANES.md) now implements the first
four items below and compares complete costs with the 8bpp reference.
Live scheduling, background update policy and hardware testing remain.

- [The packed-source SGP probe](PACKED-SGP.md) now verifies guest conversion,
  512 retained images in 64 KiB, odd-X clipping, local flips, transparent zero
  and opaque black on both front pages. Native integration is now optional
  via `--native-planes`.
- Connect the native background/character renderer to G1.
- Track old sprite footprints separately for front A and front B. Clear the
  reused page's old footprints, not the last displayed page's footprints.
- Keep background updates separate from front-page redraw and switching;
  the single background page still needs a tearing/update-policy evaluation.
- Compare complete rendering costs with the retained 8bpp reference using
  identical snapshot sequences, then integrate live scheduler state/pacing.

No speedup or hardware acceptance is claimed from this static composition
probe. External-character/text rendering remains a separate later task.
