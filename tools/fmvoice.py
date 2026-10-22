# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""FM profiles: fast additive analysis or expensive offline nonlinear fitting.

ROM-derived profiles/cache/reports stay under ignored build/. The target
performs no optimization search. Both formats are 8 waves x 2 ranges x 9 bytes.
"""

import hashlib
import json
import math
from pathlib import Path
import time

PROFILE_BYTES = 144
CARRIERS = (8,8,8,8,10,14,14,15)
ATTENUATION = (127,31,23,19,15,13,11,9,7,6,5,4,3,2,1,0)


def validate(profiles):
    if len(profiles) != PROFILE_BYTES:
        raise ValueError('FM profiles must contain 16 nine-byte voices')
    for offset in range(0,PROFILE_BYTES,9):
        p = profiles[offset:offset+9]
        if p[0] > 63 or any(p[i] > 15 or p[i+1] > 127 for i in (1,3,5,7)):
            raise ValueError('FM profile has invalid algorithm/multiplier/level')
    return bytes(profiles)


def additive(prom):
    if len(prom) != 256:
        raise ValueError('waveform PROM must be 256 bytes')
    out = bytearray()
    for wave in range(8):
        values = [v&15 for v in prom[wave*32:(wave+1)*32]]
        mean = sum(values)/32
        amplitudes = []
        for harmonic in range(1,16):
            real = sum((v-mean)*math.cos(2*math.pi*harmonic*n/32) for n,v in enumerate(values))/16
            imag = sum((v-mean)*math.sin(2*math.pi*harmonic*n/32) for n,v in enumerate(values))/16
            hold = math.sin(math.pi*harmonic/32)/(math.pi*harmonic/32)
            amplitudes.append((math.hypot(real,imag)*hold/7.5,harmonic))
        selected = sorted(amplitudes,reverse=True)[:4]
        scale = max(1.0,sum(a for a,h in selected))
        profile = bytearray([7])  # four independent carriers, no feedback
        for amplitude,harmonic in selected:
            level = 127 if amplitude < 1e-12 else max(0,min(127,round(-20*math.log10(amplitude/scale)/0.75)))
            profile.extend((harmonic,level))
        out.extend(profile*2)    # identical low/high profiles in the cheap path
    return validate(out)


def generate(prom, mode, cache_root):
    if mode not in ('fm-lite','fm-fit'):
        raise ValueError('unknown FM mode')
    import fmfit                # its VERSION changes the fitted voices
    key = hashlib.sha256(f'DDFM-4-{fmfit.VERSION}'.encode()+b'\0'+mode.encode()+prom).hexdigest()
    cache_root.mkdir(parents=True,exist_ok=True)
    binary = cache_root/(key+'.bin')
    report = cache_root/(key+'.json')
    if binary.exists() and report.exists():
        return validate(binary.read_bytes())
    started = time.monotonic()
    costs = []
    if mode == 'fm-lite':
        profiles = additive(prom)
    else:
        profiles = validate(fmfit.fm_voices(prom,lambda w,r,d,a,f,m,t: costs.append({'wave':w,'range':r,'distance':d})))
    binary.write_bytes(profiles)
    report.write_text(json.dumps({'mode':mode,'version':fmfit.VERSION,'source_sha256':hashlib.sha256(prom).hexdigest(),
                                 'build_seconds':time.monotonic()-started,'fit_costs':costs},indent=2)+'\n')
    return profiles


def check_registers(source, registers, keys, profiles, fitted=False):
    from sound import decode
    validate(profiles)
    if len(registers) != 256 or len(keys) != 3:
        raise ValueError('invalid FM export size')
    if any(registers[8:11]):
        raise ValueError('SSG must be silent in FM mode')
    active = 0
    for channel, voice in enumerate(decode(source)):
        on = bool(voice.frequency and voice.volume)
        if keys[channel] != int(on):
            raise ValueError(f'FM voice {channel} key differs')
        if not on:
            continue
        active += 1
        wanted = pitch(voice.frequency, fitted)
        actual = registers[0xa0+channel] | ((registers[0xa4+channel]&63) << 8)
        if actual != wanted:
            raise ValueError(f'FM voice {channel} pitch differs: {actual} != {wanted}')
        profile_index = voice.waveform*2 + int(fitted and voice.frequency >= 6292)
        profile = profiles[profile_index*9:profile_index*9+9]
        if registers[0xb0+channel] != profile[0]:
            raise ValueError('FM algorithm/feedback differs')
        carrier = CARRIERS[profile[0]&7]
        for op, offset in enumerate((0,8,4,12)):
            level = profile[2+2*op] + (ATTENUATION[voice.volume] if carrier & (1 << op) else 0)
            if (registers[0x30+offset+channel] != profile[1+2*op]
                    or registers[0x40+offset+channel] != min(127,level)):
                raise ValueError(f'FM voice {channel} operator {op} differs')
            for base,value in ((0x50,31),(0x60,0),(0x70,0),(0x80,15),(0x90,0)):
                if registers[base+offset+channel] != value:
                    raise ValueError('FM flat envelope differs')
    return active


def pitch(frequency, exact=False):
    if not 0 <= frequency < (1 << 20):
        raise ValueError('frequency must be 20-bit unsigned')
    value = frequency*45//26 if exact else frequency*443//256
    block = 1
    while value >= 2048:
        value >>= 1
        block += 1
    if block > 7:
        block,value = 7,2047
    return (block << 11)|value
