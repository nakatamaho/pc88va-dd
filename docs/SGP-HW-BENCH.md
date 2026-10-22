# SGP benchmark for VA/VA2 hardware and vaeg

On the VA and the VA2 the game ran slower than at 30 frames a second and
its SGP sprites were garbled, while vaeg showed neither. This benchmark
measures the SGP and the CPU on the machine itself, with the game's screen
mode and the game's command shapes, so that the vaeg SGP model can be
corrected against hardware.

```
python3 -I tools/build_sgpbench.py            # build/sgpbench.d88
python3 -I tools/check_sgpbench.py --vaeg EXE --bios DIR [--model va|va2]
```

The disk is MS-DOS 4.0 (as the game disks) with `SGPBENCH.COM`
(`src/bench/sgpbench.asm`, data from `tools/sgpbench.py`). It holds no ROM
data: the images, cases and font are synthetic (the case words are stored
XOR 5A5Ah and the font XOR A5h, so that runs of small numbers do not trip
the publish scanner's ROM windows; the remaining hits are runs of zeros,
as in DD.COM). It needs 15 kHz and memory
to 5000h, copies itself to 3000:0000 (SGP addresses 3xxxxh) and never
returns; restart the machine to leave. It takes about 3.5 minutes.

## Screen

BENCH 3 (2026-10-19): the same tests and cases as BENCH 2, with the
column heads on the status line and the text 2 rows higher, so that the
CASES line (cut off below the picture on the maintainer's monitor) is
visible. The first line starts with BENCH3.

Top: the 48 correctness boxes (three rows). Below: one line a test, then
`CASES 48 FAIL n` with the first failing cases as `case:bytes`, green when
all match, red otherwise (`SGP TIMEOUT` if the SGP had to be stopped).
SPACE switches front A (the SGP's result) and front B (the expected image
computed on the PC); the first line says which is shown. A photograph of
the finished screen, and if a case fails one of each front, is all that is
needed.

## Timing tests

Each test is repeated for 30, 120 and 480 VRTCs (three windows; 59.94 Hz
assumed: 16683.4 us a VRTC); the three columns are the time of one
repetition in each window, computed from the VRTCs that actually elapsed
(the last repetition may overrun a window). With few repetitions the
window's end rounds by up to one repetition; the columns should converge
(in vaeg 120 and 480 agree within 0.4%). The repetition counts are in the
checker's results.csv. SGP tests include
starting the list and polling for its end, not building it. Pieces are
16x16 packed 4bpp from main RAM, 8-byte pitch, to front B, BITBLT 0105h
(source zero transparent), as `planes_emit`.

| NN | Test |
|---|---|
| 01 | CPU `LOOP` 1000 times (CPU speed) |
| 02 | CPU `REP STOSW` 35840 bytes to GVRAM (a whole front) |
| 03 | the same to main RAM |
| 04 | CPU `REP MOVSW` 8192 bytes GVRAM to GVRAM (as the background cache) |
| 05 | SGP list with SET_WORK and END only (start and completion overhead) |
| 06 | SGP CLS of a whole front, 35840 bytes (the game's whole-front clear) |
| 07 | SGP CLS 1280 bytes |
| 08 | SGP list with one 16x16 piece |
| 09 | SGP list with 32 16x16 pieces, start dot 0 |
| 10 | 09 at destination start dot 1 |
| 11 | 09 read upwards (Y flip, pitch FFF6h as the game) |
| 12 | 09 with BITBLT 0005h (opaque) |
| 13 | 32 8x8 parts (the game's cell fragments) |
| 14 | 09 with the sources in GVRAM (230000h) |
| 15 | 09 started, then 02 by the CPU, then the wait |
| 16 | 09 started, then 03 |
| 17 | 09 started, then `LOOP` 4000 times |

15-17 against 09 and 02/03/01 show whether the CPU and the SGP run in
parallel (time near the larger of the two) or slow each other down (near
the sum).

## Correctness cases

Each case draws one piece into its own 20x18 box, which is first filled
with a two-colour pattern, so that transparency is visible. Cases 0-15:
whole pieces at every destination start dot, normal, Y flip, opaque and
both. 16-31: horizontal clipping (left 0-15, widths 1-15, every start
dot), half of them flipped. 32-47: vertical clipping and random mixes. The
expected image follows the semantics the game relies on (source part
`left, top, width, height` of a 16x16 image to `x + left, y + top`; Y flip
reads row 15 - row; zero source pixels left alone in 0105h).
`tools/sgpbench.py` lists the cases (`cases()`).

## vaeg results (2026-10-18, first version: one 60-VRTC window)

vaeg built 2026-10-16 (`/tmp/vaeg-tr`, includes M109a), both models: all 48
cases match. The older build used for the game checks (2026-10-09, before
M109a) fails every Y-flip case of height above 1 on `--model va` only
(24 cases): it decoded the FFF6h pitch differently on the original VA.

| NN | VA model us | VA2 model us |
|---|---:|---:|
| 01 | 2129.7 | 2129.7 |
| 02 | 9183.5 | 9183.5 |
| 03 | 6903.4 | 6903.4 |
| 04 | 4766.6 | 4766.6 |
| 05 | 32.5 | 32.5 |
| 06 | 13346.7 | 9018.0 |
| 07 | 526.2 | 363.3 |
| 08 | 386.6 | 212.6 |
| 09 | 11776.5 | 5958.3 |
| 10 | 12512.5 | 6256.2 |
| 11 | 11776.5 | 5958.3 |
| 12 | 10648.9 | 5381.7 |
| 13 | 6809.5 | 3416.3 |
| 14 | 11776.5 | 5958.3 |
| 15 | 12833.3 | 12833.3 |
| 16 | 11776.5 | 10536.8 |
| 17 | 12060.2 | 12060.2 |

vaeg M124 (`02ce6d47`, built from a clean export, debug preset) gives the
same figures to the tenth of a microsecond on both models, and all 48
cases match.

Second version (three windows), vaeg M124, us per repetition at 30 / 120
/ 480 VRTCs, all 48 cases matching:

| NN | VA model | VA2 model |
|---|---|---|
| 01 | 2129.7 / 2132.0 / 2133.1 | same |
| 02 | 9100.0 / 9225.8 / 9225.8 | same |
| 03 | 6856.1 / 6903.4 / 6921.3 | same |
| 04 | 4766.6 / 4778.0 / 4783.7 | same |
| 05 | 32.8 / 32.8 / 32.8 | same |
| 06 | 13171.1 / 13436.2 / 13481.5 | 8937.5 / 9018.0 / 9018.0 |
| 07 | 526.8 / 526.8 / 526.8 | 363.7 / 363.8 / 363.8 |
| 08 | 386.7 / 387.0 / 387.0 | 212.9 / 213.0 / 213.0 |
| 09 | 11639.5 / 11846.2 / 11863.7 | 5958.3 / 5958.3 / 5958.3 |
| 10 | 12512.5 / 12512.5 / 12512.5 | 6256.2 / 6275.8 / 6275.8 |
| 11 | 11639.5 / 11846.2 / 11863.7 | 5958.3 / 5958.3 / 5958.3 |
| 12 | 10648.9 / 10705.9 / 10720.2 | 5381.7 / 5381.7 / 5392.6 |
| 13 | 6763.5 / 6809.5 / 6815.3 | 3404.7 / 3422.2 / 3425.1 |
| 14 | 11639.5 / 11846.2 / 11863.7 | 5958.3 / 5958.3 / 5958.3 |
| 15 | 12833.3 / 12916.1 / 12937.0 | 12833.3 / 12916.1 / 12916.1 |
| 16 | 11639.5 / 11846.2 / 11863.7 | 10427.1 / 10592.6 / 10620.7 |
| 17 | 11916.7 / 12060.2 / 12115.0 | same |

In vaeg one 16x16 piece costs about 186 us (VA2 model) or 368 us (VA
model), a whole-front CLS 9.0 or 13.3 ms: a frame is 16.7 ms. These are
the emulator's provisional costs (io/sgp.c marks command costs and bus
contention as unmeasured), not hardware figures. Hardware results go here.

## Hardware results (2026-10-19, photographs by the maintainer)

PC-88VA and PC-88VA2, SGPBENCH 2: every case read upwards (Y flip, source
pitch FFF6h) is garbled on both machines (mostly colour 15 with a few dark
rows); every other case equals the expected image. The CASES line falls
below the visible picture on the monitor. Microseconds per repetition at
480 VRTCs:

| NN | Test | VA | VA2 |
|---|---|---:|---:|
| 01 | CPU LOOP x1000 | 2260.2 | 2260.2 |
| 02 | CPU STOSW GVRAM 35840 | 13830.7 | 13712.3 |
| 03 | CPU STOSW RAM 35840 | 11952.2 | 9499.4 |
| 04 | CPU MOVSW GV-GV 8192 | 8564.7 | 8537.3 |
| 05 | SGP empty list | 76.6 | 76.4 |
| 06 | SGP CLS 35840 | 27613.9 | 11934.4 |
| 07 | SGP CLS 1280 | 1075.6 | 508.6 |
| 08 | SGP 1 x 16x16 | 656.9 | 438.8 |
| 09 | SGP 32 x 16x16 | 18710.3 | 11759.2 |
| 10 | 09 at dot 1 | 18710.3 | 11759.2 |
| 11 | 09 Y flip (FFF6h, garbled) | 20746.1 | 13806.9 |
| 12 | 09 opaque | 17002.1 | 10792.4 |
| 13 | SGP 32 x 8x8 | 10188.3 | 6867.9 |
| 14 | 09 source in GVRAM | 18842.4 | 10925.0 |
| 15 | 09 + CPU STOSW GVRAM | 20120.6 | 20273.4 |
| 16 | 09 + CPU STOSW RAM | 18580.1 | 16177.8 |
| 17 | 09 + CPU LOOP x4000 | 18409.2 | 14968.2 |

One 16x16 piece costs about 585 us on the VA (3.5% of a frame) and 367 us
on the VA2; a whole-front CLS 27.6 ms (VA), more than a frame. The CPU's
memory writes are 1.5-1.7x slower than vaeg's. On the VA the CPU runs in
parallel with the SGP almost for free. The game no longer uses negative
pitches (docs/NATIVE-PLANES.md); vaeg M128 (branch
`topic/m128-sgp-negative-fbw`) garbles them and is calibrated to this table.
