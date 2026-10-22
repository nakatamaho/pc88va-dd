# M02 live integration and hardware handoff

> Since M03 every game disk is an MS-DOS 4.0 disk with DD.COM, which loads
> DDGAME.DAT and FMVOICE.DAT to the same memory as described here
> (`docs/DIST.md`, AGENTS.md "Making disks"). Mentions of the IPL loading
> game disks below are historical; `build_live.py` now writes MS-DOS disks.

## Implemented

`tools/build_live.py` builds a bootable live-graphics disk using the M01
three-CPU compatible-mode scheduler and native custom-I/O protocols, with
the [packed dual-screen renderer](NATIVE-PLANES.md). It no longer replays
frozen snapshots: the programs execute and their shared video RAM drives
background, characters, sprites and startup cache generation.

The existing M01 diagnostic disk and all CPU/SGP snapshot probes remain
available. This is an experimental graphics milestone, not a complete game
release. Sound output and all-round compatibility are not implemented or
accepted here. No MCU dump is used by the build/runtime.

## Loading without expansion RAM

The original single-segment payload limit remains F000h to protect the
native stacks. A conditional second IPL read loads transient graphics to
7000:0000, immediately after the sector-padded main payload on disk:

- 2000:0000: native code plus patched program images, 55 sectors loaded.
- 7000:0000: 40357 bytes of lookup tables and RLE source pens.
- Copy the program images into the established Z80 banks 5000/6000.
- Reclaim their original CS staging area, beginning at offset 6000h, for
  native palette/maps/lookups/index/row tables and the 1416-byte video state.
- Expand source pens into 30000h..37FFFh and 40000h..4FFFFh.
- Only after all staging data is consumed may the 70000h bank become the
  512-entry packed cache. No source data is read from it afterwards.

The code and directory fit the existing 24 KiB M01 code reservation. Native
stacks remain at F600h and F800h. No expansion RAM, disk read, BIOS call or
pen expansion occurs in the running renderer. The original boot path is
unchanged when no staged bytes are supplied. ROM-free tests verify sector
placement, primary-sector padding and the one-segment staging limit.

## Native scheduling and VRTC presentation

When all three programs have yielded for the scheduler frame, capture the
shared tile/sprite windows and video latches, mask latch bits and render.
CPU contexts are inactive while reading this shared state. The cache grows
on first use, including startup; no precomputed first-use manifest is loaded.
Global screen flip remains unsupported: such a state is rejected and counted,
not silently presented as an unflipped image.

Presentation differs from the frozen-state probe. A completed front page is
**queued** for the existing VRTC ISR. The ISR writes DSA, records the displayed
page, changes the next write target and clears the pending flag. It never
converts pixels, calls a BIOS, waits for SGP or runs the scheduler. Until
that commit, the completed back page is immutable and new render attempts
are skipped. Rendering waits synchronously for its SGP list before queuing.
Background-only changes may retain the displayed front without a swap.

This avoids blocking the game while waiting for a display boundary. It also
prevents accidentally reusing a front that has not yet been presented.
The scheduler's existing VRTC handler remains installed; graphics setup does
not replace it with the standalone probe's counter-only handler.

`--render-period N` controls attempts in **scheduler frames**, 1..8. Default
is 2: a provisional at-most-every-second-frame rendering policy, not a fixed
30 Hz or a 60 Hz game-execution claim. Period 1 remains available for budget
experiments. The single background page can still tear during updates;
SGP contention, actual frame cadence and VA/VA2 behavior need hardware tests.

## CALLN native-entry race fixed

A long live run initially stopped progressing. A diagnostic emulator trace
showed VRTC interrupting native yield bookkeeping on the fixed compatible
return stack. Returning there can be mistaken for a compatible return in
the emulator. The native entry handlers now execute CLI before saving or
processing the context: `yield_h`, `io_step` and `io_done`. Their saved
CALLN frames retain the original compatible PSW, so eventual IRET restores
its interrupt state. Normal native scheduler work still uses NATIVE_TOP.

This change affects the shared M01 scheduler and requires regression testing,
not just a graphics check. All four M01 compatible-mode probes pass for both
explicit program revisions: CALLN registers/flags, context switching, VRTC
preemption and block-transfer P/V. These are emulator results; they do not
establish the exact hardware cause or replace a VA regression run.

## Live verification

`tools/check_live.py` builds an automatic-input diagnostic disk, runs the
actual programs and exports each sampled render's **paired video snapshot**
to otherwise unused GVRAM at 30000h. The checker reconstructs that state and
requires host-composed indices to match the selected packed front over G1.
All other unused GVRAM bytes retain canaries. Sample ordinals, scheduler
frames, cache counts and the selected page are checked from registers and
metadata. The export is outside renderer-clock measurements but consumes
time in the diagnostic run. It is disabled in normal disks.

This verifies live composition, **not lockstep execution against MAME**.
Game frames need not correspond to same-numbered reference-emulator frames.
Instantaneous swap-event screenshots are observation-only, not paired final
RGB oracles. Full RGB comparisons remain covered by the snapshot tests.
`--no-export` checks production-path liveness/registers/GVRAM guards only;
it explicitly performs no host pixel comparison.

Primary revision:

- Period 1: 1500 renderer updates reached scheduler frame 2443; all seven
  sampled states matched host pixels. This crosses the former stall point.
- Period 2: 3000 updates reached scheduler frame 6297; all twelve sampled
  states matched host pixels. The final observed cache has 163 keys.
- The no-export period-2 path also reached 3000 updates / scheduler frame
  6297, with GVRAM guards intact. Its observed cache has 165 keys: removing
  diagnostic work changes timing and therefore the later game/input path.

Explicit rev2 programs also ran period 2 through 900 updates / scheduler
frame 2097 with five matching samples. A merged archive may hold both
revisions, so `--revision rev2` is now explicit in build/check tools; default
selection remains the first complete revision, normally the primary one.
An earlier run without the explicit selector was rev1, not rev2 evidence.

51 ROM-free tests pass, including staged-loader/export/revision selection.
Earlier consecutive snapshot/damage/fallback and full-capacity packed-source
tests remain applicable; the standalone rendering path is retained.

## Budget observations, not speed acceptance

Some live updates are much heavier than the earlier narrow snapshot interval:

| Period-2 diagnostic sample | Renderer clocks | Context |
|---|---:|---|
| First complete composition | 3409137 | initial background construction |
| Update 100 | 123620 | warm sprites; six cleared cells |
| Update 300 | 198960 | warm sprites; 26 cleared cells |
| Update 900 | 143300 | warm sprites; 30 cleared cells |
| Unchanged samples | 8356 | state comparison and cache bookkeeping |

The old 60-frame test's maximum must not be used as a live worst-case bound.
At about 133460 clocks/display frame, a 198960-clock render alone exceeds
a frame, before game work. Large scene/character changes can cost millions.

The no-export period-2 run at frame 6297 reports 206 scheduler-lost VRTCs
and 1459 late/preempted scheduler frames. These counters include startup
and are not equivalent to dropped pictures or a measured frame rate.
The diagnostic export run reports 242/1167 respectively, confirming that
instrumentation affects execution. The scheduler does not automatically
run a separate catch-up game tick for each lost VRTC. **Full-rate game
speed is therefore not accepted**, even though the programs and display
continue running. More cadence/combined-budget work remains.

## Reproduction

```
DD_ROMS=PATH python3 -I tools/build_live.py
DD_ROMS=PATH python3 -I tools/build_live.py --auto --output build/m02-live-auto.d88
DD_ROMS=PATH python3 -I tools/check_live.py --render-period 2 --vaeg EXE --bios DIR
DD_ROMS=PATH python3 -I tools/check_live.py --no-export --render-period 2 --vaeg EXE --bios DIR
DD_ROMS=PATH python3 -I tools/check_m01_probes.py --vaeg EXE --bios DIR
```

For merged verification inputs, add `--revision rev2` to select that revision.
`--samples` specifies increasing renderer-update ordinals, not game frames.
All generated disks, capture exports, traces and images remain private under
ignored build/. No public repository or remote is updated.

## Maintainer hardware gate

Prepared local disks:

- `build/m02-live.d88`: manual controls, default period 2, no diagnostic export.
- `build/m02-live-auto.d88`: scripted coin/start/moves, period 2, no export.
- `build/m02-native-planes.d88`: deterministic snapshot display comparison.
- `build/m01-regression.d88`: auto-boot compatible-mode regression probes.

Use 15 kHz; reset between disks. Manual keys are cursor keys or keypad
8/6/2/4, SPACE or keypad 0 for action, 5 for credit and 1 for start; ESC
resets. The automatic sequence keys off scheduler frames, so visible delays
are not wall-clock guarantees. No audio is expected. Initial scene rebuilding
can pause the picture. Report machine model, boot/RAM-check behavior, credit/
start/controls, sprite transparency/flips, flicker, hangs and sustained speed.
VA2 remains untested. These user-asset disks must not be redistributed.

M02 now has a live software candidate. It is **not marked complete** until
the hardware display/SGP gates and agreed combined-speed/pacing criteria
have been met. Text/external-character optimization and sound are separate
work; successful vaeg execution alone is not hardware acceptance.
