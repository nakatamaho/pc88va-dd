# Roadmap

| Milestone | Content | State |
|---|---|---|
| M01 | Feasibility: three programs switched in compatible mode, probe disk | VA probes and credit handling observed; play and VA2 unverified |
| M02 | Graphics at 320x224, 15.98 kHz | live candidate confirmed in emulator; hardware gate deferred by maintainer, not passed; combined-speed/pacing acceptance open |
| M03 | Sound: primary SSG, optional FM-lite / FM-fit; F10 service screen; dd-pc88va MS-DOS 4.0 disk (DD.COM) with PC-side install and FM fitting | checked in vaeg; accepted by the maintainer on the machine (play, sound, service screen, load display; 2026-10-22, v0.1) |

Details in `docs/DESIGN.md`, `docs/M02.md`, `docs/LIVE-M02.md`, `docs/M03.md` and `docs/DIST.md`.

Next candidates: sound listening/volume tuning, live frame-budget/cadence
improvements, broader input/state coverage and an MS-DOS disk with run-time
ROM loading. The deferred VA/VA2 display, SGP and sound gates remain open.
