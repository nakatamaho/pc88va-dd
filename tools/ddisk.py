# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""D88 images of 2HD disks (77 cylinders x 2 heads x 8 sectors of 1024
bytes) as flat sector images: read and write, no other dependency."""

import struct

SECTOR = 1024
PER_TRACK = 8
TRACKS = 154
IMAGE_BYTES = TRACKS * PER_TRACK * SECTOR
HEADER_BYTES = 0x2B0
MEDIA_2HD = 0x20


def read(data: bytes) -> tuple[str, bytes]:
    """(disk name, flat image) from a D88 file; every sector must be present."""
    if len(data) < HEADER_BYTES or data[0x1B] != MEDIA_2HD:
        raise ValueError('not a 2HD D88 image')
    name = data[0:17].split(b'\0', 1)[0].decode('ascii', 'replace')
    size, = struct.unpack_from('<I', data, 0x1C)
    if size != len(data):
        raise ValueError('D88 size field does not match the file')
    image = bytearray(IMAGE_BYTES)
    seen = set()
    for track in range(TRACKS):
        offset, = struct.unpack_from('<I', data, 0x20 + track * 4)
        if offset == 0:
            raise ValueError(f'track {track} is missing')
        for _ in range(PER_TRACK):
            c, h, r, n, count, _, _, _, length = struct.unpack_from('<BBBBHBBB5xH', data, offset)
            if n != 3 or length != SECTOR or not 1 <= r <= PER_TRACK or c * 2 + h != track:
                raise ValueError(f'unexpected sector on track {track}')
            lba = track * PER_TRACK + r - 1
            image[lba * SECTOR:(lba + 1) * SECTOR] = data[offset + 16:offset + 16 + SECTOR]
            seen.add(lba)
            offset += 16 + SECTOR
    if len(seen) != TRACKS * PER_TRACK:
        raise ValueError('sectors are missing or duplicated')
    return name, bytes(image)


def write(name: str, image: bytes) -> bytes:
    if len(image) != IMAGE_BYTES:
        raise ValueError('flat image has the wrong size')
    track_size = PER_TRACK * (16 + SECTOR)
    out = bytearray(HEADER_BYTES)
    raw = name.encode('ascii')[:16]
    out[0:len(raw)] = raw
    out[0x1B] = MEDIA_2HD
    struct.pack_into('<I', out, 0x1C, HEADER_BYTES + TRACKS * track_size)
    for track in range(TRACKS):
        struct.pack_into('<I', out, 0x20 + track * 4, HEADER_BYTES + track * track_size)
    for track in range(TRACKS):
        for record in range(1, PER_TRACK + 1):
            lba = track * PER_TRACK + record - 1
            out += struct.pack('<BBBBHBBB5xH', track // 2, track % 2, record, 3, PER_TRACK, 0, 0, 0, SECTOR)
            out += image[lba * SECTOR:(lba + 1) * SECTOR]
    return bytes(out)
