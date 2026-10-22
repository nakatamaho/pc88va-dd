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

"""A small Z80 instruction decoder for the build-time patches.

Enough of the instruction set to follow a program's control flow and to
find every 16-bit address operand: instruction lengths, the position of a
16-bit operand, branch targets and whether execution falls through. No
mnemonics; tools/audit.py uses the z80dis package for listings.
"""

from dataclasses import dataclass

# Unprefixed opcodes with a 16-bit operand at offset 1.
_NN = {0x01, 0x11, 0x21, 0x31, 0x22, 0x2A, 0x32, 0x3A,
       0xC2, 0xC3, 0xCA, 0xD2, 0xDA, 0xE2, 0xEA, 0xF2, 0xFA,
       0xC4, 0xCC, 0xCD, 0xD4, 0xDC, 0xE4, 0xEC, 0xF4, 0xFC}
# Unprefixed opcodes with an 8-bit operand.
_N = {0x06, 0x0E, 0x16, 0x1E, 0x26, 0x2E, 0x36, 0x3E,
      0xC6, 0xCE, 0xD6, 0xDE, 0xE6, 0xEE, 0xF6, 0xFE, 0xD3, 0xDB,
      0x10, 0x18, 0x20, 0x28, 0x30, 0x38}
# Opcodes that address (HL); with a DD/FD prefix they take a displacement.
_HL_MEM = {0x34, 0x35, 0x36, 0x46, 0x4E, 0x56, 0x5E, 0x66, 0x6E, 0x7E,
           0x70, 0x71, 0x72, 0x73, 0x74, 0x75, 0x77,
           0x86, 0x8E, 0x96, 0x9E, 0xA6, 0xAE, 0xB6, 0xBE}
_JP = {0xC2, 0xC3, 0xCA, 0xD2, 0xDA, 0xE2, 0xEA, 0xF2, 0xFA}
_CALL = {0xC4, 0xCC, 0xCD, 0xD4, 0xDC, 0xE4, 0xEC, 0xF4, 0xFC}
_JR = {0x10, 0x18, 0x20, 0x28, 0x30, 0x38}
_RST = {0xC7, 0xCF, 0xD7, 0xDF, 0xE7, 0xEF, 0xF7, 0xFF}
_ED_NN = {0x43, 0x4B, 0x53, 0x5B, 0x63, 0x6B, 0x73, 0x7B}


@dataclass
class Insn:
    addr: int
    length: int
    nn_at: int | None = None     # offset of a 16-bit operand
    target: int | None = None    # JP/JR/DJNZ/CALL/RST destination
    call: bool = False           # CALL or RST: execution returns
    ends: bool = False           # no fall-through (JP, JR, RET, RETI, RETN, JP (rr))
    indirect: bool = False       # JP (HL), (IX), (IY)

    def nn(self, code: bytes) -> int:
        return code[self.addr + self.nn_at] | code[self.addr + self.nn_at + 1] << 8


def decode(code: bytes, addr: int) -> Insn:
    """The instruction at ADDR (CODE is indexed by address)."""
    op = code[addr]
    if op == 0xCB:
        return Insn(addr, 2)
    if op == 0xED:
        op2 = code[addr + 1]
        if op2 in _ED_NN:
            return Insn(addr, 4, nn_at=2)
        return Insn(addr, 2, ends=op2 in (0x45, 0x4D))
    if op in (0xDD, 0xFD):
        op2 = code[addr + 1]
        if op2 == 0xCB:
            return Insn(addr, 4)
        if op2 in (0x21, 0x22, 0x2A):
            return Insn(addr, 4, nn_at=2)
        if op2 == 0x36:
            return Insn(addr, 4)
        if op2 == 0xE9:
            return Insn(addr, 2, ends=True, indirect=True)
        if op2 in _HL_MEM:
            return Insn(addr, 3)
        if op2 in (0xDD, 0xFD, 0xED):
            raise ValueError(f"{addr:04X}h: unsupported prefix sequence")
        inner = decode(code, addr + 1)
        if inner.nn_at is not None or inner.target is not None:
            raise ValueError(f"{addr:04X}h: prefix on a branch or 16-bit operand")
        return Insn(addr, 1 + inner.length, ends=inner.ends)
    if op in _NN:
        insn = Insn(addr, 3, nn_at=1)
        if op in _JP:
            insn.target = insn.nn(code)
            insn.ends = op == 0xC3
        elif op in _CALL:
            insn.target = insn.nn(code)
            insn.call = True
        return insn
    if op in _N:
        insn = Insn(addr, 2)
        if op in _JR:
            disp = code[addr + 1]
            insn.target = (addr + 2 + disp - (256 if disp & 0x80 else 0)) & 0xFFFF
            insn.ends = op == 0x18
        return insn
    if op in _RST:
        return Insn(addr, 1, target=op & 0x38, call=True)
    if op == 0xC9:
        return Insn(addr, 1, ends=True)
    if op == 0xE9:
        return Insn(addr, 1, ends=True, indirect=True)
    return Insn(addr, 1)


def trace(code: bytes, entries, base: int = 0) -> dict[int, Insn]:
    """Instructions reached from ENTRIES (addresses; CODE starts at BASE).
    Branches out of BASE..BASE+len(CODE) are not followed; CALL and RST
    are taken to return."""
    image = bytes(base) + code + bytes(4)
    end = base + len(code)
    found: dict[int, Insn] = {}
    work = list(entries)
    while work:
        pc = work.pop()
        while base <= pc < end and pc not in found:
            insn = decode(image, pc)
            found[pc] = insn
            if insn.target is not None:
                work.append(insn.target)
            if insn.ends:
                break
            pc += insn.length
    return found
