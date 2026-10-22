# Copyright (c) 2026 Nakata Maho
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR "AS IS" AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
# OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
# USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
# THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""FM voices for the WSG waveforms, fitted on a YM2203 model.

The WSG plays 32-sample, 4-bit waveforms, held for a 32nd of the period
each, so besides the waveform's own harmonics 1-15 its output has images
around harmonics 32 and 64 (31, 33, 30, 34, ...), weighted by the hold's
sinc. At low pitches those images are what makes the arcade bass and the
sound effects buzz. For each waveform two voices are fitted:

- LOW, for pitches below LOW_HIGH_HZ: the target is harmonics 1-48 with
  the images;
- HIGH: harmonics 1-16 without them (higher up the images would lie above
  the YM2203's 27.7 kHz Nyquist frequency and alias).

The model follows ymfm's 4-operator channel: operator k outputs
A_k sin(2 pi (MUL_k t + m_k)), A_k = 10^(-0.75 TL_k / 20); a modulator adds
4 x its output to m (in cycles; ymfm adds opout >> 1 to a 10-bit phase);
operator 1's feedback adds (o[n-1] + o[n-2]) x 2^FB / 128. The search
minimises a log-spectral distance (harmonic powers relative to the total,
in dB, floored at -50 dB), trying every algorithm and five feedback levels
from STARTS starting points each and descending over MUL and TL one operator
at a time. The carriers' TL is then shifted so that the voice's RMS level
matches the WSG waveform's (a WSG peak of 7.5 steps = one full-scale
carrier), but never so far that the voice's peak exceeds one full-scale
carrier (ymfm does not clip the YM2203's carrier sum below 32767; whether
the chip does is not known). Phase is not part of the distance: for a steady tone it is
hardly audible, and the YM2203 starts every operator at phase 0 on key-on,
so the fitted voice's waveform shape follows from the modulation.

The voice is checked at the chip's rate. The model renders N samples a
period; the YM2203 runs at 55466 Hz, so at 1.7 kHz only 33 samples a
period. There strong feedback does not settle into a period, and an
operator's sidebands above the chip's Nyquist frequency fold back into the
audible range: both sound as noise (ymfm, at the game's pitches: up to 81%
of a voice's power away from its harmonics). Every local optimum of the
search is kept; the best one (smallest distance) whose channel, rendered
at the chip's rate at pitches spanning its range (STABLE_HZ), has at most
STABLE_PERCENT of its power below 16 kHz away from the harmonics is the
voice. Operator 1's feedback is checked alone during the search already.

MUL 0 (x 0.5) is not used: an operator at half the pitch makes the tone's
period two of the model's periods, and the model, which renders one, does
not see the octave below that it adds (as found in the Pengo port against
ymfm's YM2203).

Output: for each waveform (0-7) and range (LOW, HIGH), 9 bytes:
FB << 3 | ALG (register B0h), then MUL and TL of operators 1-4.

Run as a script to print the voices and their distances. The results are
derived from the ROM; they go onto the disk only (tools/build.py caches
them in build/, which git ignores). This expensive host-only fitting path
is separate from the lightweight additive approximation in fmvoice.py;
no optimization search runs on the target CPU.
"""

import math
import random
import sys
from multiprocessing import Pool

import numpy as np

VERSION = 4
WAVES = 8
SAMPLES = 32
N = 256                       # model samples per period
LOW_HIGH_HZ = 576           # 48 harmonics below the 27.7 kHz Nyquist frequency
LOW_HARMONICS = 48
HIGH_HARMONICS = 16
FLOOR_DB = -50.0
FB_LEVELS = (0, 3, 5, 6, 7)
STARTS = 6
VOICE_BYTES = 9
FM_VOICES_BYTES = WAVES * 2 * VOICE_BYTES

MULS = [0.5] + list(range(1, 16))       # MUL 0 is x0.5
CHIP_RATE = 3993600 / 72      # the YM2203's output rate
# Pitches each range's voices play at (the game's sounds: 47 Hz-4.3 kHz).
STABLE_HZ = {True: (50.0, 150.0, 300.0, 576.0), False: (600.0, 1200.0, 2400.0, 4300.0)}
STABLE_PERCENT = 1.0
# For operators 1-4: the operators modulating it; and the carriers.
ALGORITHMS = {
    0: ([[], [0], [1], [2]], [3]),
    1: ([[], [], [0, 1], [2]], [3]),
    2: ([[], [], [1], [0, 2]], [3]),
    3: ([[], [0], [], [1, 2]], [3]),
    4: ([[], [0], [], [2]], [1, 3]),
    5: ([[], [0], [0], [0]], [1, 2, 3]),
    6: ([[], [0], [], []], [1, 2, 3]),
    7: ([[], [], [], []], [0, 1, 2, 3]),
}
T = np.arange(2 * N) / N


def amplitude(tl: int) -> float:
    return 10 ** (-0.75 * tl / 20)


_op1_cache: dict = {}


def operator1(fb: int, mul: int, tl: int) -> np.ndarray:
    key = (fb, mul, tl)
    if key in _op1_cache:
        return _op1_cache[key]
    a = amplitude(tl)
    m = MULS[mul]
    if fb == 0:
        out = a * np.sin(2 * math.pi * m * T)
    else:
        out = np.zeros(2 * N)
        k = 2 ** fb / 128
        p1 = p2 = 0.0
        for i in range(2 * N):
            v = a * math.sin(2 * math.pi * (m * T[i] + (p1 + p2) * k))
            out[i] = v
            p2, p1 = p1, v
    _op1_cache[key] = out
    return out


_stable_cache: dict = {}


def stable(fb: int, mul: int, tl: int, low: bool) -> bool:
    """Operator 1 with feedback settles into its period at the chip's rate."""
    if fb == 0:
        return True
    key = (fb, mul, tl, low)
    if key in _stable_cache:
        return _stable_cache[key]
    a = amplitude(tl)
    k = 2 ** fb / 128
    ok = True
    for f0 in STABLE_HZ[low]:
        n = 8192
        w = 2 * math.pi * MULS[mul] * f0 / CHIP_RATE
        x = np.zeros(n)
        p1 = p2 = 0.0
        for i in range(n):
            v = a * math.sin(w * i + 2 * math.pi * (p1 + p2) * k)
            x[i] = v
            p2, p1 = p1, v
        if inharmonic(x[n // 2:], f0) > STABLE_PERCENT:
            ok = False
            break
    _stable_cache[key] = ok
    return ok


def inharmonic(x: np.ndarray, f0: float) -> float:
    """Percent of x's power below 16 kHz away from f0's harmonics."""
    x = x - x.mean()
    power = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.arange(len(power)) * CHIP_RATE / len(x)
    h = np.round(f / f0)
    near = (h >= 1) & (np.abs(f - h * f0) < 3 * CHIP_RATE / len(x))
    audible = f < 16000
    total = power[audible].sum()
    return 100 * power[audible & ~near].sum() / total if total > 0 else 0.0


def chip_channel(alg: int, fb: int, muls, tls, f0: float, n: int = 8192) -> np.ndarray:
    """The channel as the model, at the chip's rate (n samples at pitch f0)."""
    modulators, carriers = ALGORITHMS[alg]
    t = np.arange(n) * f0 / CHIP_RATE           # in periods
    a = amplitude(tls[0])
    k = 2 ** fb / 128 if fb else 0.0
    op1 = np.zeros(n)
    p1 = p2 = 0.0
    w = 2 * math.pi * MULS[muls[0]]
    for i in range(n):
        v = a * math.sin(w * t[i] + 2 * math.pi * (p1 + p2) * k)
        op1[i] = v
        p2, p1 = p1, v
    outs = [op1, None, None, None]
    for op in (1, 2, 3):
        mod = sum((outs[j] for j in modulators[op]), np.zeros(n))
        outs[op] = amplitude(tls[op]) * np.sin(2 * math.pi * (MULS[muls[op]] * t + 4 * mod))
    return sum(outs[c] for c in carriers)[n // 2:]


def clean(alg: int, fb: int, muls, tls, low: bool) -> bool:
    return all(inharmonic(chip_channel(alg, fb, muls, tls, f0), f0) <= STABLE_PERCENT
               for f0 in STABLE_HZ[low])


def render(alg: int, fb: int, muls, tls) -> np.ndarray:
    """The last of two periods of the channel's output (N samples)."""
    modulators, carriers = ALGORITHMS[alg]
    outs = [operator1(fb, muls[0], tls[0]), None, None, None]
    for op in (1, 2, 3):
        mod = sum((outs[j] for j in modulators[op]), np.zeros(2 * N))
        outs[op] = amplitude(tls[op]) * np.sin(2 * math.pi * (MULS[muls[op]] * T + 4 * mod))
    return sum(outs[c] for c in carriers)[N:]


def spectrum(y: np.ndarray, harmonics: int) -> np.ndarray:
    return np.fft.rfft(y)[1:harmonics + 1] / (N / 2)


def target(samples, harmonics: int, images: bool) -> np.ndarray:
    """Complex amplitudes of harmonics 1..harmonics of the held waveform,
    in DAC steps."""
    s = np.array(samples, float)
    x = np.fft.fft(s - s.mean()) / (SAMPLES / 2)
    out = np.zeros(harmonics, complex)
    for n in range(1, harmonics + 1):
        k = n % SAMPLES
        if k == 0 or (not images and n >= SAMPLES // 2 + 1):
            continue
        hold = math.sin(math.pi * n / SAMPLES) / (math.pi * n / SAMPLES) if images else 1.0
        out[n - 1] = x[k] * hold * np.exp(-1j * math.pi * n / SAMPLES)
    return out


def levels_db(spec: np.ndarray) -> np.ndarray:
    p = np.abs(spec) ** 2
    p = p / max(p.sum(), 1e-30)
    return np.maximum(10 * np.log10(p + 1e-30), FLOOR_DB)


def distance(spec: np.ndarray, target_db: np.ndarray) -> float:
    weight = np.where(target_db > -30, 1.0, 0.3)
    return float(np.sum(weight * (levels_db(spec) - target_db) ** 2) / np.sum(weight))


def fit(job):
    """Fit one voice: job = (samples, harmonics, images, seed)."""
    samples, harmonics, images, seed = job
    goal = target(samples, harmonics, images)
    if np.max(np.abs(goal)) < 1e-12:
        return 0.0, 7, 0, [1, 1, 1, 1], [127, 127, 127, 127]
    goal_db = levels_db(goal)
    rng = random.Random(seed)

    low = harmonics == LOW_HARMONICS

    def cost(alg, fb, muls, tls):
        if not stable(fb, muls[0], tls[0], low):
            return math.inf
        return distance(spectrum(render(alg, fb, muls, tls), harmonics), goal_db)

    found = []                      # every local optimum: (distance, voice)
    for alg in range(8):
        for fb in FB_LEVELS:
            for _ in range(STARTS):
                muls = [rng.choice((1, 1, 2, 3, 4)) for _ in range(4)]
                tls = [rng.randint(0, 40) for _ in range(4)]
                cur = cost(alg, fb, muls, tls)
                improved = True
                while improved:
                    improved = False
                    for op in range(4):
                        for m in range(1, 16):     # not MUL 0 (see above)
                            if m != muls[op]:
                                trial = muls[:]
                                trial[op] = m
                                d = cost(alg, fb, trial, tls)
                                if d < cur - 1e-6:
                                    cur, muls, improved = d, trial, True
                        for step in (-16, -8, -4, -2, -1, 1, 2, 4, 8, 16):
                            if 0 <= tls[op] + step <= 127:
                                trial = tls[:]
                                trial[op] += step
                                d = cost(alg, fb, muls, trial)
                                if d < cur - 1e-6:
                                    cur, tls, improved = d, trial, True
                if cur < math.inf:
                    found.append((cur, (alg, fb, muls[:], tls[:])))
    found.sort(key=lambda item: item[0])
    for dist, (alg, fb, muls, tls) in found:
        tls = level(alg, fb, muls, tls, goal)
        if tls is not None and clean(alg, fb, muls, tls, low):
            return dist, alg, fb, muls, tls
    # None clean: the fundamental alone (a sine is always clean).
    muls, tls = [1, 1, 1, 1], [0, 127, 127, 127]
    return cost(7, 0, muls, tls), 7, 0, muls, level(7, 0, muls, tls, goal)


def level(alg, fb, muls, tls, goal):
    """The voice's TLs with its carriers shifted to the WSG's level."""
    tls = tls[:]
    # Level: the RMS of the voice against the WSG waveform's, a WSG peak of
    # 7.5 steps being one full-scale carrier.
    want = math.sqrt(np.sum(np.abs(goal) ** 2) / 2) / 7.5
    if want < 1e-12:
        return None
    y = render(alg, fb, muls, tls)
    have = math.sqrt(np.mean(y ** 2))
    shift = max(round(20 * math.log10(have / want) / 0.75),
                math.ceil(20 * math.log10(max(np.max(np.abs(y)), 1e-9)) / 0.75))
    carriers = ALGORITHMS[alg][1]
    shift = max(shift, -min(tls[c] for c in carriers))
    for c in carriers:
        tls[c] = min(127, tls[c] + shift)
    return tls


def jobs(prom: bytes):
    out = []
    for wave in range(WAVES):
        samples = [b & 0x0F for b in prom[wave * SAMPLES:(wave + 1) * SAMPLES]]
        out.append((samples, LOW_HARMONICS, True, wave))
        out.append((samples, HIGH_HARMONICS, False, wave))
    return out


def fm_voices(prom: bytes, report=None) -> bytes:
    """The voices (FM_VOICES_BYTES): waveform 0 LOW, 0 HIGH, 1 LOW, ..."""
    with Pool() as pool:
        results = pool.map(fit, jobs(prom))
    out = bytearray()
    for index, (dist, alg, fb, muls, tls) in enumerate(results):
        if report is not None:
            report(index // 2, "LOW" if index % 2 == 0 else "HIGH", dist, alg, fb, muls, tls)
        out.append(fb << 3 | alg)
        for mul, tl in zip(muls, tls):
            out += bytes((mul, tl))
    assert len(out) == FM_VOICES_BYTES
    return bytes(out)


if __name__ == "__main__":
    from pathlib import Path
    import argparse
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import roms
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roms', type=Path, default=roms.DEFAULT)
    parser.add_argument('--output', type=Path, default=Path('build/fm-fit.bin'))
    args = parser.parse_args()
    prom = roms.load(args.roms, ('waves',))['waves']
    voices = fm_voices(prom, lambda w, r, d, a, f, m, t:
                       print(f'wave {w} {r}: distance {d:.2f}', flush=True))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(voices)
