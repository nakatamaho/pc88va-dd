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

"""Build-time patches to the arcade game's three Z80 programs.

The three programs run in the uPD9002's Z80-compatible mode, one at a time,
switched by the native code (docs/DESIGN.md):

- main at 0000h-3FFFh of the main segment;
- sub relocated to 4000h-5FFFh of the same segment, so that both see the
  shared RAM at 6800h-FFFFh directly;
- sound at 0000h-0FFFh of a segment of its own; the native code copies
  the shared RAM it uses in and out around each run (SOUND_SYNC_*).

Stubs that the patches call are placed at MAIN_STUBS (main segment) and
SOUND_STUBS (sound segment). A program gives up the processor with CALLN
VEC_YIELD; the 06xx transfers call VEC_06XX_STEP and VEC_06XX_DONE.

Every change is listed below with its reason; no ROM bytes are listed
here. apply() checks the bytes it replaces against the documented
instruction (opcode bytes only) and keeps the programs' own ROM checksums
(main: through the address of one patched jump per block, see SLEDS, or
a byte of a replaced routine, see DEAD_FILLERS; sub and sound: one unused
filler byte per 4 KiB block). The ROM files
themselves are never modified.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roms  # noqa: E402
import z80  # noqa: E402

DEFAULT_ROMS = roms.DEFAULT

# CALLN vectors (native interrupt vectors 40h-7Bh are unused).
VEC_BRKEM = 0x70        # BRKEM entry from the native code
VEC_YIELD = 0x71        # the program has nothing to do until its next interrupt
VEC_06XX_STEP = 0x72    # one byte of a 06xx transfer is about to move
VEC_06XX_DONE = 0x73    # the 06xx transfer has ended
VEC_SPRITE_COPY = 0x74  # main's IRQ copies its sprite RAM (two LDIRs, native)
VEC_SUB_POSITIONS = 0x75  # sub's sprite position copy (0E4Ch, native)
VEC_OBJECTS_A = 0x76    # main's object table copies to sprite RAM (native):
VEC_OBJECTS_B = 0x77    # 1B90h, 1BADh and 16E3h in rev1
VEC_OBJECTS_C = 0x78
VEC_DIGITS = 0x79       # main's six-digit number to tiles (14FDh in rev1, native)
VEC_TEXT10 = 0x7A       # main's 10-byte text copy to 83D4h down (1430h in rev1, native)
VEC_FILL12 = 0x7B       # main's IRQ: 05h to 12 bytes from 9825h (0A52h, native)
VEC_NEAR = 0x7C         # main's distance test of 8 objects (134Ch in rev1, native)
VEC_COPY3 = 0x7D        # main's 3-byte copy (0D54h, native)

SUB_BASE = 0x4000
MAIN_STUBS = 0x6000
MAIN_STUBS_END = 0x6800
SLED_BASE = 0x6200      # two page-aligned sleds, each ending in a JP (SLEDS)
SOUND_STUBS = 0x1000
SOUND_STUBS_END = 0x1100

# Shared RAM the sound program reads (copied in before it runs) and writes
# (copied out after, with the sound registers and latches it writes). Measured with the arcade board emulated, plus the
# addresses its code names directly.
SOUND_SYNC_IN = [(0x8401, 1), (0x8646, 1), (0x8657, 1), (0x87CF, 1),
                 (0x8A01, 1), (0x9A80, 0x100)]
SOUND_SYNC_OUT = [(0x6800, 0x20),       # sound registers
                  (0x6822, 1),          # its NMI latch (not 6820h-6821h: main's, sub's)
                  (0x8A01, 1), (0x8A40, 8), (0x9A80, 0x100)]

# ---------------------------------------------------------------------------
# A minimal assembler for the stubs: items are bytes, ("label", name),
# ("abs", name) for a 16-bit address, ("jr", name) for a relative jump.


def assemble(origin: int, items) -> tuple[bytes, dict[str, int]]:
    labels, pc = {}, origin
    for item in items:
        if isinstance(item, tuple):
            kind = item[0]
            if kind == "label":
                labels[item[1]] = pc
            else:
                pc += 2 if kind == "abs" else 1
        else:
            pc += len(item)
    out = bytearray()
    for item in items:
        if isinstance(item, tuple):
            kind, name = item
            if kind == "abs":
                value = labels[name] if isinstance(name, str) else name
                out += value.to_bytes(2, "little")
            elif kind == "jr":
                disp = labels[name] - (origin + len(out) + 1)
                if not -128 <= disp < 128:
                    raise ValueError(f"JR to {name} out of range")
                out.append(disp & 0xFF)
        else:
            out += item
    return bytes(out), labels


def calln(vector: int) -> bytes:
    return bytes((0xED, 0xED, vector))


def _wait_stub(name: str, address: int):
    """CALLN VEC_YIELD; LD A,(address); RET: replaces the LD A,(address) at
    the head of a polling loop, so that the program yields once a pass."""
    return [("label", name), calln(VEC_YIELD), b"\x3A", ("abs", address), b"\xC9"]


def main_stub_items(rev: "Revision"):
    return [
        # Entry from the native code (BRKEM VEC_BRKEM lands here).
        ("label", "enter"), calln(VEC_YIELD), b"\x18\xFB",          # JR enter
        # Main idle loop (0238h): EI; LD SP,9A00h as the original, then
        # yield once a pass; the pass continues at 023Ch.
        ("label", "main_idle"), b"\xFB\x31\x00\x9A", calln(VEC_YIELD),
        b"\xC3", ("abs", 0x023C),
        # 06xx transfer: replaces LD (7100h),A. Store the control byte, then
        # run the program's own NMI routine (0066h, one LDI per call) until
        # the control register is idle again, with the native code moving
        # each byte between 7000h-70FFh and the emulated custom I/O chips.
        ("label", "io06"), b"\x32\x00\x71", b"\xF5",               # LD (7100h),A; PUSH AF
        ("label", "io06_loop"), b"\x3A\x00\x71", b"\xE6\xE0",       # LD A,(7100h); AND 0E0h
        b"\x28", ("jr", "io06_done"),                               # JR Z,done
        calln(VEC_06XX_STEP), b"\xCD\x66\x00",                      # CALL 0066h
        b"\x18", ("jr", "io06_loop"),
        ("label", "io06_done"), calln(VEC_06XX_DONE), b"\xF1\xC9",  # POP AF; RET
        # Sub idle loop (sub 0078h): LD SP,9A80h; yield; CALL the EAROM
        # state routine; again.
        ("label", "sub_idle"), b"\x31\x80\x9A", calln(VEC_YIELD),
        b"\xCD", ("abs", SUB_BASE + rev.sub_idle_call), b"\x18", ("jr", "sub_idle"),
        *_wait_stub("wait_8a00", 0x8A00),
        *_wait_stub("wait_8a01", 0x8A01),
        # Main IRQ (0295h): the two 128-byte LDIRs (9800h -> 8B80h, 9900h
        # -> 9B80h) are done by the native code, which leaves HL, DE and BC
        # as the LDIRs do; continue at 02AAh.
        ("label", "sprite_copy"), calln(VEC_SPRITE_COPY), b"\xC3", ("abs", 0x02AA),
        # Sub 0E4Ch: the routine that copies the 64 sprite positions
        # (9880h -> 9380h, adjusted for the screen orientation) runs natively,
        # registers as the original at its RET.
        ("label", "sub_positions"), calln(VEC_SUB_POSITIONS), b"\xC9",
        # Main 1B90h: 8 x 2 bytes, 8465h + 8n -> 98BCh + 2n. The native code
        # copies; then the registers the routine leaves: IX, A, B, DE, HL and,
        # through its last ADD HL,DE, the flags (C and the others untouched).
        ("label", "objects_a"), calln(VEC_OBJECTS_A),
        b"\xDD\x21", ("abs", 0x98CC), b"\x3A", ("abs", 0x849E), b"\x06\x00",
        b"\x21", ("abs", 0x849E), b"\x11", ("abs", 0x0007), b"\x19\xC9",
        # Main 1BADh: 8 x 4 bytes from 8529h + 16n: two to 98E4h + 2n, two
        # to 9864h + 2n. Registers as above, with IY.
        ("label", "objects_b"), calln(VEC_OBJECTS_B),
        b"\xDD\x21", ("abs", 0x9874), b"\xFD\x21", ("abs", 0x98F4),
        b"\x3A", ("abs", 0x859C), b"\x06\x00",
        b"\x21", ("abs", 0x859C), b"\x11", ("abs", 0x000D), b"\x19\xC9",
        # Main 16E3h: 8 bytes, 8532h + 16n -> 9964h + 2n; DE last as it
        # pops it.
        ("label", "objects_c"), calln(VEC_OBJECTS_C),
        b"\x3A", ("abs", 0x85A2), b"\x06\x00",
        b"\x21", ("abs", 0x85A2), b"\x11", ("abs", 0x0010), b"\x19",
        b"\x11", ("abs", 0x9974), b"\xC9",
        # Main 14FDh: the three BCD bytes at DE as six digits at 841Dh-8422h,
        # leading zeros blanked, then copied down from IX. The native code
        # does all but the last digit and leaves DE + 3 and HL = 841Dh; IX
        # moves down five here, and the last digit runs as the original
        # (LD A,(HL); CP 8Ch; JR Z; CP 0Ch; JR Z; ADD A,10h; LD (IX+0),A;
        # DEC HL; DEC IX), so that A, B, IX and the flags are its own.
        ("label", "digits"), calln(VEC_DIGITS),
        b"\xD5\x11", ("abs", 0xFFFB), b"\xDD\x19\xD1",           # PUSH DE; IX -= 5; POP DE
        b"\x7E\xFE\x8C\x28\x06\xFE\x0C\x28\x02\xC6\x10",
        b"\xDD\x77\x00\x2B\xDD\x2B\x06\x00\xC9",
        # Main 1430h: 10 bytes of its table (the routine's address + 13h)
        # to 83D4h down. IX = the table for the native copy; then HL, IX,
        # A and B as the routine leaves them (no flags change).
        ("label", "text10"), b"\xDD\x21", ("abs", rev.sites["text10"] + 0x13), calln(VEC_TEXT10),
        b"\x21", ("abs", 0x83CA), b"\xDD\x21", ("abs", rev.sites["text10"] + 0x1D),
        b"\x3A", ("abs", rev.sites["text10"] + 0x1C), b"\x06\x00\xC9",
        # The handlers below leave HL, DE, BC and A as the code they replace
        # (the native BX, DX, CX, AL are these registers; F comes back from
        # the CALLN frame).
        # Main IRQ 0A52h: 05h to 9825h, 9827h, ... 983Bh; continue after
        # the loop.
        ("label", "fill12"), calln(VEC_FILL12), b"\xC3", ("abs", rev.sites["fill12"] + 0x0E),
        # Main 134Ch: for 8 objects, |x - player x| + |y - player y|; at the
        # first below 10 the routine continues at its own code (1393h) with
        # its registers and RAM as there (carry set), else it returns.
        ("label", "near"), calln(VEC_NEAR), b"\xD0",              # RET NC
        b"\xC3", ("abs", rev.sites["near"] + 0x47),
        # Main 0D54h: 3 bytes from HL to DE.
        ("label", "copy3"), calln(VEC_COPY3), b"\xC9",
    ]


SOUND_STUB_ITEMS = [
    # Sound idle loop (00B0h): LD SP,8B80h as the original, then yield.
    ("label", "sound_idle"), b"\x31\x80\x8B", calln(VEC_YIELD),
    b"\x18", ("jr", "sound_idle"),
    *_wait_stub("sound_wait_8a01", 0x8A01),
]


@dataclass
class Patch:
    address: int        # in the program's own address space
    old: bytes          # opcode bytes that must be there (no ROM data)
    new: object         # bytes, or a stub label to CALL/JP
    reason: str


def _call(label):
    return (0xCD, label)


def _jp(label):
    return (0xC3, label)


# Main and sub patches: (site name, original opcode bytes, new, reason);
# the address of each site is per revision (Revision.sites).
MAIN_PATCH_LIST = [
    ("idle", b"\xFB\x31", _jp("main_idle"),
     "idle loop: EI; LD SP,9A00h becomes JP to a stub that also yields"),
    ("io_command", b"\x32\x00\x71", _call("io06"),
     "06xx transfer started by the command routine at 00A1h"),
    ("io_test", b"\x32\x00\x71", _call("io06"),
     "06xx transfer of the power-on test"),
    ("io_service_write", b"\x32\x00\x71", _call("io06"),
     "06xx write of the service mode"),
    ("io_service_read", b"\x32\x00\x71", _call("io06"),
     "06xx read of the service mode"),
    ("nmi_return1", b"\xED\x45", b"\xC9\x00",
     "the 06xx NMI routine is called by the io06 stub: RETN becomes RET"),
    ("nmi_return2", b"\xED\x45", b"\xC9\x00",
     "the 06xx NMI routine is called by the io06 stub: RETN becomes RET"),
    ("wait_sub", b"\x3A\x00\x8A", _call("wait_8a00"),
     "power-on test waits, interrupts disabled, for the sub program"),
    ("wait_sound", b"\x3A\x01\x8A", _call("wait_8a01"),
     "power-on test waits, interrupts disabled, for the sound program"),
    ("sprite_copy", b"\x21", _jp("sprite_copy"),
     "IRQ: the sprite RAM copy (LD HL; LD DE; LD BC; PUSH BC; LDIR; POP BC;"
     " LD HL; LD DE; LDIR) runs natively, 4x faster"),
    ("objects_a", b"\x21", _jp("objects_a"),
     "an object table copy to sprite RAM (8 x 2 bytes, IX) runs natively"),
    ("objects_b", b"\x21", _jp("objects_b"),
     "an object table copy to sprite RAM (8 x 4 bytes, IX and IY) runs natively"),
    ("objects_c", b"\x21", _jp("objects_c"),
     "an object table copy to sprite RAM (8 bytes, DE) runs natively"),
    ("digits", b"\x21", _jp("digits"),
     "the six-digit number routine (BCD to tiles, leading zeros) runs natively"
     " but for its last digit"),
    ("fill12", b"\x21", _jp("fill12"),
     "IRQ: the loop writing 05h to 12 bytes from 9825h runs natively"),
    ("near", b"\x21", _jp("near"),
     "the distance test of 8 objects runs natively up to the first near one,"
     " which continues in the original code"),
    ("copy3", b"\x06", _jp("copy3"),
     "the 3-byte copy routine runs natively"),
    ("text10", b"\x21", _jp("text10"),
     "the 10-byte text copy from its table to 83D4h down runs natively"
     " (its loop, entered from elsewhere too, stays)"),
]

SUB_PATCH_LIST = [
    ("sub_idle", b"\x31\x80\x9A", _jp("sub_idle"),
     "idle loop: LD SP,9A80h becomes JP to a stub that also yields"),
    ("sub_wait_main", b"\x3A\x00\x8A", _call("wait_8a00"),
     "start-up waits, interrupts disabled, for the main program"),
    ("sub_positions", b"\x21", _jp("sub_positions"),
     "the sprite position copy routine (64 pairs, 0E4Ch-0E82h) runs natively"),
]

ROUTINE_REASONS = {"sprite_copy": "IRQ: the sprite RAM copy",
                   "sub_positions": "the sprite position copy routine",
                   "objects_a": "an object table copy to sprite RAM (8 x 2",
                   "objects_b": "an object table copy to sprite RAM (8 x 4",
                   "objects_c": "an object table copy to sprite RAM (8 bytes",
                   "digits": "the six-digit number routine",
                   "text10": "the 10-byte text copy",
                   "fill12": "IRQ: the loop writing 05h",
                   "near": "the distance test of 8 objects",
                   "copy3": "the 3-byte copy routine"}

# Opcode bytes (offset: byte) a replaced routine must hold beyond the
# patched first instruction: a check that the whole routine is the one
# replaced, without listing ROM bytes.
ROUTINE_OPCODES = {
    "sprite_copy": {3: 0x11, 6: 0x01, 9: 0xC5, 10: 0xED, 11: 0xB0, 12: 0xC1, 13: 0x21,
                    16: 0x11, 19: 0xED, 20: 0xB0},
    "sub_positions": {3: 0x11, 6: 0x06, 8: 0x3A, 11: 0xCB, 14: 0x3A, 27: 0x7E, 28: 0x12,
                      29: 0x23, 30: 0x13, 37: 0x10, 39: 0xC9, 40: 0x3E, 42: 0x96,
                      52: 0x10, 54: 0xC9},
    "objects_a": {3: 0x11, 6: 0x06, 8: 0xDD, 9: 0x21, 12: 0x7E, 13: 0xDD, 14: 0x77, 16: 0x23,
                  17: 0xDD, 18: 0x23, 19: 0x7E, 20: 0xDD, 21: 0x77, 23: 0xDD, 24: 0x23, 25: 0x19,
                  26: 0x10, 28: 0xC9},
    "objects_b": {3: 0x06, 5: 0x11, 8: 0xDD, 9: 0x21, 12: 0xFD, 13: 0x21, 16: 0x7E, 17: 0xFD,
                  18: 0x77, 20: 0xFD, 21: 0x23, 22: 0x23, 23: 0x7E, 24: 0xFD, 25: 0x77, 27: 0x23,
                  28: 0xFD, 29: 0x23, 30: 0x7E, 31: 0xDD, 32: 0x77, 34: 0x23, 35: 0xDD, 36: 0x23,
                  37: 0x7E, 38: 0xDD, 39: 0x77, 41: 0xDD, 42: 0x23, 43: 0x19, 44: 0x10, 46: 0xC9},
    "objects_c": {3: 0x11, 6: 0x06, 8: 0x7E, 9: 0x12, 10: 0x13, 11: 0x13, 12: 0xD5, 13: 0x11,
                  16: 0x19, 17: 0xD1, 18: 0x10, 20: 0xC9},
    "digits": {3: 0x06, 5: 0x1A, 6: 0xE6, 8: 0x77, 9: 0x23, 10: 0x1A, 11: 0xCB, 12: 0x3F,
               13: 0xCB, 14: 0x3F, 15: 0xCB, 16: 0x3F, 17: 0xCB, 18: 0x3F, 19: 0x77, 20: 0x23,
               21: 0x13, 22: 0x10, 24: 0x21, 27: 0x06, 29: 0x7E, 30: 0xA7, 31: 0x20, 33: 0x3A,
               36: 0xCB, 37: 0x4F, 38: 0xCA, 41: 0xCB, 42: 0x57, 43: 0xC2, 46: 0x3E, 48: 0xC3,
               51: 0x3E, 53: 0x77, 54: 0x2B, 55: 0x10, 57: 0x21, 60: 0x06, 62: 0x7E, 63: 0xFE,
               65: 0x28, 67: 0xFE, 69: 0x28, 71: 0xC6, 73: 0xDD, 74: 0x77, 76: 0x2B, 77: 0xDD,
               78: 0x2B, 79: 0x10, 81: 0xC9},
    "fill12": {3: 0x06, 5: 0x36, 7: 0x23, 8: 0x23, 9: 0x32, 12: 0x10},
    "near": {3: 0x11, 6: 0x06, 8: 0x22, 11: 0x4E, 12: 0x3A, 15: 0xB9, 16: 0xDA, 19: 0x91, 20: 0x18,
             22: 0xD5, 23: 0x57, 24: 0x79, 25: 0x92, 26: 0xD1, 27: 0x32, 30: 0x2A, 33: 0x23,
             34: 0x4E, 35: 0x3A, 38: 0xB9, 39: 0xDA, 42: 0x91, 43: 0x18, 45: 0xD5, 46: 0x57,
             47: 0x79, 48: 0x92, 49: 0xD1, 50: 0x5F, 51: 0x16, 53: 0x3A, 56: 0x6F, 57: 0x26,
             59: 0x19, 60: 0x7C, 61: 0xA7, 62: 0xC2, 65: 0x7D, 66: 0xFE, 68: 0xD2, 71: 0x2A,
             177: 0x2A, 180: 0x11, 183: 0x19, 184: 0x05, 185: 0xC2, 188: 0xC9},
    "copy3": {2: 0x7E, 3: 0x12, 4: 0x23, 5: 0x13, 6: 0x32, 9: 0x10, 11: 0xC9},
    "text10": {3: 0xDD, 4: 0x21, 7: 0x06, 9: 0xDD, 10: 0x7E, 12: 0x77, 13: 0x2B, 14: 0xDD,
               15: 0x23, 16: 0x10, 18: 0xC9},
}

# Blocks 1000h-2FFFh have no unused bytes: a block holding replaced
# routines keeps its sum through a byte of one of them that is no longer
# reached (block -> site name, offset; nothing branches into the routine).
DEAD_FILLERS = {0x1000: ("objects_a", 3)}

SOUND_PATCHES = [
    Patch(0x00B0, b"\x31\x80\x8B", _jp("sound_idle"),
          "idle loop: LD SP,8B80h becomes JP to a stub that also yields"),
    Patch(0x0074, b"\xED\x45", b"\xC9\x00",
          "the NMI is injected as a call: RETN becomes RET"),
    Patch(0x0318, b"\xED\x45", b"\xC9\x00",
          "the NMI is injected as a call: RETN becomes RET"),
    Patch(0x0695, b"\x3A\x01\x8A", _call("sound_wait_8a01"),
          "start-up waits for the main program"),
]

# The main program's ROM has no unused bytes left in blocks 1000h-2FFFh
# and few elsewhere. Its patches are in blocks 0000h and 3000h; in each,
# one patched jump goes to a sled that ends in a JP to the real stub
# (SLEDS: block -> site name, sled page). The landing byte in the
# page-aligned sled is chosen so that the block keeps its sum. The sled is
# 256 bytes 18h, read from any byte as JR +26 (at most ten taken JRs, 12
# clocks each in vaeg), then SLED_NOPS NOPs that catch every last JR, then
# the JP; a NOP sled cost the idle loop about 900 clocks a frame.
SLEDS = {0x0000: ("idle", SLED_BASE), 0x3000: ("wait_sound", SLED_BASE + 0x200)}
SLED_NOPS = 25          # the last JR (from sled + FEh) lands at most 18h on


def sled_bytes(target: int) -> bytes:
    return b"\x18" * 0x100 + bytes(SLED_NOPS) + b"\xC3" + target.to_bytes(2, "little")

# ---------------------------------------------------------------------------
# Sub program relocation, 0000h-1FFFh to 4000h-5FFFh.
#
# Every JP and CALL target is moved. Of the 16-bit immediates whose value
# lies in 0000h-1FFFh, those in the pointer list address the program's own
# data and are moved; those in the constant list are numbers (sprite codes,
# counts, counter values) and stay. apply() refuses an immediate in neither
# list. Addresses are of the instruction. The rev1 lists were derived from
# rev2's through an alignment of the two programs (identical up to 1BC0h,
# four bytes on up to the rewritten EAROM routines); the relocation of both
# is checked in MAME with tools/check_sub.py.

SUB_POINTERS_REV2 = {
    0x0117: "demonstration input script",
    0x037C: "sprite table", 0x039D: "sprite table", 0x03A5: "sprite table",
    0x03AD: "sprite table", 0x03B5: "sprite table", 0x03BD: "sprite table",
    0x03C5: "sprite table", 0x03CD: "sprite table",
    0x03E5: "sprite table",
    0x0551: "text", 0x05B6: "sprite table", 0x0629: "sprite table",
    0x0636: "sprite table",
    0x0656: "script", 0x065C: "script", 0x0662: "script", 0x0668: "script",
    0x066E: "script", 0x0674: "script", 0x067A: "script",
    0x07A7: "demonstration input script", 0x07AC: "demonstration input script",
    0x0805: "sprite table", 0x0831: "tile column table", 0x0882: "table",
    0x0A64: "text", 0x0A7D: "text", 0x0AA0: "text", 0x0AC4: "text",
    0x1869: "table", 0x1943: "table",
    0x1B3F: "table", 0x1BBF: "table", 0x1BE3: "table",
    0x1DE8: "jump table",
    0x1E0B: "EAROM defaults", 0x1E19: "EAROM defaults", 0x1E2A: "EAROM defaults",
    0x1EAE: "EAROM data", 0x1F48: "EAROM data",
    0x1F07: "ROM checksum start", 0x1F0B: "ROM checksum values",
}
SUB_CONSTANTS_REV2 = {
    0x0122: "counter 0", 0x0278: "sprite codes", 0x0280: "sprite codes",
    0x028F: "sprite codes", 0x0297: "sprite codes", 0x0360: "BCD 1",
    0x0564: "count", 0x05BC: "count", 0x062F: "count", 0x06AC: "count",
    0x06C3: "row step", 0x0754: "counter 0", 0x07B7: "counter 0",
    0x07D1: "count", 0x080B: "count", 0x082C: "row step", 0x086F: "count",
    0x0A38: "row step", 0x0E3F: "row step", 0x108F: "offset", 0x109B: "offset",
    0x122F: "step", 0x125B: "step", 0x1277: "time", 0x12C3: "step",
    0x1302: "time", 0x186F: "count", 0x1949: "count", 0x1989: "step",
    0x19B4: "row step", 0x1A4C: "time", 0x1BF4: "step", 0x1E30: "count",
}
SUB_POINTERS_REV1 = {
    0x0117: "demonstration input script", 0x037C: "sprite table",
    0x039D: "sprite table", 0x03A5: "sprite table", 0x03AD: "sprite table",
    0x03B5: "sprite table", 0x03BD: "sprite table", 0x03C5: "sprite table",
    0x03CD: "sprite table", 0x03E5: "sprite table", 0x0551: "text",
    0x05B6: "sprite table", 0x0629: "sprite table", 0x0636: "sprite table",
    0x0656: "script", 0x065C: "script", 0x0662: "script", 0x0668: "script",
    0x066E: "script", 0x0674: "script", 0x067A: "script",
    0x07A7: "demonstration input script", 0x07AC: "demonstration input script",
    0x0805: "sprite table", 0x0831: "tile column table", 0x0882: "table",
    0x0A64: "text", 0x0A7D: "text", 0x0AA0: "text", 0x0AC4: "text",
    0x1869: "table", 0x1943: "table", 0x1B3F: "table", 0x1BBF: "table",
    0x1BDF: "table", 0x1DE4: "jump table", 0x1E07: "EAROM defaults",
    0x1E15: "EAROM defaults", 0x1E26: "EAROM defaults", 0x1EAA: "EAROM data",
    0x1F03: "ROM checksum start", 0x1F07: "ROM checksum values",
}
SUB_CONSTANTS_REV1 = {
    0x0122: "counter 0", 0x0278: "sprite codes", 0x0280: "sprite codes",
    0x028F: "sprite codes", 0x0297: "sprite codes", 0x0360: "BCD 1",
    0x0564: "count", 0x05BC: "count", 0x062F: "count", 0x06AC: "count",
    0x06C3: "row step", 0x0754: "counter 0", 0x07B7: "counter 0",
    0x07D1: "count", 0x080B: "count", 0x082C: "row step", 0x086F: "count",
    0x0A38: "row step", 0x0E3F: "row step", 0x108F: "offset", 0x109B: "offset",
    0x122F: "step", 0x125B: "step", 0x1277: "time", 0x12C3: "step",
    0x1302: "time", 0x186F: "count", 0x1949: "count", 0x1989: "step",
    0x19B4: "row step", 0x1A4C: "time", 0x1BF0: "step", 0x1E2C: "count",
}


@dataclass(frozen=True)
class Revision:
    sites: dict            # main and sub patch site name -> address
    sub_idle_call: int     # the EAROM state routine called by sub's idle loop
    sub_entries: tuple     # code reached only indirectly or not at all
    sub_word_tables: tuple  # (address, entries) of code address tables
    sub_pointers: dict
    sub_constants: dict


REVISIONS = {
    "rev2": Revision(
        sites={"idle": 0x0238, "io_command": 0x00AC, "io_test": 0x39AD,
               "io_service_write": 0x3A58, "io_service_read": 0x3A6E,
               "nmi_return1": 0x0096, "nmi_return2": 0x009F,
               "wait_sub": 0x3973, "wait_sound": 0x3980, "sprite_copy": 0x0295, "sub_positions": 0x0E4C,
               "objects_a": 0x1B92, "objects_b": 0x1BAF, "objects_c": 0x16E5, "digits": 0x14FF,
               "text10": 0x1432, "fill12": 0x0A52, "near": 0x134E, "copy3": 0x0D54,
               "sub_idle": 0x0078, "sub_wait_main": 0x1F25},
        sub_idle_call=0x1DDC,
        sub_entries=(0x0000, 0x0038, 0x0066,
                     0x1378, 0x1381, 0x138A,   # three entries of an unused routine
                     0x1E6F),                  # an unused routine
        sub_word_tables=((0x1DF6, 5),),        # EAROM state routines (JP (HL) at 1DF0h)
        sub_pointers=SUB_POINTERS_REV2, sub_constants=SUB_CONSTANTS_REV2),
    "rev1": Revision(
        sites={"idle": 0x0238, "io_command": 0x00AC, "io_test": 0x39A5,
               "io_service_write": 0x3A50, "io_service_read": 0x3A66,
               "nmi_return1": 0x0096, "nmi_return2": 0x009F,
               "wait_sub": 0x396B, "wait_sound": 0x3978, "sprite_copy": 0x0295, "sub_positions": 0x0E4C,
               "objects_a": 0x1B90, "objects_b": 0x1BAD, "objects_c": 0x16E3, "digits": 0x14FD,
               "text10": 0x1430, "fill12": 0x0A52, "near": 0x134C, "copy3": 0x0D54,
               "sub_idle": 0x0078, "sub_wait_main": 0x1F21},
        sub_idle_call=0x1DD8,
        sub_entries=(0x0000, 0x0038, 0x0066,
                     0x1378, 0x1381, 0x138A),  # three entries of an unused routine
        sub_word_tables=((0x1DF2, 5),),        # EAROM state routines (JP (HL) at 1DECh)
        sub_pointers=SUB_POINTERS_REV1, sub_constants=SUB_CONSTANTS_REV1),
}


def patch_list(rev: Revision, items) -> list[Patch]:
    return [Patch(rev.sites[name], old, new, reason) for name, old, new, reason in items]


# One filler byte per 4 KiB block adjusts the block's sum: the last byte of
# the last run of at least 16 FFh bytes outside the traced code.


def _filler(code: bytes, block: int, covered: set[int], avoid=()) -> int:
    best = None
    run = 0
    for a in range(block, block + 0x1000):
        if code[a] == 0xFF and a not in covered and a not in avoid:
            run += 1
            if run >= 16:
                best = a
        else:
            run = 0
    if best is None:
        raise ValueError(f"no filler byte in block {block:04X}h")
    return best


def _put(out: bytearray, patch: Patch, labels: dict[str, int], name: str) -> None:
    a = patch.address
    for site, opcodes in ROUTINE_OPCODES.items():
        if patch.reason.startswith(ROUTINE_REASONS[site]):
            for offset, byte in opcodes.items():
                if out[a + offset] != byte:
                    raise ValueError(f"{name} {a:04X}h+{offset}: not the routine replaced ({patch.reason})")
    if bytes(out[a:a + len(patch.old)]) != patch.old:
        raise ValueError(f"{name} {a:04X}h does not hold {patch.old.hex()} ({patch.reason})")
    if isinstance(patch.new, tuple):
        opcode, label = patch.new
        new = bytes((opcode,)) + labels[label].to_bytes(2, "little")
    else:
        new = patch.new
    out[a:a + len(new)] = new


def _covered(insns) -> set[int]:
    cov = set()
    for insn in insns.values():
        cov.update(range(insn.addr, insn.addr + insn.length))
    return cov


def sub_entries(rev: Revision, sub: bytes) -> list[int]:
    """Entry points for tracing the sub program, its tables' targets included."""
    entries = list(rev.sub_entries)
    for table, count in rev.sub_word_tables:
        entries += [sub[table + 2 * i] | sub[table + 2 * i + 1] << 8 for i in range(count)]
    return entries


def relocate_sub(rev: Revision, sub: bytes, main: bytes) -> bytes:
    """The sub program with every address of its own moved by SUB_BASE."""
    end = len(sub)
    # The sub program's only RST, RST 08h, runs the main program's routine
    # at 0008h-0014h, which must be the same.
    if main[0x0008:0x0015] != sub[0x0008:0x0015]:
        raise ValueError("the RST 08h routines of main and sub differ")
    insns = z80.trace(sub, sub_entries(rev, sub))
    out = bytearray(sub)
    seen = set()
    for addr, insn in sorted(insns.items()):
        if insn.nn_at is None:
            if insn.call and insn.target is not None and insn.target != 0x08:
                raise ValueError(f"sub {addr:04X}h: RST other than 08h")
            continue
        value = insn.nn(sub)
        at = addr + insn.nn_at
        if insn.target is not None:                 # JP / CALL
            if not insn.target < end:
                raise ValueError(f"sub {addr:04X}h: branch out of the program")
            value += SUB_BASE
        elif value < end:
            if addr in rev.sub_pointers:
                value += SUB_BASE
            elif addr not in rev.sub_constants:
                raise ValueError(f"sub {addr:04X}h: unclassified immediate {value:04X}h")
            seen.add(addr)
        out[at:at + 2] = value.to_bytes(2, "little")
    unused = (set(rev.sub_pointers) | set(rev.sub_constants)) - seen
    if unused:
        raise ValueError("listed sites without an immediate: "
                         + " ".join(f"{a:04X}h" for a in sorted(unused)))
    for table, count in rev.sub_word_tables:
        for i in range(count):
            a = table + 2 * i
            value = (out[a] | out[a + 1] << 8) + SUB_BASE
            out[a:a + 2] = value.to_bytes(2, "little")
    return bytes(out)


@dataclass
class Images:
    revision: str
    patches: int            # number of patches (relocation not counted)
    main_segment: bytes     # 0000h-67FFh: main, sub, stubs
    sound_segment: bytes    # 0000h-10FFh: sound, stubs
    symbols: dict[str, int]


def _block_sums(code: bytes) -> list[int]:
    return [sum(code[b:b + 0x1000]) & 0xFF for b in range(0, len(code), 0x1000)]


def apply(revision: str, main: bytes, sub: bytes, sound: bytes) -> Images:
    """Patched images for the programs of REVISION (tools/roms.py)."""
    rev = REVISIONS[revision]
    main_patches = patch_list(rev, MAIN_PATCH_LIST)
    main_stubs, mlabels = assemble(MAIN_STUBS, main_stub_items(rev))
    sound_stubs, slabels = assemble(SOUND_STUBS, SOUND_STUB_ITEMS)
    if MAIN_STUBS + len(main_stubs) > SLED_BASE or \
            SOUND_STUBS + len(sound_stubs) > SOUND_STUBS_END:
        raise ValueError("stubs too large")

    # Main: block b's sum is the byte at 3FFCh + b.
    if _block_sums(main) != list(main[0x3FFC:0x4000]):
        raise ValueError("the main program does not pass its own checksum")
    m = bytearray(main)
    for p in main_patches:
        _put(m, p, mlabels, "main")
    stubs = bytearray(main_stubs)
    for block, (name, sled) in SLEDS.items():
        site = rev.sites[name]
        patch = next(p for p in main_patches if p.address == site)
        target = mlabels[patch.new[1]]
        o = sled - MAIN_STUBS
        sled_code = sled_bytes(target)
        stubs[len(stubs):o + len(sled_code)] = bytes(o + len(sled_code) - len(stubs))
        stubs[o:o + len(sled_code)] = sled_code
        m[site + 1:site + 3] = sled.to_bytes(2, "little")   # land at sled + 0
        b = block // 0x1000
        landing = (main[0x3FFC + b] - _block_sums(m)[b]) & 0xFF
        m[site + 1] = landing
    for block, (name, offset) in DEAD_FILLERS.items():
        f = rev.sites[name] + offset
        b = block // 0x1000
        if not block <= f < block + 0x1000:
            raise ValueError(f"dead filler {f:04X}h outside block {block:04X}h")
        m[f] = (m[f] + main[0x3FFC + b] - _block_sums(m)[b]) & 0xFF
    main_stubs = bytes(stubs)
    if _block_sums(m) != list(m[0x3FFC:0x4000]):
        raise AssertionError("main checksum compensation failed")

    # Sub: block sums are at 1FFEh and 1FFFh.
    if _block_sums(sub) != list(sub[0x1FFE:0x2000]):
        raise ValueError("the sub program does not pass its own checksum")
    covered = _covered(z80.trace(sub, sub_entries(rev, sub)))
    s = bytearray(relocate_sub(rev, sub, main))
    for p in patch_list(rev, SUB_PATCH_LIST):    # the stubs are in the main segment
        _put(s, p, mlabels, "sub")
    for b in range(2):
        f = _filler(sub, b * 0x1000, covered, avoid=range(0x1FFE, 0x2000))
        s[f] = (s[f] + sub[0x1FFE + b] - _block_sums(s)[b]) & 0xFF
    if _block_sums(s) != list(s[0x1FFE:0x2000]):
        raise AssertionError("sub checksum compensation failed")

    # Sound: the sum of the 4 KiB is AAh.
    if _block_sums(sound) != [0xAA]:
        raise ValueError("the sound program does not pass its own checksum")
    covered = _covered(z80.trace(sound, [0x0000, 0x0066]))
    d = bytearray(sound)
    for p in SOUND_PATCHES:
        _put(d, p, slabels, "sound")
    f = _filler(sound, 0, covered)
    d[f] = (d[f] + 0xAA - _block_sums(d)[0]) & 0xFF
    if _block_sums(d) != [0xAA]:
        raise AssertionError("sound checksum compensation failed")

    main_segment = bytearray(MAIN_STUBS_END)
    main_segment[0:0x4000] = m
    main_segment[SUB_BASE:SUB_BASE + 0x2000] = s
    main_segment[MAIN_STUBS:MAIN_STUBS + len(main_stubs)] = main_stubs
    sound_segment = bytearray(SOUND_STUBS_END)
    sound_segment[0:0x1000] = d
    sound_segment[SOUND_STUBS:SOUND_STUBS + len(sound_stubs)] = sound_stubs
    symbols = {
        "VEC_BRKEM": VEC_BRKEM, "VEC_YIELD": VEC_YIELD,
        "VEC_06XX_STEP": VEC_06XX_STEP, "VEC_06XX_DONE": VEC_06XX_DONE,
        "VEC_SPRITE_COPY": VEC_SPRITE_COPY, "VEC_SUB_POSITIONS": VEC_SUB_POSITIONS,
        "VEC_OBJECTS_A": VEC_OBJECTS_A, "VEC_OBJECTS_B": VEC_OBJECTS_B,
        "VEC_OBJECTS_C": VEC_OBJECTS_C, "VEC_DIGITS": VEC_DIGITS, "VEC_TEXT10": VEC_TEXT10,
        "VEC_FILL12": VEC_FILL12, "VEC_NEAR": VEC_NEAR, "VEC_COPY3": VEC_COPY3,
        "Z80_ENTER": mlabels["enter"],
        "SUB_RESET": SUB_BASE, "SUB_IRQ": SUB_BASE + 0x0038,
        "MAIN_IRQ": 0x0038, "SOUND_NMI": 0x0066,
        "MAIN_SEGMENT_BYTES": len(main_segment),
        "SOUND_SEGMENT_BYTES": len(sound_segment),
    }
    count = len(MAIN_PATCH_LIST) + len(SUB_PATCH_LIST) + len(SOUND_PATCHES)
    return Images(revision, count, bytes(main_segment), bytes(sound_segment), symbols)


def static_symbols() -> dict[str, int]:
    """The symbols of apply() computed without ROMs: they depend only on the
    stubs, the same for every revision (checked here and against apply())."""
    found = None
    for rev in REVISIONS.values():
        _, mlabels = assemble(MAIN_STUBS, main_stub_items(rev))
        symbols = {
            "VEC_BRKEM": VEC_BRKEM, "VEC_YIELD": VEC_YIELD,
            "VEC_06XX_STEP": VEC_06XX_STEP, "VEC_06XX_DONE": VEC_06XX_DONE,
        "VEC_SPRITE_COPY": VEC_SPRITE_COPY, "VEC_SUB_POSITIONS": VEC_SUB_POSITIONS,
        "VEC_OBJECTS_A": VEC_OBJECTS_A, "VEC_OBJECTS_B": VEC_OBJECTS_B,
        "VEC_OBJECTS_C": VEC_OBJECTS_C, "VEC_DIGITS": VEC_DIGITS, "VEC_TEXT10": VEC_TEXT10,
        "VEC_FILL12": VEC_FILL12, "VEC_NEAR": VEC_NEAR, "VEC_COPY3": VEC_COPY3,
            "Z80_ENTER": mlabels["enter"],
            "SUB_RESET": SUB_BASE, "SUB_IRQ": SUB_BASE + 0x0038,
            "MAIN_IRQ": 0x0038, "SOUND_NMI": 0x0066,
            "MAIN_SEGMENT_BYTES": MAIN_STUBS_END,
            "SOUND_SEGMENT_BYTES": SOUND_STUBS_END,
        }
        if found is not None and symbols != found:
            raise AssertionError("stub symbols differ between revisions")
        found = symbols
    return found


def nasm_include_static() -> str:
    """nasm_include() for a ROM-less build (both revisions)."""
    return nasm_include(Images("any revision", 0, b"", b"", static_symbols()))


def nasm_include(images: Images) -> str:
    lines = ["; Generated by tools/patches.py: Z80-side addresses and vectors",
             f"; for the programs' {images.revision}."]
    lines += [f"{k:<20}equ\t{v:#06x}" for k, v in images.symbols.items()]
    for name, ranges in (("SOUND_SYNC_IN", SOUND_SYNC_IN), ("SOUND_SYNC_OUT", SOUND_SYNC_OUT)):
        lines.append(f"%macro {name} 0")
        lines += [f"\t\tSYNC_RANGE\t{a:#06x}, {n:#06x}" for a, n in ranges]
        lines.append("%endmacro")
    return "\n".join(lines) + "\n"
