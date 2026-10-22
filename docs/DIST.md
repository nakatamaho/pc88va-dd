# dd-pc88va: MS-DOS 4.0 disk and PC-side installation

The distribution follows the sister port's (pk-pc88va) model: an MS-DOS
4.0 disk (the FreeDOS-88VA project's msdos4-va.2 release, MIT licence,
checked by SHA-256) with the game program and no ROM data; the user's ROM
files are checked on a PC and the game data is added to the disk there; FM
voices are fitted on the PC, and the PC-88VA only loads them.

## Flow

1. `tools/build_dist.py` builds, without ROMs, `build/dist/`:
   `dd-msdos4.d88` (MS-DOS 4.0's kept files, `DD.COM`, `DD.TXT`,
   `DDLICENS.TXT`, an `AUTOEXEC.BAT` that runs `DD`), `DD.COM`,
   `install_roms.py` with the modules it uses and vaeg's `pcengine_disk.py`
   (FAT12 writer), `DD.TXT` (`docs/dist/DD.TXT`), `DDLICENS.TXT` and
   `dd-pc88va.zip` of them all.
2. The user runs `python3 -I install_roms.py --fit-fm dd-msdos4.d88
   Release_0.dll OUTPUT.d88`, the same form as the sister port's installer
   (the re-release's plugin DLL, or its install folder, or a zip/directory
   of ROM files). It finds the ROMs by size and CRC-32, checks SHA-1,
   chooses the program revision (rev1 preferred; `--revision`), and prints
   them. In a DLL (`roms._search`) every ROM is searched for, at offsets
   that are multiples of 16 first and then at every offset for anything
   missing; no offsets are assumed, so no extraction step or tool is
   needed. The DLL stores the 18 ROMs as they are.
3. It patches the programs (including the traced sub-program relocation),
   decodes the graphics and builds the tables, as the development builds do.
4. With `--fit-fm` it fits the FM voices on the PC (NumPy); without it the
   disk has SSG only. `--quick-fm` is the additive approximation without
   NumPy; `--fmvoice` reuses an earlier `FMVOICE.DAT`.
5. It adds `DDGAME.DAT` (the programs, then the staged area up to its end)
   and `FMVOICE.DAT` to the root of a copy of the disk, and writes
   FMVOICE.DAT beside it. These are the user's private files.

Unlike the sister port, the payload is built on the PC rather than by the
DOS program: the sub program's relocation uses a Z80 code tracer
(`tools/z80.py`), impractical in V30 code. The user needs Python either way
for FM fitting.

## DD.COM (`src/dos/dd.asm`)

A loader of about 1.5 KiB followed by the 24 KiB game code, assembled
ROM-free (both revisions). It checks 15 kHz, that it is loaded below
segment 2000h and that DOS leaves memory up to 8000h; reads `DDGAME.DAT`
(optionally from `DD directory`): the programs to 2000:6000 and the staged
area to 7000:0000; clears 7000:FC00-FFFF and reads `FMVOICE.DAT` there if
present; copies its game code to 2000:0000 (backwards: its own copy can
overlap the destination, as MS-DOS 4.0 loads it at 1DDCh); and jumps to it
with interrupts disabled. Memory is then exactly as the game code expects
(it was first written for a self-booting IPL, since retired). It never returns; ESC restarts the
machine. Missing or short files return to DOS with a message.

## Memory layout (`tools/ddpayload.py`)

| CPU address | Content | From |
|---|---|---|
| 2000:0000-5FFF | game code (ROM-free, both revisions) | DD.COM |
| 2000:6000-D8FF | patched main/sub and sound segments (30976 bytes) | DDGAME.DAT, first part |
| 7000:0000- | staged area: header, tables, RLE pens | DDGAME.DAT, the rest |
| 7000:FC00-FFFF | FMVOICE.DAT, or zeros | FMVOICE.DAT |

Staged header: magic `DDGA`, version, sizes, offsets of the three RLE
streams, end, revision, CRC-32 of the staged data and of the programs.
FMVOICE.DAT: magic `DDFM`, version, method (1 quick, 2 fit), the waveform
PROM's CRC-32, size 144, CRC-32, then 16 voices x 9 bytes (waveform 0 LOW,
0 HIGH, 1 LOW, ...: FB<<3|ALG, then MUL and TL of operators 1-4).

The assembler definitions need only fixed sizes (`ddpayload.include`) and
the stub symbols, which `patches.static_symbols()` computes without ROMs and
checks across revisions; `install_roms.py` and the development builders
check them against `apply()`. All game disks, development ones included
(`build_live.py`, `build_m03.py`, via `tools/dosdisk.py`), are MS-DOS 4.0
disks with the same two files, so a development FM-fit disk and an
installed disk hold identical DDGAME.DAT and FMVOICE.DAT. The sector
constants in `ddpayload.py` describe the former self-booting layout and are
kept only for its tests; no game disk boots without MS-DOS any more.

## At start (`src/m03/install.inc`)

`install_check` builds a CRC-32 table at 3B00:0000 and checks the staged
header and both CRC-32s before the programs are copied to their Z80 banks.
Without valid data the disk prints that the game data is not installed and
stops. `install_fm` checks FMVOICE.DAT the same way and, when valid, copies
its voices and enables FM in the F10 screen with its method (quick: pitch
F*443/128, one voice for both ranges; fit: exact F*45/13 and LOW/HIGH
voices). With fitted voices the game starts with FM; otherwise (quick or
none) with SSG. No fitting
happens on the PC-88VA. The checks add about half a second to start-up.

## Verification

`tools/check_dist.py --roms SOURCE --dll DLL --vaeg EXE --bios DIR` (and
`--scan-roms` for more reference sets):

- packaged files: text scanned like `publish.py`; `DD.COM` against this
  game's identified ROMs (windows of four or more distinct bytes; zero
  runs with a byte or two match anything); the disk holds MS-DOS's kept
  files and ours only, and its `DD.COM` equals the packaged one. MS-DOS's
  own files are third-party and not scanned. A 16-entry joystick direction
  table in the native code matched only an unrelated file of a merged
  reference archive.
- the disk without game data boots MS-DOS, which runs `DD` (at 1DDCh),
  and `DD` reports the missing `DDGAME.DAT`;
- `install_roms.py` from the unpacked zip with `--fit-fm`, again with
  `--fmvoice` (same files), without an FM option (no FMVOICE.DAT), and from
  the plugin DLL (same files); no `__pycache__` is left in the package;
- `DDGAME.DAT` and `FMVOICE.DAT` equal the development FM-fit build's
  payload sectors;
- the installed disk boots MS-DOS, `AUTOEXEC.BAT` runs `DD`, and the game
  keeps drawing (1220 picture updates by frame 3500; DOS takes about 650
  frames to start the game);
- the installed test variant (TEST_KEYS, LIVE_CAPTURE) passes
  `check_service.py --start 1600`: menu, SSG test, F10 switch to the fitted
  FM voices loaded from `FMVOICE.DAT` with matching registers, DIP restart.

`tools/test_dist.py` covers the layout, static symbols, D88 round trip,
the DLL search, staged header/CRC failures and FMVOICE.DAT validation
without ROMs.

All of this ran in vaeg. VA/VA2 hardware, real floppy writing and a
Windows host are untested. Nothing has been published.
