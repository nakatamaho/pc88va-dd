# AGENTS.md — pc88va-dd

Two-clause BSD licence (`LICENSE`).

Development happens in a private repository that keeps the whole
history. The public repository, pc88va-dd, is a separate directory
holding one commit, made from a snapshot of the private one by
`tools/publish.py` (checks: clean tree, no ROM bytes, no forbidden words
from `../pc88va-dd.names`, a file that is never committed; `--replace`
makes it again as one commit). Push nothing anywhere without the
maintainer's decision.

## What this is

The Game DD: an unofficial port of an arcade game with three Z80 CPUs
(main 16 KiB, sub 8 KiB, sound 4 KiB; `tools/roms.py`) to the NEC
PC-88VA and PC-88VA2. The three original programs run, one at a time, in
the uPD9002's uPD780 (Z80-compatible) mode, switched by native V30-mode
code that also owns the vertical interrupt, video, sound and input. The
sister project pc88va-pk (`../pacman`) does this for a one-CPU board; its
conventions apply here. See `docs/ROADMAP.md`.

## Invariants

- ROM images, ROM bytes and anything derived from them (patched programs,
  converted graphics, disk images, MAME check files) are never committed.
  The build reads `$DD_ROMS` (the re-release plugin DLL, its install
  folder, or a zip or directory of ROM files; `tools/roms.py`).
  `.gitignore` enforces the common cases; check `git status` before every
  commit.
- The repository and everything built from it use the name "The Game DD"
  (DD). The arcade game's name, its characters' names and its makers'
  names appear nowhere: not in files, file names, comments or commit
  messages. ROM files are identified by size, CRC-32 and SHA-1. Tools that
  drive MAME take the ROM set's name as an argument.
- Changes to the Z80 programs are build-time patches in `tools/patches.py`
  with the reason for each; no ROM bytes are listed there. The original ROM
  files are never modified. The sub program's relocation is checked against
  the original in MAME with `tools/check_sub.py`.
- The custom I/O chips (06xx, 51xx, 53xx) are emulated by the native code;
  the build and the disks use no dump of their microcontrollers. Those
  dumps are used only by MAME for the checks.
- The main target is the programs' rev1, as in a current commercial
  re-release (the user's own copy, extracted outside the repository);
  rev2 is kept building and checked.
- Display: 320x224 graphics at 15.98 kHz, the arcade board's raster
  orientation (top of the game on the left).
- Disks: every game disk is an MS-DOS 4.0 disk, as in pc88va-pk: a vanilla
  copy of the FreeDOS-88VA project's MS-DOS 4.0 (release msdos4-va.2,
  `msdos4-pc88va-2hd.d88`, MIT licence, SHA-256 checked; default
  `~/.cache/vaeg/msdos4-va.2/dl/`) with `DD.COM` (`src/dos/dd.asm` around
  the game code), an `AUTOEXEC.BAT` that runs `DD`, and, for a playable
  disk, `DDGAME.DAT` and `FMVOICE.DAT` built from the ROMs on a PC
  (`tools/dosdisk.py`, `tools/ddpayload.py`, `tools/install_roms.py`). No
  self-booting game disks. Self-booting images remain only for isolated
  emulator probes (M01 compatible-mode probes, M02 screen/SGP probes, M03
  sound probes); they are test tools, never handed out.
- FM voices are fitted on the PC (`install_roms.py --fit-fm`, NumPy); the
  PC-88VA only loads and checks FMVOICE.DAT. SSG is the primary sound.
- Targets, in order: the vaeg emulator, then the PC-88VA and PC-88VA2.
  vaeg running a test is not evidence that the hardware does.
- Tools: NASM for V30 code, Python 3 for build scripts, vaeg's
  `tools/pc88va/pcengine_disk.py` for the FAT12 disks. Run Python that
  reads ROM data with `-I`.
- Code, comments, identifiers and committed documents are in English.

## Service screen (F10) and load display (F9)

What both must do (`src/m03/service.inc`, `src/m03/diag.inc`):

- F10 opens the service screen and returns from it. Keys are sampled at
  every VRTC, so no press is lost during a long render.
- While it is open the game is paused: the main and sub programs get no
  time and no interrupts; the sound runs only for the sound test.
- It is drawn by the native renderer in the game's own font and
  orientation; the selected item is shown in the font's second colour.
- Keys: cursor keys or keypad 8 2 select, 4 6 change, RETURN or SPACE
  plays the test sound or adds 10 to the start round. A held direction
  repeats (after 20 frames, then every 2).
- DIP switches: those of the board (coins A and B, lives, bonus, level,
  continue, demonstration sound), in MAME's bit layout; the bonus names
  follow the lives setting. Cabinet and freeze are not offered. A changed
  switch restarts the programs on return as a power cycle does (Z80 RAM
  cleared, custom I/O reset). Settings are not saved.
- SOUND switches SSG and FM at run time; FM only with a valid
  FMVOICE.DAT. TEST plays the 20 sounds the board plays; the game's
  pending requests are saved on open and restored on close.
- ROUND: the round a game starts at, OFF or 1-255, from the next game
  start until DD ends. FPS: 60 (draw every frame, the default) or 30.
- F9, at any time, toggles the load display in the margins, read like
  the game's text, as in the sister ports: left, each over the last 60
  frames after its letter, F game frames, D frames dropped, R pictures
  drawn, T sound ticks, I idle percent (from the idle loop's count of an
  empty frame measured at start, so right on a VA and a VA2); right, in
  hex, K keys, M the 51xx mode, S the sound state. It must cost the game
  nothing measurable when off, and draw at most once a second when on.
- Checked by `tools/check_service.py` with SSG and with FM (screen text,
  composition, DIP changes, test-sound registers, the restart); `--diag`
  (tests) starts with the load display on. Users' description in
  `docs/dist/DD.TXT`, design in `docs/M03.md`.

## Making disks

The ROM source is normally the user's copy of the current commercial
re-release's plugin DLL: for this game `Release_0.dll` (394240 bytes,
CRC-32 AA58DC77; the sister port uses its own `Release_X.dll`). The ROMs are
found inside it by size, CRC-32 and SHA-1, so no extraction step is needed;
its install folder, or a zip/directory of ROM files, works as well.

The distribution and a finished disk, as a user makes it:

    python3 -I tools/build_dist.py            # build/dist/: dd-msdos4.d88 (no ROM data),
                                              # DD.COM, install_roms.py + modules, DD.TXT
    python3 -I build/dist/install_roms.py --fit-fm build/dist/dd-msdos4.d88 \
        /path/to/Release_0.dll build/dd-msdos4-roms.d88
    python3 -I tools/build_dist.py --with-roms /path/to/Release_0.dll   # the same in one step

Development disks with options (MS-DOS too; the game data is built here):

    DD_ROMS=/path/to/Release_0.dll python3 -I tools/build_m03.py --audio fm-fit
                                              # build/m03-fm-fit.d88; also ssg, fm-lite
    DD_ROMS=... python3 -I tools/build_m03.py --auto --output build/m03-auto.d88
    DD_ROMS=... python3 -I tools/build_live.py   # M02 options, silent by default

Test variants add `--test-keys` (M = F10, P = play, U D L R) and
`--capture-state` (diagnostic export); never hand those out. Checks:
`tools/check_dist.py --roms SRC --dll DLL`, `tools/check_service.py`,
`tools/check_live.py` (vaeg, `--vaeg EXE --bios DIR`). In vaeg, MS-DOS takes
about 650 frames before DD shows the game; select 15 kHz
(`Monitor15kHz=true`).

Every disk and FMVOICE.DAT made with ROMs is private: never commit or
distribute them. Nothing is pushed or published without the maintainer.

## Reference material

- `../pc88va-private-docs/tekumani/` — PC-88VA technical manuals.
- `../vaeg/docs/modernization/upd9002-upd70008-mode.md` — the CPU's
  Z80-compatible mode: mode switching, interrupts, register mapping.
- `../pacman/docs/DESIGN.md` — the one-CPU port's design and measurements.
- MAME's description of the board (driver and the custom I/O chips) for
  the memory map, latches and the 06xx/51xx/53xx protocol.

## How work is organized

Work goes in milestones on a branch `topic/mNN-<name>` with commit prefix
`MNN:`; each ends at a maintainer gate on the hardware. Keep the public
documents short and technical: `docs/ROADMAP.md` gets one line a
milestone, `docs/DESIGN.md` the design; no descriptions of the game's
content.
