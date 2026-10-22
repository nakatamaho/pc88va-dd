# Design notes

Short technical notes on how The Game DD runs on the PC-88VA. The ROM
files are the user's own; `tools/roms.py` lists them by size, CRC-32 and
SHA-1.

## M02 screen bring-up

Indexed 8bpp with palette mode 3 retains all 32 source palette entries
on graphics screen 0. Three 320x224 pages use 210 KiB of GVRAM. Host and
native snapshot compositors agree in the emulator; live rendering still
needs dirty-region optimization and scheduler integration. See
[M02](M02.md) for probes, checks, measurements and the open hardware gate.

## The board

- Two revisions of the main and sub programs are supported (`REVISIONS`
  in `tools/roms.py` and `tools/patches.py`); the sound program, graphics
  and PROMs are common. rev1, the one in a current commercial
  re-release, is the main target; the build uses it when both are
  present. The two differ in
  bug fixes and the EAROM routines: main's patch sites from 3900h move by
  8 bytes, sub's code from 1BC0h by 4.

- Three Z80s at 3.072 MHz with private program ROMs at 0000h (main 16 KiB,
  sub 8 KiB, sound 4 KiB) and everything from 6800h shared: sound
  registers (6800h-681Fh), latches (6820h main IRQ enable, 6821h sub IRQ
  enable, 6822h sound NMI disable, 6823h sub and sound out of reset),
  watchdog (6830h), the 06xx interface (7000h data, 7100h control), RAM
  8000h-9BFFh, video latches (A000h-A007h), EAROM (B800h-B840h).
- Main and sub get an IRQ at VBLANK (IM 1); sound gets an NMI twice a
  frame and acts on each (9B3Ch only blocks nesting; docs/SOUND-DRIVER.md).
  M03 and distribution builds do not run the sound program: a native
  driver does its work (docs/SOUND-DRIVER.md). Only main uses the alternate
  registers. No program uses IN/OUT or HALT.
- Busy Z80 cycles per frame measured in MAME (idle loops excluded, 10600
  frames of play): main 17.4k, sub 9.8k, sound 8.0k on average; the sum
  is 35k (0.70 of the 50.7k cycles of a frame), 64k at the 99th
  percentile, 75k at most.

## Address spaces

- Main segment: main program at 0000h-3FFFh, sub program relocated to
  4000h-5FFFh, stubs at 6000h-67FFh, shared RAM and registers as plain RAM
  above. Main and sub see the shared RAM directly.
- Sound segment: sound program at 0000h-0FFFh, stubs at 1000h. Its shared
  RAM (8401h, 8646h, 8657h, 87CFh, 8A01h, 9A80h-9B7Fh in; 6800h-681Fh,
  6822h, 8A01h, 8A40h-8A47h, 9A80h-9B7Fh out; measured in MAME plus the
  addresses its code names) is copied around each of its runs
  (`SOUND_SYNC_*` in `tools/patches.py`).
- The sub program's relocation moves every JP and CALL target and the
  immediates that address its own data (rev2 43, rev1 42); 33 immediates
  in the same range are numbers. Every immediate in 0000h-1FFFh must be
  classified, or the build stops. One word table (EAROM state routines)
  is moved. Its RST 08h runs main's identical routine at 0008h. The rev1
  lists come from rev2's through an alignment of the two programs.
- `tools/check_sub.py` runs the board in MAME with the relocated program
  (main's ROM at 0000h, as on the VA) and compares tile RAM and sprite
  registers with an unmodified run. 30000 frames each, from an empty and
  from a saved EAROM: rev2 identical; rev1 identical but for one frame in
  which a screen update straddles the frame's end (the redirected entries
  cost cycles), the frames before and after it identical.

## Switching

- A program is entered by IRET with a frame built from its saved context
  (PS, PC, a PSW with MD = 0, AL, CX, DX, BX, SI, DI, BP, DS0); it leaves
  by CALLN (a yield or a service) or by the VRTC interrupt, both of which
  push such a frame. The native code therefore always runs inside a
  native call made from compatible mode, where RETI may restore MD = 0;
  BRKEM is used once, to a stub that yields at once.
- Yields: each program's idle loop and its start-up handshake loops call
  CALLN VEC_YIELD (patches). A program that does not yield before the
  next VRTC is preempted; the next frame starts with the program after it.
- Each frame, in the order main, sub, sound: main's and sub's IRQ are
  injected (PC pushed on the Z80 stack, PC = 0038h / 4038h, IE cleared)
  when their latch is set and their saved IE is 1; sound gets two NMIs
  when its latch allows (injected the same way, IE kept). Sound runs with
  IE = 1 (it never uses EI or DI) so that it can be preempted. RETN in the
  NMI routines becomes RET. Sub and sound start from their reset entries
  when 6823h becomes 1.
- 06xx transfers: each `LD (7100h),A` that starts one calls a stub that
  stores the control byte and calls main's own NMI routine (one LDI) until
  the control register is idle again, with CALLN VEC_06XX_STEP before each
  byte and VEC_06XX_DONE at the end. The native code puts a byte read at
  7000h + n or takes a byte written from there. The program's transfer
  queue works unchanged; transfers complete at once.
- 51xx and 53xx are emulated at the protocol level seen in MAME: commands
  01h (coinage, four bytes), 02h (credit mode), 03h/04h (joystick remap),
  05h (switch mode). Credit mode reads credits (BCD), player 1, player 2;
  the players' bytes are FFh until a start is accepted. A player byte is
  the direction (0 up, 2 right, 4 down, 6 left, 8 centre) with bit 5 low
  while the button is held and bit 4 low on a new press. 53xx returns the
  two DIP switch bytes.
- ROM checksums: sub and sound adjust an unused filler byte per 4 KiB
  block. Main has none left; one patched jump per patched block lands in a
  page-aligned NOP sled ending in a JP to the stub, and the landing byte
  is chosen to keep the block's sum.

## M01 results in vaeg

- Probes (`src/m01/m01test.asm`, menu 1): CALLN keeps all registers and
  the flags; two contexts in two segments switched 1000 times by
  CALLN/IRET keep their registers and main's alternate set; two spinning
  contexts preempted by VRTC 20 times each keep the carry and IX; LDI sets
  P/V as a Z80. Compatible mode runs 119k-129k T-states a frame (about
  2.4 times the arcade CPU), also with IX instructions.
- The game (menu 2 or 3) runs, rev2 and rev1: power-on test passed by
  all three programs, coin accepted, play. Load 35% of the frame (native idle loop
  against an empty frame); about 14% of the frames end with main or sub
  preempted in a polling loop.

## M01 results on the PC-88VA

- Probes: all PASS. Compatible mode runs about 127k T-states a frame
  (2.5 times the arcade CPU); vaeg is within 4% for plain code, 10% for
  PUSH IX, 3% for LD A,(IX+d). The PSW saved in compatible mode has bits
  12-14 set on the VA (7047h, 7244h); vaeg saves them clear. MD is 0 in
  both. IRET returns to compatible mode with the frames placed as in vaeg.
- The game (rev1, from the re-release): power-on test passed by the three
  programs, coins counted by the emulated 51xx, load 35-48%, as in vaeg.
  The M01 text view (text BIOS) takes 4-8 frames a refresh on the VA.
  Not yet checked: play after a start. PC-88VA2 not yet run.

## vaeg notes

- vaeg takes an IRET as the return to compatible mode only at the native
  stack position where the last CALLN or interrupt from compatible mode
  pushed its frame. The programs' frames therefore all go to one place
  (SCHED_TOP - 6), the first via BRKEM with SP = SCHED_TOP + 6, and the
  scheduler runs on a stack of its own: an interrupt taken in native code
  at that position would be taken for the return.
- vaeg's trace build fails to compile (`io/subsystem.cpp` calls the
  private `Clock::now()`); a local copy with that argument removed works.
- The M01 text view is meant for 24.8 kHz, where the text screen has 20
  rows.
