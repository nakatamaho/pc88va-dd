# pc88va-dd

The Game DD: an unofficial port of an arcade game with three Z80 CPUs to
the NEC PC-88VA (VA and VA2). Not affiliated with or endorsed by the
owners of the original game. Two-clause BSD licence (`LICENSE`).

Approach: the three original Z80 programs run unmodified apart from a
build-time patch list, one at a time, in the uPD9002 CPU's uPD780
(Z80-compatible) mode. Native V30-mode code switches between them on the
vertical interrupt and when a program has nothing to do, emulates the
board's custom I/O chips, and handles experimental native graphics and
keyboard input. M03 adds experimental SSG and two optional FM sound paths.

ROM images are not part of this repository. The build reads them from
`$DD_ROMS` (`--roms PATH` instead): the current commercial re-release's
plugin DLL (`Release_0.dll`), its install folder, or a zip file or a
directory holding the ROM files under any names; `tools/roms.py` lists
their sizes and CRC-32s. Two revisions of the main and sub programs are
accepted, among them the one found in the re-release.

Game disks are MS-DOS 4.0 disks (the FreeDOS-88VA project's msdos4-va.2
release) with DD.COM; there are no self-booting game disks. See AGENTS.md,
"Making disks".

## Building

NASM, Python 3, and vaeg's `tools/pc88va/pcengine_disk.py`.

    DD_ROMS=/path/to/Release_0.dll python3 -I tools/build_m03.py --audio fm-fit
                                           # build/m03-fm-fit.d88: MS-DOS, DD

Select 15 kHz before boot. Cursor keys or keypad 8/6/2/4 move, SPACE or
keypad 0 acts, 5 adds credit, 1 starts, ESC resets. F10 opens the service
screen (DIP switches, SSG/FM, sound test). Default rendering attempts are
every second scheduler frame; full-rate speed is not accepted. See
`docs/LIVE-M02.md` for checks, limitations and the VA/VA2 hardware gate.
A merged verification archive can select programs with `--revision rev2`;
default selection prefers the first complete revision.

    python3 -I tools/build_m01.py          # build/m01test.d88: self-booting
                                           # compatible-mode probes (tests only)

M03 sound (SSG is primary; FM remains optional):

    python3 -I tools/build_m03.py                 # build/m03-ssg.d88
    python3 -I tools/build_m03.py --audio fm-lite  # fast additive approximation
    python3 -I tools/build_m03.py --audio fm-fit   # FM voices fitted on the host

FM-fit needs NumPy; generated voices are cached privately. No fitting search
runs on the target CPU. See `docs/M03.md` for model/CPU costs and unverified
sound-quality/hardware gates. M02's live builder remains silent by default.

Distribution (dd-pc88va: an MS-DOS 4.0 disk with DD.COM, no ROM data, and a
PC-side installer, as in the sister port):

    python3 -I tools/build_dist.py                # build/dist/, needs no ROMs
    python3 -I install_roms.py --fit-fm dd-msdos4.d88 Release_0.dll out.d88  # by the user

`install_roms.py` checks the user's ROM files, patches the programs, decodes
the graphics, fits the FM voices (NumPy) and adds them as DDGAME.DAT and
FMVOICE.DAT to a copy of the disk; DD.COM only loads them. See `docs/DIST.md` and
`docs/dist/DD.TXT`.

These disks contain the arcade programs and are never distributed.

    python3 -I tools/check_sub.py --mame PATH --system NAME --rompath DIR

checks the relocated sub program against the original in MAME (NAME is
MAME's name of the ROM set). See `docs/DESIGN.md` and `docs/ROADMAP.md`.
