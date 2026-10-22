# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Build M03 sound modes; default SSG, optional --audio fm-lite or fm-fit.

FM-fit performs expensive offline profile fitting and caches private results.
The live target never performs that search. The M02 builder remains silent
by default, so its reference disk is not accidentally replaced.

M03 enables the measured rendering optimizations by default: composited
background-tile cache, sprite blit coalescing and the hybrid front policy.
Each can be disabled for comparison, e.g. --no-front-hybrid. The F10
service screen (--service), the native sound driver (--native-sound; the
sound program and its NMI catch-up, --no-native-sound --sound-catchup 4,
remain for comparison) and making up overrun frames (--frame-debt 3) are
also on by default.
"""

from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from build_live import main

if __name__ == '__main__':
    main(['--audio','ssg','--background-cache','--coalesce','--front-hybrid','--service','--native-sound','--rect-sprites','--frame-debt','3',*sys.argv[1:]])
