# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""ROM-free three-voice WSG register decoding and initial SSG approximation.

This models pitch/level only. SSG square waves do not reproduce wavetable
shape, phase, noise or exact amplitude. Frequencies are unsigned 20-bit.
"""

from dataclasses import dataclass

WSG_CLOCK = 96000
SSG_CLOCK = 3993600                 # YM2203: tone = clock / (32 TP)
PERIOD_NUMERATOR = SSG_CLOCK*(1 << 20)//(32*WSG_CLOCK)
VOLUME = (0,6,8,9,10,11,11,12,12,13,13,13,14,14,15,15)


@dataclass(frozen=True)
class Voice:
    frequency: int
    volume: int
    waveform: int


def decode(registers: bytes) -> tuple[Voice, ...]:
    if len(registers) != 32:
        raise ValueError('expected 32 WSG register bytes')
    voices = []
    for voice, end in enumerate((0x14,0x19,0x1e)):
        start = 0x10 if voice == 0 else end-3
        frequency = sum((registers[i]&15) << (4*(i-start)) for i in range(start,end+1))
        if voice:
            frequency <<= 4
        voices.append(Voice(frequency,registers[end+1]&15,registers[5+voice*5]&7))
    return tuple(voices)


def target(voice: Voice) -> tuple[int | None,int]:
    if not 0 <= voice.frequency < (1 << 20) or not 0 <= voice.volume <= 15:
        raise ValueError('voice frequency or volume out of range')
    if not voice.frequency or not voice.volume:
        return None,0
    return max(1,min(4095,PERIOD_NUMERATOR//voice.frequency)),VOLUME[voice.volume]


def check_ssg(source: bytes, registers: bytes) -> int:
    if len(registers) != 16:
        raise ValueError('expected 16 SSG register shadows')
    if registers[7]&63 != 0x38:
        raise ValueError('unexpected SSG tone/noise mixer')
    active = 0
    for i,voice in enumerate(decode(source)):
        period,level = target(voice)
        if registers[8+i] != level:
            raise ValueError(f'SSG voice {i} level differs')
        if period is not None:
            actual = registers[i*2] | ((registers[i*2+1]&15) << 8)
            if actual != period:
                raise ValueError(f'SSG voice {i} period differs: {actual} != {period}')
            active += 1
    return active
