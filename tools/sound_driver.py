# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Reference model of the sound program's 120 Hz tick (docs/SOUND-DRIVER.md).

`tick(mem)` performs what one sound NMI does, on a 64 KiB image of the
sound CPU's address space: the sound program (its tables) at 0000h, the
shared RAM, the sound registers at 6800h. The driver's state stays at the
program's own addresses (9A80h-9B3Ch), which the main program also reads
and writes, so a native driver keeping them is a drop-in replacement.
No ROM data here: the tables are read from the image.
"""

REQUEST = 0x9A80        # request flags/counters a sound (main and sub write them)
ACTIVE = 0x9A96         # a sound is playing
DURATION = 0x9AAC       # per track: ticks into the current note
POSITION = 0x9ADB       # per track: offset of the current note (2 bytes a note)
TEMPO = 0x9B0A          # per sound: ticks per length unit (copied at reset)
SHADOW = 0x9B20         # 6810h-681Fh image, then waveforms 9B30h-9B32h
COIN_SOUNDS = 0x9B33    # added to the coin sound's counter (main writes it)
CURRENT = 0x9B34        # sound being stepped
TRACK, COUNT, VOICE = 0x9B35, 0x9B36, 0x9B37
ENDED = 0x9B38          # a track of the current sound reached its end mark
NOTE_PTR = 0x9B39       # word
DELAY = 0x9B3B          # countdown between repeats of sound 12h
BUSY = 0x9B3C

# Tables in the program.
T_TRACKS = 0x0700       # word a track: its notes
T_SOUNDS = 0x0754       # 3 bytes a sound: first track, tracks, first voice
T_WAVE = 0x0793         # per track: waveform
T_PITCH_SET = 0x07BD    # per track: pitch table 0, 1 or 2
T_TEMPO = 0x07E7        # 21 bytes, copied to TEMPO at reset
T_ENVELOPE = 0x07FC     # per track: envelope 0, 1, 2 (not read: see step)
T_DECAY = 0x0826        # per track: ticks before the decay of envelope 0
T_END = 0x040D          # word a sound: routine run when it ends
PITCH = (0x0631, 0x064B, 0x0665)    # 13 words each: note 0-12 at the top octave
REST, END_MARK = 0xC0, 0xFF


def rot4(value: int) -> int:
    return ((value >> 4) | (value << 4)) & 0xFF


def word(mem, address: int) -> int:
    return mem[address] | mem[address + 1] << 8


def fill(mem, address: int, count: int, value: int = 0) -> None:
    mem[address:address + count] = bytes([value]) * count


# Routines run when a sound ends (T_END), by address in the program.
def _end_reset(mem, tempo):
    mem[TEMPO + 0x11] = tempo
    mem[0x9AA7] = 0
    fill(mem, 0x9A8A, 9)
    fill(mem, 0x9AA0, 9)


def _end_046e(mem):
    mem[0x9A93] = mem[0x9AA9] = 0
    fill(mem, 0x9A8A, 9)
    fill(mem, 0x9AA0, 9)


def _end_0448(mem):
    for a in (0x9A86, 0x9A89, 0x9A9C, 0x9A9F, 0x9A93, 0x9AA9):
        mem[a] = 0
    _end_reset(mem, 0x10)


def _end_04c6(mem):
    for a in (0x9A86, 0x9A89, 0x9A9C, 0x9A9F):
        mem[a] = 0
    _end_046e(mem)


def _clear(*addresses):
    def routine(mem):
        for address in addresses:
            mem[address] = 0
    return routine


END_ROUTINES = {
    0x0437: _clear(),
    0x0438: _clear(0x9A94, 0x9AAA),
    0x0440: _clear(0x9A8D, 0x9AA3),
    0x0448: _end_0448,
    0x045F: lambda mem: _end_reset(mem, 10),
    0x0463: lambda mem: _end_reset(mem, 12),
    0x046E: _end_046e,
    0x0490: lambda mem: (fill(mem, 0x9A8A, 4), fill(mem, 0x9AA0, 4)),
    0x04AB: lambda mem: (fill(mem, 0x9A8A, 7), fill(mem, 0x9AA0, 7)),
    0x04C6: _end_04c6,
}


def step(mem) -> None:
    """One track (TRACK) of the current sound on voice VOICE (04D5h)."""
    track, voice = mem[TRACK], mem[VOICE]
    mem[DURATION + track] = (mem[DURATION + track] + 1) & 0xFF
    ptr = (word(mem, T_TRACKS + 2 * track) + mem[POSITION + track]) & 0xFFFF
    mem[NOTE_PTR], mem[NOTE_PTR + 1] = ptr & 0xFF, ptr >> 8
    note = mem[ptr]
    volume_at = (0x9B25, 0x9B2A)[voice] if voice < 2 else 0x9B2F
    if note == END_MARK:
        mem[volume_at] = 0
        mem[ENDED] = 1
        return
    table = PITCH[min(mem[T_PITCH_SET + track], 2)]
    pitch = word(mem, table + 2 * (note >> 4)) >> (note & 15)
    freq_at = (0x9B21, 0x9B26)[voice] if voice < 2 else 0x9B2B
    low, high = pitch & 0xFF, pitch >> 8
    mem[freq_at:freq_at + 4] = bytes((low, rot4(low), high, rot4(high)))
    duration = mem[DURATION + track]
    if note == REST:
        volume = 0
    else:
        # The program means to test the byte at T_ENVELOPE + track, but tests
        # A after RST 10h, the low byte of that address: track 4 has the
        # decay form, track 5 the attack, all others the 15 - ticks start.
        envelope = (T_ENVELOPE + track) & 0xFF
        if envelope == 1 and duration < 6:
            volume = duration * 2 & 0xFF            # attack
        elif envelope >= 2 and duration < 6:
            volume = ~duration & 0xFF               # 15 - ticks in the low nibble
        else:
            hold = mem[T_DECAY + track]
            if hold == 0 or duration < hold:
                volume = 10
            elif duration - hold >= 10:
                volume = 0
            else:
                volume = 10 - (duration - hold)
    mem[volume_at] = volume
    mem[0x9B30 + voice & 0xFFFF] = mem[T_WAVE + track]
    length = mem[TEMPO + mem[CURRENT]] * mem[ptr + 1 & 0xFFFF] & 0xFF
    if length != duration:
        return
    mem[POSITION + track] = (mem[POSITION + track] + 2) & 0xFF
    mem[DURATION + track] = 0


def _load(mem, sound: int) -> int:
    mem[TRACK], mem[COUNT], mem[VOICE] = mem[T_SOUNDS + 3 * sound:T_SOUNDS + 3 * sound + 3]
    return mem[COUNT]


def _reset_tracks(mem) -> None:
    count = mem[COUNT]
    fill(mem, POSITION + mem[TRACK], count)
    fill(mem, DURATION + mem[TRACK], count)


def _tracks(mem) -> bool:
    """Step every track of the current sound; True if one ended (and clear the mark)."""
    while True:
        step(mem)
        mem[COUNT] = (mem[COUNT] - 1) & 0xFF
        if mem[COUNT] == 0:
            break
        mem[TRACK] = (mem[TRACK] + 1) & 0xFF
        mem[VOICE] = (mem[VOICE] + 1) & 0xFF
    if not mem[ENDED]:
        return False
    mem[ENDED] = 0
    return True


def _end(mem, sound: int) -> None:
    END_ROUTINES[word(mem, T_END + 2 * sound)](mem)


def play(mem, sound: int) -> None:
    """Request-driven sound (0391h): starts if idle, steps, ends."""
    mem[CURRENT] = sound
    _load(mem, sound)
    if mem[ACTIVE + sound] == 0:
        mem[ACTIVE + sound] = 1
        _reset_tracks(mem)
    if not _tracks(mem):
        return
    mem[ACTIVE + sound] = 0
    if sound in (0x00, 0x14):              # counters: one play less
        mem[REQUEST + sound] = (mem[REQUEST + sound] - 1) & 0xFF
        return
    mem[REQUEST + sound] = 0
    _end(mem, sound)


def _finish(mem) -> None:
    if _tracks(mem):
        mem[ACTIVE + mem[CURRENT]] = 0
        _end(mem, mem[CURRENT])


def restart(mem) -> None:
    """Triggered sound (031Ah): (re)starts from its first note."""
    sound = mem[CURRENT]
    mem[ACTIVE + sound] = (mem[ACTIVE + sound] + 1) & 0xFF
    _load(mem, sound)
    _reset_tracks(mem)
    _finish(mem)


def resume(mem) -> None:
    """Triggered sound while playing (034Eh)."""
    _load(mem, mem[CURRENT])
    _finish(mem)


def _triggered(mem, sound: int, request: int) -> bool:
    mem[CURRENT] = sound
    if mem[request]:
        mem[request] = 0
        restart(mem)
        return True
    if mem[ACTIVE + sound]:
        resume(mem)
        return True
    return False


# Request-driven sounds checked first; the first requested one plays (0117h).
FIRST = (0x01, 0x08, 0x02, 0x03, 0x14, 0x07, 0x04, 0x05)


def tick(mem) -> None:
    """One sound NMI (0066h) that is not nested; BUSY is left set."""
    mem[BUSY] = 1
    fill(mem, SHADOW, 16)
    first = True
    if mem[0x8657] & 2:                     # attract mode
        if mem[0x87CF] & 0x10:              # sound off in attract mode
            fill(mem, REQUEST, 0x28)
            _output(mem)
            return
        fill(mem, REQUEST, 10)
        fill(mem, ACTIVE, 10)
        mem[0x9A8E] = mem[0x9AA4] = 0
        fill(mem, 0x9A90, 3)
        fill(mem, 0x9AA6, 3)
        mem[0x9A94] = mem[0x9AAA] = 0
        first = False
    if first:
        if mem[COIN_SOUNDS]:
            mem[REQUEST] = (mem[REQUEST] + mem[COIN_SOUNDS]) & 0xFF
            mem[COIN_SOUNDS] = 0
        for sound in FIRST:
            if mem[REQUEST + sound]:
                play(mem, sound)
                _sound0(mem)
                return
        if mem[REQUEST + 0x11]:
            play(mem, 0x11)
            mem[DELAY] = 0x50
        else:
            mem[DELAY] = (mem[DELAY] - 1) & 0xFF
            if mem[DELAY] == 0:
                mem[DELAY] = 1
                if mem[REQUEST + 0x12]:
                    play(mem, 0x12)
    # 01D0h: triggered sounds 0Fh or else 10h; 0Ah or 0Bh-0Dh; 0Eh
    if not _triggered(mem, 0x0F, REQUEST + 0x0F):
        _triggered(mem, 0x10, REQUEST + 0x10)
    if not _triggered(mem, 0x0A, REQUEST + 0x0A):
        for sound in (0x0B, 0x0C, 0x0D):
            if mem[REQUEST + sound]:
                play(mem, sound)
                break
    _triggered(mem, 0x0E, REQUEST + 0x0E)
    # 027Bh: sounds 09h, 06h, 13h with conditions
    skip_06 = False
    if mem[REQUEST + 0x09]:
        if mem[0x8646] & 1:
            mem[REQUEST + 0x09] = mem[ACTIVE + 0x09] = 0
        else:
            play(mem, 0x09)
            skip_06 = True
    if not skip_06 and mem[REQUEST + 0x06]:
        if mem[0x8646] & 1 or mem[0x8401] & 0x80:
            mem[REQUEST + 0x06] = mem[ACTIVE + 0x06] = 0
        else:
            play(mem, 0x06)
    if mem[REQUEST + 0x13]:
        if mem[0x8657] & 2 or mem[0x8401] & 0x20:
            play(mem, 0x13)
        else:
            mem[REQUEST + 0x13] = mem[ACTIVE + 0x13] = 0
    _sound0(mem)


def _sound0(mem) -> None:
    if mem[REQUEST]:
        play(mem, 0x00)
    _output(mem)


def _output(mem) -> None:
    mem[0x6810:0x6820] = mem[SHADOW:SHADOW + 16]
    mem[0x6805], mem[0x680A], mem[0x680F] = mem[0x9B30], mem[0x9B31], mem[0x9B32]


def reset(mem) -> None:
    """State after the program's start-up (0085h), before the first NMI."""
    fill(mem, 0x8A40, 8)
    fill(mem, REQUEST, 0x100)
    mem[TEMPO:TEMPO + 21] = mem[T_TEMPO:T_TEMPO + 21]
