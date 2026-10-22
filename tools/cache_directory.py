# Copyright (c) 2026 Nakata Maho
# SPDX-License-Identifier: BSD-2-Clause
"""Host model of the guest append-only directory; no pixel or ROM data."""


class RetainedCache:
    def __init__(self, capacity=512):
        if not 1 <= capacity <= 512:
            raise ValueError('capacity must be 1..512')
        self.capacity = capacity
        self.tags = [None] * 1024
        self.slots = [None] * 1024
        self.used = 0

    def lookup(self, key):
        """Return (stable pixel slot, inserted, probes); never evict a slot."""
        if not 0 <= key < 32768:
            raise ValueError('key must fit glyph/colour/X-flip fields')
        bucket = (key ^ (key >> 7)) & 1023
        for probes in range(1, 1025):
            if self.tags[bucket] == key:
                return self.slots[bucket], False, probes
            if self.tags[bucket] is None:
                if self.used == self.capacity:
                    raise OverflowError('retained cache capacity exceeded')
                slot = self.used
                self.used += 1
                self.tags[bucket], self.slots[bucket] = key, slot
                return slot, True, probes
            bucket = (bucket + 1) & 1023
        raise OverflowError('retained directory is full')
