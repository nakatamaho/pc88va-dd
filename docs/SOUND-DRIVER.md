# Native sound driver

The sound program runs as the third Z80 program. In the heaviest measured
round-100 stretch it took 26.0% of a frame (17.8% on average in play),
more than rendering (19.1%) or the main program (18.5%) (docs/M03.md,
"High rounds"). Most of that is the cost of running it at all: switching
to it twice a frame, copying its shared RAM in and out around each run
(`SOUND_SYNC_*`, 261 bytes in, 298 out), injecting its NMIs and emulating
it in compatible mode, for a small amount of work. This document describes
the program and proposes replacing it by native V30 code.

## The program (4 KiB, both revisions)

Disassembled from the user's ROM for this study only (no listing is kept
in the repository). Addresses below are the program's.

- Start-up (0000h, 0085h): checksum of its 4 KiB, then the handshake with
  main: it writes FFh to 8A01h (06h and stops if the sum is wrong) and
  waits until main has cleared it. Main had cleared 8A01h, written 1 to
  6822h (NMI off) and released the reset (6823h); it waits for FFh and
  clears it. Then the program clears 8A40h-8A47h and 9A80h-9B7Fh, copies 21
  tempo bytes (07E7h) to 9B0Ah, enables its NMI (6822h = 0) and idles.
- Tick (NMI 0066h): every NMI, 120 Hz (MAME: scanlines 64 and 192). 9B3Ch
  only blocks nesting. A tick clears the register image 9B20h-9B2Fh, goes
  through the requests in a fixed priority order, steps the sounds that
  play, and copies the image to 6810h-681Fh and the three waveforms
  (9B30h-9B32h) to 6805h, 680Ah, 680Fh. Later sounds in the order
  overwrite earlier ones' voices.
- Requests: one byte a sound, 9A80h + n for the 21 sounds 00h-14h, written
  by main (and sub: 91h, 89h, 86h, 93h; main also reads 81h, 82h, 87h and
  94h back to wait for an end). Sounds 00h (coin; 9B33h, written by main,
  is added to it) and 14h are counters: each end plays one less. 9A96h + n
  marks a sound as playing.
- Kinds of sounds: request-driven ones play while their request is set and
  clear it at their end (the first requested of 01h, 08h, 02h, 03h, 14h,
  07h, 04h, 05h is played and the tick goes straight to sound 00h; then
  11h/12h with a countdown at 9B3Bh). Triggered ones (0Fh or else 10h, 0Ah,
  0Eh) restart from the first note when requested (the request is cleared
  at once) and play on while 9A96h + n is set. 0Bh-0Dh, 09h, 06h and 13h
  are request-driven with conditions on main's state (8401h bits 5 and 7,
  8646h bit 0, 8657h bit 1).
- Attract mode (8657h bit 1): most requests and playing marks are cleared;
  with 87CFh bit 4 (no sound in attract mode) every request is cleared and
  the tick outputs silence.
- A sound (table 0754h, 3 bytes each): first track, number of tracks,
  first voice; its tracks go to consecutive voices. 42 tracks in all.
- A track (word table 0700h): notes of 2 bytes, pitch then length; FFh
  ends the sound. Pitch: high nibble a note 0-12 in one of three 13-word
  tables (0631h, 064Bh, 0665h; per track at 07BDh), low nibble octaves
  down (a right shift); C0h is a rest. The 16-bit value goes to frequency
  nibbles 1-4 of the voice (nibble 0 is zero). Length: tempo of the sound
  (9B0Ah + n, main sets 9B1Bh at reset and the end routines change it)
  times the length byte, low 8 bits, in ticks. Waveform per track (0793h).
- Volume, by the ticks into the note: a decay form (10 until a per-track
  hold time at 0826h, then down to 0 over 10 ticks), an attack form
  (2 x ticks for 6 ticks) and a "15 - ticks" start (CPL; the WSG uses the
  low nibble) for 6 ticks followed by the decay form. **The program means
  to choose the form from a per-track table at 07FCh but tests the low
  byte of the table address instead** (A after RST 10h): track 4 has the
  decay form, track 5 the attack form, every other track the "15 - ticks"
  start. The replacement must reproduce this, not the table.
- End routines (word table 040Dh, one per sound): clear related requests
  and playing marks, and three of them set the tempo of sound 11h.

## Reference model and check against MAME

`tools/sound_driver.py` models one tick on a 64 KiB image of the sound
CPU's space (state at the program's own addresses; tables read from the
image, no ROM data in the source). `tools/mame/sound_ticks.lua` records
in MAME the state 9A80h-9B7Fh before and after every tick and the four
input bytes; `tools/check_sound_driver.py` replays every tick on the model.

Result (rev1, 4 x 20000 frames: scripted play; with random requests;
with each sound requested in turn every 240 frames, `DD_INJECT=2`; with
the Demo Sounds switch off, `DD_DEMO_OFF=1`): 151848 ticks identical,
none different; 5574 ticks skipped because main or sub wrote the area
during them. All 21 sounds, all 10 end routines and the attract-mode
silence (5066 ticks) occur.

Load: 1.57 tracks stepped a tick on average in play (0 in 49% of ticks,
3 in 45%), at most 5; with random requests 2.9 on average.

## Implementation

`src/m03/sound_driver.inc` (`sd_tick`, `sd_reset`) follows the model
routine by routine, with DS the Z80 segment and ES the sound program's
segment (6000h; the program image is loaded as before and only its
tables are read: the patches and the checksum filler at 0FFEh lie outside
them, the last track ends at 0EEBh). `src/m03/sound_native.inc` connects
it (`--native-sound`, `NATIVE_SOUND`; on in M03 and distribution builds):

- `sound_start_step` (scheduler frame work, interrupts off): when main
  releases the reset (6823h bit 0), 6822h = 1 and 8A01h = FFh as the
  program after its checksum; once main has cleared 8A01h, `sd_reset` and
  6822h = 0. A reset (6823h = 0) or a DIP-switch restart stops it.
- `sound_vrtc` (VRTC handler): two ticks unless 6822h bit 0 is set, then
  `m03_sound_update` (unchanged: it converts 6800h-681Fh to the OPN).
  While the F10 screen is open there are no ticks unless its sound test
  plays. `m03_nmi_delivered` counts the ticks.
- The sound program never runs: no context, stubs, `SOUND_SYNC_*` copies,
  NMI injection or catch-up (`SOUND_CATCHUP` remains for the old path).
- The live game no longer assembles the M01 probes and text view
  (`%ifndef LIVE_VIDEO`; M01 builds keep them): about 3.9 KiB, which makes
  room for the driver (1.2 KiB) in CODE_BYTES.

## Checks

- `tools/check_sound_driver.py --vaeg EXE --bios DIR` runs a selection of
  the recorded states (one of each of 860 kinds of tick: sounds playing,
  requests, end routine, attract flags; then at random) through `sd_tick`
  in a self-booting probe (`src/m03/driver_probe.asm`) and compares each
  result, 9A80h-9B3Ch and 6800h-681Fh, with the model: 3000 of 3000 equal.
  A tick takes 1363 clocks on average, 2761 at most (first 540 timed).
- Live game (vaeg, scripted play, M03 defaults): pictures as before;
  exactly 2.00 ticks a VRTC (11874 in 5937 VRTCs).
- Round-100 worst stretch (`frame_budget.py --start 2993`, FM-fit): the
  sound program's runs took 26.0% of a frame; the driver's ticks now take
  2.6% and the OPN update 1.9%. Idle time 4.9% -> 38.6%; frames without
  idle time 44 of 124 -> 0 of 79.
- Speed windows (as docs/M03.md "High rounds"): round 1 overall 100.0%,
  worst window 99.0%; round 100 overall 100.0%, worst 99.0%; ticks 2.00 a
  VRTC in every window (before: round 100 worst 98.1%, sound 98.1%).
- Regression: service screen (SSG, FM-lite, FM-fit), distribution, M01
  probes (rev1, rev2), live round 100, the old path, check_sound, unit
  tests: all pass.

Not yet done: the two ticks are back to back (the board spaces them by
half a frame; the first tick's registers are not heard); listening on
hardware.

## Design (as proposed before the implementation)

- A native driver in V30 code with the same state at the same addresses
  in the Z80 segment (ZSEG 9A80h-9B3Ch): main and sub keep reading and
  writing requests, 9B1Bh and 9B33h as now; nothing in their programs
  changes. The tables are read from the sound program's image, which
  DDGAME.DAT already holds (the sound segment); the installer and the
  data format do not change.
- Two ticks a VRTC, from the VRTC handler, then the existing conversion
  (`m03_sound_update`: SSG or FM, only voices that changed). As now, both
  ticks are back to back; spacing the second by half a frame with the
  interval timer is possible later. The tempo then follows real time
  even when the game runs late, as on the board, where the sound CPU is
  independent of the others.
- Start-up as the program: when main releases the reset (6823h = 1) the
  driver writes FFh to 8A01h, and once main has cleared it, does the
  start-up clearing and starts ticking; a reset (6823h = 0) stops it and
  silences the voices.
- Removed: the sound program's context and stubs, `SOUND_SYNC_*` copies,
  NMI injection and catch-up (`SOUND_CATCHUP`), `SOUND_PRIORITY`.
- The F10 sound test keeps writing requests (and clearing the attract
  gate meanwhile); OPN access from the scheduler (silence, voice switch)
  must not interleave with the handler's: done with interrupts off.
- Checking: the native tick against the model in vaeg from recorded and
  generated states (all 21 sounds, both pitch sets, all envelope forms,
  ends, attract mode), as `check_sound.py` does for the conversion; then
  the existing live and service checks and listening.

Expected cost: a tick with 3 tracks is a few hundred instructions, about
1-2k clocks; 2 ticks and the register update about 3-5k clocks a frame
(2-4%) against 23.7k-34.7k now (17.8-26.0%).

## For the other games on this hardware

The same board family's other games have their own sound programs, but
the method carries over: disassemble the sound program, write a model
with the state at the program's addresses, check it tick by tick against
MAME with the recorder, then port it to V30 code and check that against
the model. The recorder and checker are generic except for the entry and
end marks of a tick.
