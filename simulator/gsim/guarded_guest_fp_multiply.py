#!/usr/bin/env python3
"""Independent instruction/PTE/IEEE replay for the default-off guest FP multiplication profile.

The recipe contains inputs, never expected architectural results. This interpreter
runs before reading DUT observations. Raw state samples cover every clock edge;
state interning and sparse zero encoding are lossless, not event filtering.
"""
import argparse
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess

import run as common

from fractions import Fraction

MASK64 = (1 << 64) - 1
NX, UF, OF, NV = 1, 2, 4, 16


def _scale(value, exponent):
    return value * (1 << exponent) if exponent >= 0 else value / (1 << -exponent)


def ieee_multiply(insn, lhs, rhs, frm=0):
    """Return (boxed result, flags), or raise ValueError for illegal encoding/rm.

    Decode IEEE interchange values into exact Fractions, multiply them exactly, then
    choose an adjacent representable magnitude using the architectural mode.
    """
    funct7 = insn >> 25
    if insn & 0x7f != 0x53 or funct7 not in (8, 9):
        raise ValueError('not an FMUL.S/D instruction')
    rm = (insn >> 12) & 7
    rm = frm if rm == 7 else rm
    if rm not in range(5):
        raise ValueError('reserved arithmetic rounding mode')
    single = not (funct7 & 1)
    width, ebits, fbits = (32, 8, 23) if single else (64, 11, 52)
    bias = (1 << (ebits - 1)) - 1
    maxexp = (1 << ebits) - 1
    qnan = (maxexp << fbits) | (1 << (fbits - 1))

    def box(bits):
        return bits | (0xffffffff00000000 if single else 0)

    def decode(raw):
        if single and raw >> 32 != 0xffffffff:
            raw = qnan
        raw &= (1 << width) - 1
        sign = raw >> (width - 1)
        exp = (raw >> fbits) & maxexp
        frac = raw & ((1 << fbits) - 1)
        if exp == maxexp:
            return sign, ('nan' if frac else 'inf'), bool(frac and not (frac >> (fbits - 1))), None
        sig = frac if exp == 0 else (1 << fbits) | frac
        val = _scale(Fraction(sig), (1 - bias if exp == 0 else exp - bias) - fbits)
        return sign, 'finite', False, -val if sign else val

    sa, ka, sna, va = decode(lhs)
    sb, kb, snb, vb = decode(rhs)
    if ka == 'nan' or kb == 'nan':
        return box(qnan), NV if sna or snb else 0
    if (ka == 'inf' and vb == 0) or (kb == 'inf' and va == 0):
        return box(qnan), NV
    sign = sa ^ sb
    if ka == 'inf' or kb == 'inf':
        return box((sign << (width - 1)) | (maxexp << fbits)), 0
    exact = va * vb
    if not exact:
        return box(sign << (width - 1)), 0
    sign = int(exact < 0)
    magnitude = abs(exact)
    # Exact floor(log2(value)), using integer lengths then one rational compare.
    exponent = magnitude.numerator.bit_length() - magnitude.denominator.bit_length()
    if magnitude < _scale(Fraction(1), exponent):
        exponent -= 1
    def round_at(quantum):
        units = _scale(magnitude, -quantum)
        integral, rem = divmod(units.numerator, units.denominator)
        inexact = bool(rem)
        twice = 2 * rem
        increment = ((rm == 0 and (twice > units.denominator or
                      (twice == units.denominator and integral & 1))) or
                     (rm == 4 and twice >= units.denominator) or
                     (rm == 2 and sign and inexact) or
                     (rm == 3 and not sign and inexact))
        return integral + int(increment), inexact

    # IEEE 754 section 7.5: after-rounding tininess uses target precision
    # with an unbounded exponent, before rounding into the subnormal range.
    # Thus a final normal encoding can still signal UF when it is inexact.
    # Independent reference: www.jhauser.us/arithmetic/SoftFloat-3/doc/SoftFloat-FAQ.html
    unbounded, _ = round_at(exponent - fbits)
    tiny = _scale(Fraction(unbounded), exponent - fbits) < _scale(Fraction(1), 1 - bias)
    quantum = max(exponent, 1 - bias) - fbits
    rounded, inexact = round_at(quantum)
    if rounded >= 1 << (fbits + 1):
        rounded >>= 1
        quantum += 1
    rounded_exp = quantum + fbits
    if rounded_exp > bias:
        infinity = rm in (0, 4) or (rm == 2 and sign) or (rm == 3 and not sign)
        bits = (maxexp << fbits) if infinity else ((maxexp << fbits) - 1)
        return box((sign << (width - 1)) | bits), OF | NX
    subnormal = rounded < (1 << fbits)
    expfield = 0 if subnormal else rounded_exp + bias
    bits = (sign << (width - 1)) | (expfield << fbits) | (rounded & ((1 << fbits) - 1))
    return box(bits), (NX | (UF if tiny else 0)) if inexact else 0


MASK = (1 << 64) - 1
CYCLE_LIMIT = 180000
TRACE_LIMIT = 22 * 1024 * 1024
TIMEOUT = 120
SCHEDULES = ('baseline', 'staggered')
MARKER = 'GUARDED_GUEST_FP_MULTIPLY_SUMMARY'
STANDARD_MARKER = 'GUARDED_GUEST_FP_MULTIPLY_STANDARD_PASS'
STATE_COLUMNS = tuple([f'fpr_{n}' for n in range(32)] + [
    'hostFs', 'guestFs', 'fcsr', 'virtualized', 'privilege',
    'hstatus', 'htval', 'htinst', 'scause', 'sepc', 'stval'])


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def unsigned(value, width=64):
    return type(value) is int and 0 <= value < 1 << width


def exact(actual, expected, label):
    need(type(actual) is type(expected), 'type mismatch: ' + label)
    if type(expected) is dict:
        need(set(actual) == set(expected), 'fields mismatch: ' + label)
        for key, value in expected.items():
            exact(actual[key], value, label + '.' + str(key))
    elif type(expected) in (list, tuple):
        need(len(actual) == len(expected), 'length mismatch: ' + label)
        for n, value in enumerate(expected):
            exact(actual[n], value, label + '.' + str(n))
    else:
        need(actual == expected, 'mismatch: ' + label)


def unique_object(pairs):
    row = dict(pairs)
    need(len(row) == len(pairs), 'duplicate JSON field')
    return row


def json_row(text):
    try:
        return json.loads(text, object_pairs_hook=unique_object)
    except ValueError as error:
        raise RuntimeError('malformed JSON evidence') from error


def clean_text(path, limit=TRACE_LIMIT):
    need(path.is_file() and 0 < path.stat().st_size <= limit,
         'missing, empty or excessive evidence: ' + str(path))
    raw = path.read_bytes()
    need(all(n >= 32 or n in (9, 10, 13) for n in raw), 'nontext evidence')
    try:
        result = raw.decode('utf-8')
    except UnicodeDecodeError as error:
        raise RuntimeError('non-UTF8 evidence') from error
    need(result.endswith('\n'), 'truncated evidence')
    need('Sanitizer' not in result and 'runtime error:' not in result,
         'sanitizer failure is not evidence')
    return result


def signed(value, width):
    return value - (1 << width) if value & (1 << (width - 1)) else value


def image(pairs, width, name):
    need(type(pairs) is list, 'invalid ' + name)
    result = {}
    for row in pairs:
        need(type(row) is list and len(row) == 2 and unsigned(row[0]) and unsigned(row[1], width),
             'invalid ' + name + ' item')
        need(row[0] not in result, 'duplicate ' + name + ' address')
        result[row[0]] = row[1]
    return result


class Memory:
    def __init__(self, recipe):
        self.data = image(recipe['bytes'], 8, 'byte')
        self.pages = set(recipe['zero_pages'])
        need(len(self.pages) == len(recipe['zero_pages']) and
             all(unsigned(p) and not p & 4095 for p in self.pages), 'invalid zero pages')
        for address, value in image(recipe['ptes'], 64, 'PTE').items():
            need(not address & 7, 'unaligned PTE input')
            self.put(address, value, 8)
        for address, value in image(recipe['program'], 32, 'program').items():
            need(not address & 3, 'unaligned program input')
            self.put(address, value, 4)
        self.initial = self.data.copy()

    def get(self, address, size):
        need(all(address + n in self.data or (address + n) & ~4095 in self.pages
                 for n in range(size)), 'memory outside frozen image')
        return sum(self.data.get(address + n, 0) << (8*n) for n in range(size))

    def put(self, address, value, size):
        for n in range(size):
            self.data[address + n] = (value >> (8*n)) & 255

    def changed(self):
        return [[a, value] for a, value in sorted(self.data.items())
                if value != self.initial.get(a, 0)]


class PageFault(Exception):
    def __init__(self, guest, address, implicit=False):
        self.guest, self.address, self.implicit = guest, address, implicit


class Translation:
    """Sv39/Sv39x4 from the architectural PTE format, including nested VS reads."""
    def __init__(self, memory):
        self.memory, self.reads = memory, []

    def walk(self, address, root, access, guest=False, implicit=False, g_root=0):
        if root >> 60 == 0:
            return address
        need(root >> 60 == 8, 'translation outside frozen Sv39 profile')
        if guest:
            if address >> 41:
                raise PageFault(True, address, implicit)
        elif address >> 39 != ((1 << 25) - 1 if address & (1 << 38) else 0):
            raise PageFault(False, address)
        table = (root & ((1 << 44) - 1)) << 12
        for level in (2, 1, 0):
            bits = 11 if guest and level == 2 else 9
            slot = table + ((address >> (12 + 9*level)) & ((1 << bits)-1))*8
            physical = self.walk(slot, g_root, 0, True, True) if g_root and not guest else slot
            self.reads.append(physical)
            pte = self.memory.get(physical, 8)
            v, r, w, x, u = [bool(pte & (1 << n)) for n in range(5)]
            if not v or w and not r or pte >> 54:
                raise PageFault(guest, address, implicit)
            if r or x:
                permission = (r, w, x)[access]
                if not permission or u != guest or not pte & 64 or access == 1 and not pte & 128:
                    raise PageFault(guest, address, implicit)
                ppn = (pte >> 10) & ((1 << 44)-1)
                if ppn & ((1 << (9*level))-1):
                    raise PageFault(guest, address, implicit)
                return (ppn << 12) | (address & ((1 << (12+9*level))-1))
            if level == 0 or pte & (16 | 64 | 128):
                raise PageFault(guest, address, implicit)
            table = ((pte >> 10) & ((1 << 44)-1)) << 12
        raise AssertionError('unreachable page walk')

    def translate(self, address, vsatp, hgatp, access):
        guest = self.walk(address, vsatp, access, g_root=hgatp)
        return self.walk(guest, hgatp, access, True), guest


def classify(value, width):
    fraction_bits, exponent_bits = (23, 8) if width == 32 else (52, 11)
    sign = value >> (width-1)
    exponent = (value >> fraction_bits) & ((1 << exponent_bits)-1)
    fraction = value & ((1 << fraction_bits)-1)
    if exponent == (1 << exponent_bits)-1:
        bit = (9 if fraction & (1 << (fraction_bits-1)) else 8) if fraction else (0 if sign else 7)
    elif not exponent:
        bit = (2 if sign else 5) if fraction else (3 if sign else 4)
    else:
        bit = 1 if sign else 6
    return 1 << bit


class Architecture:
    """Small RV64 interpreter. No result or state is read from the native oracle."""
    def __init__(self, recipe):
        self.memory = Memory(recipe)
        self.x, self.f = [0]*32, [0]*32
        self.initialized = set()
        self.pc = recipe['reset_pc']
        self.host_fs = self.guest_fs = self.fcsr = self.v = 0
        self.privilege = 3
        self.csr = {a: 0 for a in (0x100, 0x180, 0x200, 0x280, 0x300, 0x302,
            0x303, 0x304, 0x305, 0x105, 0x341, 0x141, 0x142, 0x143, 0x600, 0x602,
            0x603, 0x604, 0x643, 0x64a, 0x680, 0x3a0, 0x3b0, 0x140, 0x340)}
        self.events, self.accesses, self.virtual_accesses = [], [], []

    def status(self, address):
        fs = self.guest_fs if address == 0x200 else self.host_fs
        fixed = 0xa00000000 if address == 0x300 else 0x200000000
        return fixed | self.csr[address] | (fs << 13) | (int(fs == 3) << 63)

    def csr_address(self, address):
        return address + 0x100 if self.v and address in (0x100, 0x105, 0x140, 0x141, 0x142, 0x143, 0x180) else address

    def read_csr(self, address):
        address = self.csr_address(address)
        if address in (1, 2, 3):
            return {1: self.fcsr & 31, 2: self.fcsr >> 5, 3: self.fcsr}[address]
        if address in (0x100, 0x200, 0x300):
            return self.status(address)
        if address == 0x600:
            return (2 << 32) | self.csr[address]
        need(address in self.csr, f'unsupported CSR read {address:#x}')
        return self.csr[address]

    def write_csr(self, address, value):
        address = self.csr_address(address)
        if address in (1, 2, 3):
            self.fcsr = {1: (self.fcsr & 224) | (value & 31),
                         2: (self.fcsr & 31) | ((value & 7) << 5), 3: value & 255}[address]
            self.dirty()
        elif address in (0x100, 0x200, 0x300):
            if address == 0x200:
                self.guest_fs = (value >> 13) & 3
            else:
                self.host_fs = (value >> 13) & 3
            mask = 0xc0122 if address != 0x300 else 0xc0000 | 0x218aa | (3 << 11) | (3 << 38)
            self.csr[address] = value & mask
            if address == 0x300:
                # mstatus/sstatus expose the same S interrupt/privilege fields.
                self.csr[0x100] = value & 0xc0122
            elif address == 0x100:
                self.csr[0x300] = (self.csr[0x300] & ~0xc0122) | self.csr[0x100]
        elif address in (0x180, 0x280, 0x680):
            need(value >> 60 in (0, 8), 'unsupported translation mode write')
            self.csr[address] = (value & (0xf0000fffffffffff if address != 0x680 else 0xf0000ffffffffffc)) if value >> 60 else 0
        elif address == 0x600:
            self.csr[address] = value & 0x7003c0
        elif address in (0x105, 0x305):
            self.csr[address] = (value & ~3) | int(value & 3 == 1)
        elif address in (0x141, 0x341):
            self.csr[address] = value & ~1
        elif address == 0x3b0:
            self.csr[address] = value & ((1 << 54)-1)
        elif address == 0x302:
            self.csr[address] = value & 0xf0b7ff
        elif address == 0x602:
            self.csr[address] = value & 0xcb1ff
        else:
            need(address in self.csr, f'unsupported CSR write {address:#x}')
            self.csr[address] = value

    def dirty(self):
        self.host_fs = 3
        if self.v:
            self.guest_fs = 3

    def state(self):
        return {**{f'fpr_{n}': value for n, value in enumerate(self.f)},
            'hostFs': self.host_fs, 'guestFs': self.guest_fs, 'fcsr': self.fcsr,
            'virtualized': self.v, 'privilege': self.privilege,
            'hstatus': self.read_csr(0x600) if not self.v else (2 << 32) | self.csr[0x600],
            'htval': self.csr[0x643], 'htinst': self.csr[0x64a],
            'scause': self.csr[0x142], 'sepc': self.csr[0x141], 'stval': self.csr[0x143]}

    def translate(self, address, access):
        walker = Translation(self.memory)
        if self.v:
            try:
                physical, guest = walker.translate(address, self.csr[0x280], self.csr[0x680], access)
            except PageFault as fault:
                fault.reads = walker.reads
                raise
        else:
            physical = walker.walk(address, self.csr[0x180] if self.privilege != 3 else 0, access)
            guest = 0
        return physical, guest, walker.reads

    def trap(self, event, cause, tval, gpa=0, implicit=0):
        need(self.v and self.privilege == 1, 'fault outside frozen VS-to-HS profile')
        need(self.csr[0x302] & (1 << cause) and not self.csr[0x602] & (1 << cause),
             'fault must delegate M to HS, never VS')
        address = int(cause in (0, 1, 3, 4, 5, 6, 7, 12, 13, 15, 20, 21, 23))
        event.update(trap=True, cause=cause, tval=tval, guestAddress=address,
                     guestPageFault=int(cause in (20, 21, 23)), guestPhysicalAddress=gpa, implicitPte=implicit)
        self.csr[0x141], self.csr[0x142], self.csr[0x143] = self.pc, cause, tval
        self.csr[0x643], self.csr[0x64a] = gpa >> 2, 0x3000 if implicit else 0
        self.csr[0x600] = (self.csr[0x600] & ~0x1c0) | 0x180 | (address << 6)
        old = self.csr[0x100]
        self.csr[0x100] = (old & ~0x122) | 0x100 | ((old & 2) << 4)
        self.csr[0x300] = (self.csr[0x300] & ~0xc0122) | self.csr[0x100]
        self.v, self.privilege = 0, 1
        event['next'] = self.csr[0x105] & ~3

    def step(self):
        before = self.state()
        physical, _, fetch_ptes = self.translate(self.pc, 2)
        inst = self.memory.get(physical, 4)
        op, rd, funct, rs1, rs2, funct7 = inst & 127, (inst >> 7)&31, (inst >> 12)&7, (inst >> 15)&31, (inst >> 20)&31, inst >> 25
        a, b = self.x[rs1], self.x[rs2]
        event = dict(pc=self.pc, instruction=inst, physical=physical, rd=rd, writes=False,
                     data=0, next=(self.pc+4)&MASK, trap=False, system=op in (0x73, 0x07, 0x27, 0x53, 0x0f),
                     fp=op in (0x07, 0x27, 0x53), before=before, operand=a, operand2=b,
                     fetch_ptes=fetch_ptes, mutation=False, access=None, fpWrite=False,
                     initialized_before=set(self.initialized), completion_data=0, csr_write=None,
                     arithmetic_encoding=op == 0x53 and funct7 in (8,9))
        def write(value):
            event.update(writes=rd != 0, data=value & MASK)
        if op == 0x13:
            imm = signed(inst >> 20, 12)
            if funct == 0: write(a + imm)
            elif funct == 1 and inst >> 26 == 0: write(a << ((inst >> 20)&63))
            elif funct == 5 and inst >> 26 in (0, 16):
                write((signed(a, 64) if inst >> 26 else a) >> ((inst >> 20)&63))
            elif funct == 4: write(a ^ (imm & MASK))
            elif funct == 6: write(a | (imm & MASK))
            elif funct == 7: write(a & (imm & MASK))
            else: raise RuntimeError('unsupported immediate instruction')
        elif op in (0x37, 0x17):
            write(signed(inst & 0xfffff000, 32) + (self.pc if op == 0x17 else 0))
        elif op == 0x33:
            if funct == 0 and funct7 in (0, 32): write(a-b if funct7 else a+b)
            elif funct == 4 and funct7 == 0: write(a ^ b)
            elif funct == 6 and funct7 == 0: write(a | b)
            elif funct == 7 and funct7 == 0: write(a & b)
            else: raise RuntimeError('unsupported register instruction')
        elif op in (0x6f, 0x67):
            if op == 0x6f:
                imm = ((inst>>31)<<20)|(((inst>>12)&255)<<12)|(((inst>>20)&1)<<11)|(((inst>>21)&1023)<<1)
                target = self.pc + signed(imm, 21)
            else:
                need(funct == 0, 'reserved JALR')
                target = (a + signed(inst >> 20, 12)) & ~1
            write(self.pc+4); event['next'] = target & MASK
        elif op == 0x63:
            imm = ((inst>>31)<<12)|(((inst>>7)&1)<<11)|(((inst>>25)&63)<<5)|(((inst>>8)&15)<<1)
            take = {0:a==b, 1:a!=b, 4:signed(a,64)<signed(b,64), 5:signed(a,64)>=signed(b,64), 6:a<b, 7:a>=b}
            need(funct in take, 'reserved branch')
            if take[funct]: event['next'] = (self.pc+signed(imm,13)) & MASK
        elif op in (3, 0x23, 7, 0x27):
            fp, store = op in (7, 0x27), op in (0x23, 0x27)
            need(funct in ((2,3) if fp else (0,1,2,3,4,5,6)), 'unsupported load/store width')
            size = 1 << (funct & 3)
            immediate = (((inst>>25)<<5)|rd) if store else inst>>20
            address = (a + signed(immediate,12)) & MASK
            if fp and (not self.host_fs or self.v and not self.guest_fs):
                self.trap(event, 2, inst)
            elif address & (size-1):
                self.trap(event, 6 if store else 4, address)
            else:
                try:
                    pa, gpa, reads = self.translate(address, int(store))
                    value = (self.f[rs2] if fp else b) if store else self.memory.get(pa, size)
                    event['access'] = dict(address=address, physical=pa, size=size, store=store,
                        value=value & ((1 << (size*8))-1), ptes=reads, guest=gpa)
                    self.accesses.append(event['access'])
                    self.virtual_accesses.append({**event['access'], 'virtualized': self.v})
                    if store: self.memory.put(pa, value, size)
                    elif fp:
                        self.f[rd] = value | (0xffffffff00000000 if size == 4 else 0)
                        self.dirty(); event['mutation'] = True
                        event.update(fpWrite=True, completion_data=value)
                        self.initialized.add(rd)
                    else: write(value if funct & 4 else signed(value, size*8))
                except PageFault as fault:
                    self.virtual_accesses.append(dict(address=address, physical=None, size=size, store=store,
                        ptes=fault.reads, virtualized=self.v))
                    cause = ((23 if store else 21) if fault.guest else (15 if store else 13))
                    self.trap(event, cause, address, fault.address if fault.guest else 0, int(fault.implicit))
        elif op == 0x53:
            if not self.host_fs or self.v and not self.guest_fs:
                self.trap(event, 2, inst)
            else:
                if funct7 in (8, 9):
                    rm = funct if funct != 7 else self.fcsr >> 5
                    if rm not in range(5):
                        self.trap(event, 2, inst)
                    else:
                        value, flags = ieee_multiply(inst, self.f[rs1], self.f[rs2], self.fcsr >> 5)
                        event.update(arithmetic=True, flags=flags, rounding=rm,
                                     lhs=self.f[rs1], rhs=self.f[rs2])
                        self.f[rd] = value
                        self.fcsr |= flags
                        self.dirty(); event['mutation'] = True
                        event.update(fpWrite=True, completion_data=value)
                        self.initialized.add(rd)
                else:
                    width = 32 if not funct7 & 1 else 64
                    need(funct7 in (0x10,0x11,0x70,0x71,0x78,0x79), 'FP operation outside moves/sign/class profile')
                    def operand(index):
                        value = self.f[index]
                        return 0x7fc00000 if width == 32 and value >> 32 != 0xffffffff else value & ((1 << width)-1)
                    if funct7 in (0x78,0x79):
                        need(rs2 == 0 and funct == 0, 'reserved integer-to-FP move')
                        value = a & ((1 << width)-1)
                    elif funct7 in (0x70,0x71):
                        need(rs2 == 0 and funct in (0,1), 'reserved FP-to-integer move/class')
                        write(classify(operand(rs1),width) if funct else (signed(self.f[rs1]&0xffffffff,32) if width == 32 else self.f[rs1]))
                        value = None
                    else:
                        need(funct in (0,1,2), 'reserved sign injection')
                        left, right = operand(rs1), operand(rs2)
                        sign = (right >> (width-1)) ^ int(funct == 1)
                        if funct == 2: sign ^= left >> (width-1)
                        value = (left & ((1 << (width-1))-1)) | (sign << (width-1))
                    if value is not None:
                        self.f[rd] = value | (0xffffffff00000000 if width == 32 else 0)
                        self.dirty(); event['mutation'] = True
                        event.update(fpWrite=True, completion_data=value)
                        self.initialized.add(rd)
                    elif event['writes']:
                        event['completion_data'] = event['data']
        elif op == 0x73:
            if funct:
                need(funct in (1,2,3,5,6,7), 'reserved CSR opcode')
                address = inst >> 20
                source = rs1 if funct & 4 else a
                writes = (funct & 3) == 1 or rs1 != 0
                if address in (1,2,3) and (not self.host_fs or self.v and not self.guest_fs):
                    self.trap(event, 2, inst)
                else:
                    need(self.privilege >= (address>>8)&3 or self.privilege == 1 and not self.v and (address>>8)&3 == 2,
                         'CSR privilege outside frozen program')
                    old = self.read_csr(address)
                    write(old if (funct & 3) != 1 or rd else 0)
                    if writes:
                        value = source if (funct & 3) == 1 else old | source if (funct & 3) == 2 else old & ~source
                        event['csr_write'] = dict(address=address, value=value & MASK, source=source, operation=(funct & 3)-1)
                        self.write_csr(address, value & MASK)
                        event['mutation'] = address in (1,2,3)
            elif inst == 0x30200073:
                need(self.privilege == 3, 'MRET privilege')
                old = self.csr[0x300]; self.privilege = (old >> 11)&3
                self.v = int(bool(old & (1 << 39)) and self.privilege != 3)
                self.csr[0x300] = (old & ~((3<<11)|(1<<39)|8|(1<<17))) | 128 | ((old>>4)&8)
                event['next'] = self.csr[0x341]
            elif inst == 0x10200073:
                need(not self.v and self.privilege == 1, 'only HS SRET is frozen')
                old = self.csr[0x100]; self.privilege = (old >> 8)&1
                self.v = (self.csr[0x600] >> 7)&1; self.csr[0x600] &= ~128
                self.csr[0x100] = (old & ~0x122) | 32 | ((old>>4)&2)
                self.csr[0x300] = (self.csr[0x300] & ~(0xc0122|(1<<17))) | self.csr[0x100]
                event['next'] = self.csr[0x141]
            elif inst == 0x73:
                self.trap(event, 10, 0)
            else:
                need(inst in (0x12000073,0x22000073,0x62000073), 'unsupported SYSTEM instruction')
        elif op == 0x0f:
            need(funct in (0,1), 'unsupported barrier')
        else:
            raise RuntimeError(f'unsupported ISA opcode at {self.pc:#x}: {inst:#x}')
        if event['writes'] and not event['trap']:
            self.x[rd] = event['data']
        self.pc = event['next']
        event['after'] = self.state()
        event['initialized_after'] = set(self.initialized)
        self.events.append(event)
        return event

    def run(self, terminal, terminal_commits=2):
        seen = 0
        for _ in range(700):
            event = self.step()
            if event['pc'] == terminal:
                need(event['instruction'] == 0x6f and event['next'] == terminal, 'terminal must be software self jump')
                seen += 1
                if seen == terminal_commits:
                    return self.events
        raise RuntimeError('input program exceeds architectural instruction bound')


def validate_program(events):
    """Coverage derives from decoded instructions and operand values, not labels."""
    arithmetic = [e for e in events if e.get('arithmetic')]
    for funct7 in (8,9):
        group = [e for e in arithmetic if e['instruction'] >> 25 == funct7]
        need({e['rounding'] for e in group} == set(range(5)), 'five legal modes per arithmetic opcode required')
        need({(e['instruction'] >> 12) & 7 == 7 for e in group} == {False,True},
             'static and dynamic modes per arithmetic opcode required')
    need(any(e['before']['fcsr'] >> 5 in (5,6,7) and (e['instruction'] >> 12)&7 != 7
             for e in arithmetic), 'legal static override of reserved frm absent')
    need(any(arithmetic_checker(e) == 'malformed_box_result' and e['flags'] == 0
             and e['before']['fcsr'] & 31 == 0 for e in arithmetic),
         'observable malformed S box canonicalization absent')
    need(any((e['before']['fcsr'] & 31) & ~e['flags'] for e in arithmetic),
         'old-only sticky flag preservation coverage absent')
    need(any(e['flags'] == NV for e in arithmetic), 'arithmetic NV coverage absent')
    need(all(e['before']['fcsr'] & 31 == 0 for e in arithmetic if e['before']['virtualized'] and e['before']['fcsr'] >> 5 != 7),
         'observable isolated multiplication flags absent')
    for width in (32,64):
        group = [e for e in arithmetic if (32 if not (e['instruction'] >> 25)&1 else 64) == width]
        for sign in (0,1):
            need(any(e['flags'] == (OF|NX) and (e['lhs'] >> (width-1))&1 == sign for e in group),
                 'signed overflow coverage absent')
            need(any(e['flags'] == NX and (e['lhs'] >> (width-1))&1 == sign for e in group),
                 'signed inexact coverage absent')
        frac = 23 if width == 32 else 52
        magnitude_mask = (1 << (width-1))-1
        def classes(event):
            # Malformed boxes are tested separately, never counted as true NaNs.
            if width == 32 and any(event[k] >> 32 != 0xffffffff for k in ('lhs','rhs')):
                return ()
            return tuple(classify(event[k] & ((1 << width)-1), width) for k in ('lhs','rhs'))
        first_inexact = next((e for e in group if e['flags'] == NX), None)
        need(first_inexact is not None and first_inexact['before']['fcsr'] & 31 == 0,
             'observable initial inexact flags absent')
        need(any(set(classes(e)) & {1,128} and set(classes(e)) & {8,16} and e['flags'] == NV for e in group),
             'zero times infinity invalid absent')
        invalid = [e for e in group if e['flags'] == NV]
        need(invalid and all(e['before']['fcsr'] & 31 == 0 for e in invalid),
             'observable multiplication invalid flag absent')
        for kind, flag in ((512,0),(256,NV)):
            chosen = [e for e in group if kind in classes(e)]
            need(chosen and all(e['before']['fcsr'] & 31 == 0 and e['flags'] == flag for e in chosen),
                 'observable NaN flags absent')
        exact_tiny = [e for e in group if 0 < (e['after']['fpr_'+str(e['rd'])] & magnitude_mask) < (1 << frac) and e['flags'] == 0]
        need(exact_tiny and all(e['before']['fcsr'] & 31 == 0 for e in exact_tiny), 'observable exact subnormal absent')
        tiny = [e for e in group if e['flags'] == (UF|NX)]
        need(tiny and all(e['before']['fcsr'] & 31 == 0 for e in tiny), 'observable inexact underflow absent')
        half_min = [e for e in group if e['lhs'] & magnitude_mask == 1 and
                    e['rhs'] & magnitude_mask == ((126 if width == 32 else 1022) << frac)]
        need({(e['rounding'], e['after']['fpr_'+str(e['rd'])] & magnitude_mask, e['flags']) for e in half_min} ==
             {(0,0,UF|NX),(4,1,UF|NX)}, 'ties-even versus ties-away underflow contrast absent')
        one = (127 if width == 32 else 1023) << frac
        for lhs, rhs, flags in ((1 << frac, one-1, UF|NX), ((1 << frac)-1, one+1, NX)):
            boundary = [e for e in group if e['lhs'] & magnitude_mask == lhs and e['rhs'] & magnitude_mask == rhs]
            need(boundary and all(e['rounding'] == 0 and e['flags'] == flags and
                 e['after']['fpr_'+str(e['rd'])] & magnitude_mask == 1 << frac and
                 e['before']['fcsr'] & 31 == 0 for e in boundary),
                 'observable precision-rounded tininess boundary absent')
        zeros = [e for e in group if e['after']['fpr_'+str(e['rd'])] & magnitude_mask == 0 and e['flags'] == 0]
        need(any((e['after']['fpr_'+str(e['rd'])] >> (width-1)) & 1 for e in zeros), 'signed multiplication zero absent')
    need(any(e['rd'] == 4 and e['lhs'] == e['rhs'] and e['lhs'] == prior['after']['fpr_'+str(prior['rd'])]
             and (e['instruction'] >> 15) & 31 == prior['rd'] and (e['instruction'] >> 20) & 31 == prior['rd']
             and classify(e['lhs'],64) in (2,64) for prior,e in zip(arithmetic,arithmetic[1:])),
         'finite multiplication result dependency absent')
    illegal = [e for e in events if e['trap'] and e['arithmetic_encoding']]
    reserved = [e for e in illegal if e['before']['hostFs'] and e['before']['guestFs']]
    need({(e['instruction']>>12)&7 for e in reserved} == {5,6,7}, 'reserved static rounding traps absent')
    need({e['before']['fcsr']>>5 for e in reserved if (e['instruction']>>12)&7 == 7} == {5,6,7},
         'reserved dynamic rounding traps absent')
    need(any(not e['before']['hostFs'] for e in illegal) and
         any(e['before']['hostFs'] and not e['before']['guestFs'] for e in illegal),
         'joint host/guest FS arithmetic denial absent')
    return {'events':len(events), 'retirements':sum(not e['trap'] for e in events),
            'arithmetic':len(arithmetic), 'traps':sum(e['trap'] for e in events)}


def prefixed(prefix, fields):
    return {prefix + '$$' + key: width for key, width in fields.items()}


TOKEN = {'index': 4, 'tag': 64}
REQUEST = {**prefixed('token', TOKEN), 'pc': 64, 'instruction': 32, 'operand': 64, 'operand2': 64}
FAULT = {'pc': 64, 'cause': 64, 'tval': 64, **prefixed('guestFault', {
    'guestPageFault': 1, 'guestAddress': 1, 'guestPhysicalAddress': 64, 'implicitPte': 1})}
COMPLETE = {**prefixed('token', TOKEN), 'data': 64, 'nextPc': 64, 'exception': 1,
            **{key: width for key, width in FAULT.items() if key != 'pc'}}
DATA = {'address': 64, 'data': 64, 'mask': 8, 'write': 1, 'size': 2,
        'virtualized': 1, 'atomic': 1, 'atomicOp': 5, 'precheckedLoad': 1,
        'translationEpoch': 32, 'prefetchNextAllowed': 1, 'uncached': 1}
RAW_WIDTHS = {key: 1 for key in ('fpBusy', 'ownerActive', 'contextMemoryEpoch', 'hMemoryEpoch',
    'fpMemoryEpoch', 'trapReady', 'recovering', 'memoryBusy', 'fpMemoryBusy', 'adapterIdle',
    'translatorIdle', 'fetchAdapterIdle', 'fetchTranslatorIdle', 'assemblerIdle',
    'responseBufferIdle', 'memoryDrained', 'systemExecute', 'fpStartOffered', 'fpCompleteOffered',
    'guestSd', 'commitEnable', 'fpStartReady', 'systemStartReady')}
RAW_WIDTHS.update({'retireMatches': 2, 'statePhase': 2, 'systemState': 4, 'completionCount': 2,
                  **prefixed('ownerToken', TOKEN), **prefixed('systemRequest', REQUEST)})
for _name, _fields in (
    ('fpStart', REQUEST), ('systemStart', REQUEST), ('fpComplete', COMPLETE),
    ('systemComplete', {**prefixed('completion', COMPLETE), 'redirect': 1, 'invalidateFetch': 1}),
    ('trap', {**prefixed('token', TOKEN), **FAULT}),
    ('pendingException', {**prefixed('token', TOKEN), **FAULT}),
    ('fpRetire', TOKEN), ('mutation', {'guest': 1}),
    ('fpCsrWrite', {'address': 12, 'operation': 2, 'write': 1, 'value': 64}),
    ('hWrite', {'address': 12, 'data': 64}), ('dataVirtualRequest', DATA)):
    RAW_WIDTHS.update({_name + '$$valid': 1, **prefixed(_name + '$$bits', _fields)})
RAW_WIDTHS.update({'hostFsWrite$$valid': 1, 'hostFsWrite$$bits': 2})
for _lane in (0, 1):
    RAW_WIDTHS.update({f'commit{_lane}$$valid': 1, **prefixed(f'commit{_lane}$$bits', {
        **prefixed('token', TOKEN), 'pc': 64, 'instruction': 32, 'rd': 5,
        'writesRd': 1, 'data': 64, 'nextPc': 64})})
for _port in ('instruction', 'fetchPte', 'dataPte', 'data'):
    RAW_WIDTHS.update({_port + '$$request$$valid': 1, _port + '$$request$$ready': 1,
                      _port + '$$response$$valid': 1, _port + '$$response$$ready': 1})
    if _port == 'data':
        RAW_WIDTHS.update(prefixed(_port + '$$request$$bits', DATA))
    else:
        RAW_WIDTHS[_port + '$$request$$bits'] = 64
    if _port == 'instruction':
        RAW_WIDTHS.update({'instruction$$response$$bits': 16,
                          'instruction$$responseError': 1, 'instruction$$responsePageFault': 1})
    else:
        RAW_WIDTHS.update({_port + '$$response$$bits$$data': 64, _port + '$$response$$bits$$error': 1})
        if _port == 'data':
            RAW_WIDTHS['data$$response$$bits$$pageFault'] = 1
STATE_COLUMNS += ('hostSd',)
STATE_WIDTHS = {name: 64 for name in STATE_COLUMNS}
STATE_WIDTHS.update(hostFs=2, guestFs=2, fcsr=8, virtualized=1, privilege=2, hostSd=1)


class CheckFailure(RuntimeError):
    def __init__(self, name, cycle):
        self.name, self.cycle = name, cycle
        super().__init__(f'GUARDED_GUEST_FP_MULTIPLY_CHECK[{name}] cycle={cycle}')


def check(condition, name, cycle):
    if not condition:
        raise CheckFailure(name, cycle)


def token(raw, prefix):
    return raw[prefix + '$$index'], raw[prefix + '$$tag']


class Service:
    """Rebuild every driven memory input from frozen bytes and prior raw requests."""
    def __init__(self, recipe, schedule, accesses, virtual_accesses):
        self.memory = Memory(recipe)
        self.schedule, self.accesses, self.access_index = schedule, accesses, 0
        self.virtual_accesses, self.virtual_index, self.pte_queue = virtual_accesses, 0, []
        self.ports = {name: dict(valid=False, data=0, delay=0, wait=0, held=None)
                      for name in ('instruction', 'fetchPte', 'dataPte', 'data')}
        self.counts = Counter()

    def step(self, raw, cycle):
        stagger = self.schedule == 'staggered'
        if raw['dataVirtualRequest$$valid']:
            check(not self.pte_queue and self.virtual_index < len(self.virtual_accesses), 'single_data_walk_owner', cycle)
            access = self.virtual_accesses[self.virtual_index]; self.virtual_index += 1
            prefix = 'dataVirtualRequest$$bits$$'
            check(raw[prefix+'address'] == access['address'] and raw[prefix+'write'] == int(access['store'])
                  and raw[prefix+'size'] == access['size'].bit_length()-1
                  and raw[prefix+'virtualized'] == access['virtualized'], 'virtual_data_request', cycle)
            self.pte_queue = access['ptes'].copy()
        for name, port in self.ports.items():
            if port['delay']:
                port['delay'] -= 1
            ready = int(not port['valid'] and (not stagger or port['wait'] >= 2))
            valid = int(port['valid'] and not port['delay'])
            expected = {name+'$$request$$ready': ready, name+'$$response$$valid': valid}
            data_key = name + ('$$response$$bits' if name == 'instruction' else '$$response$$bits$$data')
            expected[data_key] = port['data'] if valid else 0
            for key, value in expected.items():
                check(raw[key] == value, 'external_service_input', cycle)
            errors = (('instruction$$responseError', 'instruction$$responsePageFault') if name == 'instruction'
                      else (name+'$$response$$bits$$error',))
            for field in errors:
                check(raw[field] == 0, 'no_injected_memory_fault', cycle)
            if name == 'data':
                check(raw['data$$response$$bits$$pageFault'] == 0, 'no_injected_memory_fault', cycle)
            offered = raw[name+'$$request$$valid']
            bits = ({key: raw[name+'$$request$$bits$$'+key] for key in DATA} if name == 'data'
                    else raw[name+'$$request$$bits'])
            if port['held'] is not None:
                check(offered and bits == port['held'], 'held_request_stability', cycle)
            port['held'] = bits if offered and not ready else None
            if port['held'] is not None:
                port['wait'] += 1
                self.counts[name+'_stalls'] += 1
            if valid and raw[name+'$$response$$ready']:
                port['valid'] = False
                self.counts[name+'_responses'] += 1
            if offered and ready:
                check(not port['valid'], 'single_external_response_owner', cycle)
                self.counts[name+'_requests'] += 1
                address = bits['address'] if name == 'data' else bits
                if name == 'data':
                    check(self.access_index < len(self.accesses), 'extra_physical_access', cycle)
                    expected_access = self.accesses[self.access_index]
                    self.access_index += 1
                    check(address == expected_access['physical'], 'physical_address', cycle)
                    check(bits['write'] == int(expected_access['store']) and
                          bits['size'] == expected_access['size'].bit_length()-1 and
                          not bits['virtualized'] and not bits['atomic'] and not bits['uncached'],
                          'physical_request_shape', cycle)
                    if bits['write']:
                        mask = ((1 << expected_access['size'])-1) << (address & 7)
                        check(bits['mask'] == mask and bits['data'] == expected_access['value'] << (8*(address&7)),
                              'physical_store_bytes', cycle)
                        for n in range(8):
                            if mask & (1 << n):
                                self.memory.put((address & ~7)+n, bits['data'] >> (8*n), 1)
                    else:
                        check(self.memory.get(address, expected_access['size']) == expected_access['value'],
                              'load_byte_oracle', cycle)
                    value = self.memory.get(address & ~7, 8)
                else:
                    if name == 'dataPte':
                        check(bool(self.pte_queue) and address == self.pte_queue.pop(0), 'exact_nested_data_pte_sequence', cycle)
                    value = self.memory.get(address, 2 if name == 'instruction' else 8)
                port.update(valid=True, data=value, delay=(2+cycle%5 if stagger else 1), wait=0)


class Replay:
    def __init__(self, recipe, schedule):
        self.arch = Architecture(recipe)
        self.events = self.arch.run(recipe['terminal_pc'])
        self.systems = [event for event in self.events if event['system']]
        self.index = self.started = self.executed = self.completed = 0
        self.owner = self.fp = self.system = None
        # The passive retirement comparator retains its reset token even inactive.
        self.last_token = (0, 0)
        self.state = None
        self.initialized = set()
        self.counts = Counter()
        self.service = Service(recipe, schedule, self.arch.accesses, self.arch.virtual_accesses)
        self.last_post = None
        self.schedule = schedule
        self.hold = 0
        self.held_tokens = set()

    def current(self):
        need(self.index < len(self.events), 'extra architectural event')
        return self.events[self.index]

    def fault(self, raw, prefix, event, cycle):
        for name in ('pc', 'cause', 'tval'):
            check(raw[prefix+'$$'+name] == event[name], 'trap_'+name, cycle)
        for name in ('guestPageFault', 'guestAddress', 'guestPhysicalAddress', 'implicitPte'):
            check(raw[prefix+'$$guestFault$$'+name] == event[name], 'trap_'+name, cycle)

    def apply(self, event):
        after = event['after']
        for name, value in after.items():
            if not name.startswith('fpr_') or int(name[4:]) in event['initialized_after']:
                self.state[name] = value
        self.state['hostSd'] = int(self.state['hostFs'] == 3)
        self.initialized = event['initialized_after'].copy()

    def request(self, raw, prefix, event, cycle):
        check(raw[prefix+'$$pc'] == event['pc'] and raw[prefix+'$$instruction'] == event['instruction'],
              'fetched_system_instruction', cycle)
        inst = event['instruction']; op = inst & 127
        uses_integer = op in (7, 0x27) or op == 0x53 and inst >> 25 in (0x78, 0x79) or op == 0x73 and (inst >> 12)&3
        if uses_integer:
            check(raw[prefix+'$$operand'] == event['operand'], 'system_integer_operand', cycle)

    def step(self, raw, pre, post, cycle):
        if self.state is None:
            self.state = {**self.events[0]['before'], 'hostSd': 0}
            for n in range(32):
                self.state[f'fpr_{n}'] = pre[f'fpr_{n}']
        if self.last_post is not None:
            check(pre == self.last_post, 'linked_pre_post', cycle)
        check(pre == self.state, 'architectural_pre_state', cycle)
        check(raw['guestSd'] == int(pre['guestFs'] == 3), 'guest_sd_alias', cycle)
        check(raw['ownerActive'] == int(self.owner is not None), 'protected_owner_lifetime', cycle)
        if self.owner:
            check(token(raw, 'ownerToken') == self.owner['token'], 'protected_owner_token', cycle)
        owner_event = self.owner['event'] if self.owner else None
        memory_fp = bool(owner_event and owner_event['instruction'] & 127 in (7, 0x27))
        check(raw['fpMemoryEpoch'] == int(memory_fp) and not raw['hMemoryEpoch'] and
              raw['contextMemoryEpoch'] == int(bool(owner_event and (not owner_event['fp'] or memory_fp))),
              'protected_memory_domain', cycle)
        check(raw['fpBusy'] == int(self.fp is not None), 'fp_busy_lifetime', cycle)
        check(bool(raw['statePhase']) == bool(self.fp), 'fp_state_phase', cycle)
        if self.fp and self.fp['completed']:
            check(raw['statePhase'] == 3, 'completed_fp_waits_for_retire_or_trap', cycle)
            if not raw['commitEnable']:
                self.counts['fp_held_cycles'] += 1
        if self.fp and self.fp['completed'] and self.fp['event']['trap'] and self.owner is None and not raw['trap$$valid']:
            check(not raw['fpStartReady'] and not raw['systemStartReady'] and not raw['fpStart$$valid']
                  and not raw['systemStart$$valid'] and not raw['fpComplete$$valid'],
                  'no_fp_fault_start_credit', cycle)
        if raw['pendingException$$valid'] and not raw['commitEnable']:
            self.counts['trap_held_cycles'] += 1
        check(raw['memoryDrained'] == int(not raw['memoryBusy'] and raw['adapterIdle'] and raw['translatorIdle']
              and raw['responseBufferIdle'] and not raw['completionCount']), 'drain_definition', cycle)
        check(raw['commitEnable'] == int(self.hold == 0), 'frozen_commit_hold_schedule', cycle)
        if self.hold:
            self.hold -= 1
        if self.schedule == 'staggered':
            fc = raw['fpComplete$$valid']
            sc = raw['systemComplete$$valid'] and raw['systemComplete$$bits$$completion$$exception']
            if fc or sc:
                tag = raw['fpComplete$$bits$$token$$tag' if fc else 'systemComplete$$bits$$completion$$token$$tag']
                if tag not in self.held_tokens:
                    self.held_tokens.add(tag); self.hold = 5
        self.service.step(raw, cycle)
        expected_mutation = 0
        expected_csr = None
        expected_guest = 0
        fp_retired = False
        matches = 0
        # The ROB may retire an accepted nonfault SYSTEM completion on this
        # same edge. Validate completion before consuming its owner at commit.
        if raw['systemComplete$$valid']:
            check(self.system is not None and self.system['execute'] and not self.system['complete'],
                  'once_system_completion', cycle)
            event = self.system['event']; self.system['complete'] = True
            prefix = 'systemComplete$$bits$$completion'
            check(token(raw, prefix+'$$token') == self.system['token'], 'system_completion_token', cycle)
            check(raw[prefix+'$$exception'] == int(event['trap']), 'system_completion_exception', cycle)
            if event['trap']:
                check(raw['memoryDrained'], 'exception_release_drained', cycle)
                self.owner = None
            self.completed += 1
        if raw['fpComplete$$valid']:
            check(self.fp is not None and not self.fp['completed'], 'once_fp_completion', cycle)
            event = self.fp['event']; self.fp['completed'] = True
            check(token(raw, 'fpComplete$$bits$$token') == self.fp['token'], 'fp_completion_token', cycle)
            check(raw['fpComplete$$bits$$exception'] == int(event['trap']), 'fp_completion_exception', cycle)
            check(raw['fpComplete$$bits$$nextPc'] == event['pc']+4, 'fp_completion_next_pc', cycle)
            if event['trap']:
                for name in ('cause', 'tval'):
                    check(raw['fpComplete$$bits$$'+name] == event[name], 'fp_completion_'+name, cycle)
                for name in ('guestPageFault','guestAddress','guestPhysicalAddress','implicitPte'):
                    check(raw['fpComplete$$bits$$guestFault$$'+name] == event[name], 'fp_completion_'+name, cycle)
            else:
                check(raw['fpComplete$$bits$$data'] == event['completion_data'], arithmetic_checker(event), cycle)
            self.counts['fp_completions'] += 1
        for lane in (0, 1):
            prefix = f'commit{lane}'
            if not raw[prefix+'$$valid']:
                continue
            check(raw['commitEnable'] == 1, 'retirement_enable', cycle)
            event = self.current()
            check(not event['trap'], 'fault_must_not_retire', cycle)
            for key, name in (('pc','pc'),('instruction','instruction'),('nextPc','next')):
                check(raw[prefix+'$$bits$$'+key] == event[name], 'retired_'+key, cycle)
            check(raw[prefix+'$$bits$$writesRd'] == int(event['writes']), 'retired_write_enable', cycle)
            if event['writes']:
                check(raw[prefix+'$$bits$$rd'] == event['rd'], 'retired_rd', cycle)
                check(raw[prefix+'$$bits$$data'] == event['data'], 'retired_value', cycle)
            commit_token = token(raw, prefix+'$$bits$$token')
            if self.last_token == commit_token:
                matches |= 1 << lane
            if event['system']:
                check(self.system is not None and self.system['event'] is event and self.system['complete'],
                      'system_commit_after_completion', cycle)
                check(self.system['token'] == commit_token and self.owner is not None,
                      'system_commit_owner', cycle)
                self.owner = None; self.system = None
            if event['fp']:
                check(self.fp is not None and self.fp['event'] is event and self.fp['completed'],
                      'fp_commit_after_once_completion', cycle)
                check(raw['fpRetire$$valid'] and token(raw, 'fpRetire$$bits') == commit_token,
                      'fp_retire_token', cycle)
                expected_mutation = int(event['mutation']); expected_guest = event['before']['virtualized']
                self.apply(event); self.fp = None; fp_retired = True
                self.counts['fp_retires'] += 1
            self.index += 1; self.counts['commits'] += 1
        check(raw['retireMatches'] == matches, 'retire_token_matches', cycle)
        check(raw['fpRetire$$valid'] == int(fp_retired), 'no_spurious_fp_retire', cycle)
        if raw['systemStart$$valid']:
            check(self.started < len(self.systems) and self.system is None and self.owner is None,
                  'single_system_owner', cycle)
            event = self.systems[self.started]; self.started += 1
            self.request(raw, 'systemStart$$bits', event, cycle)
            self.last_token = token(raw, 'systemStart$$bits$$token')
            self.system = dict(event=event, token=self.last_token, execute=False, complete=False)
            self.owner = self.system
            self.counts['system_starts'] += 1
        if raw['systemExecute']:
            check(self.system is not None and not self.system['execute'], 'once_system_execute', cycle)
            event = self.system['event']
            self.request(raw, 'systemRequest', event, cycle)
            check(token(raw, 'systemRequest$$token') == self.system['token'], 'system_execute_token', cycle)
            self.system['execute'] = True
            self.executed += 1
            expected_csr = event['csr_write']
            if not event['fp'] and not event['trap']:
                self.apply(event)
                expected_mutation = int(event['mutation']); expected_guest = event['before']['virtualized']
        if raw['fpStart$$valid']:
            check(self.system is not None and self.system['execute'] and self.fp is None,
                  'single_fp_owner', cycle)
            event = self.system['event']
            check(event['fp'], 'only_decoded_fp_start', cycle)
            self.request(raw, 'fpStart$$bits', event, cycle)
            check(token(raw, 'fpStart$$bits$$token') == self.system['token'], 'fp_start_token', cycle)
            self.fp = dict(event=event, token=self.system['token'], completed=False)
            self.counts['fp_issues'] += 1
        if raw['trap$$valid']:
            event = self.current()
            check(event['trap'], 'unexpected_trap', cycle)
            check(raw['commitEnable'] and raw['trapReady'] and not raw['recovering'] and self.owner is None,
                  'automatic_trap_admission', cycle)
            check(raw['memoryDrained'], 'trap_drained', cycle)
            check(raw['pendingException$$valid'], 'trap_has_real_pending_exception', cycle)
            if event['arithmetic_encoding'] and event['before']['hostFs'] and event['before']['guestFs']:
                check(raw['trap$$bits$$cause'] == 2, 'reserved_rounding_trap', cycle)
            self.fault(raw, 'trap$$bits', event, cycle)
            self.fault(raw, 'pendingException$$bits', event, cycle)
            check(self.system is not None and self.system['complete'], 'trap_after_system_completion', cycle)
            check(token(raw, 'trap$$bits$$token') == self.system['token'], 'trap_token', cycle)
            if event['fp']:
                check(self.fp is not None and self.fp['completed'], 'fp_fault_busy_until_trap', cycle)
            else:
                check(self.fp is None, 'csr_fault_has_no_fp_owner', cycle)
            self.apply(event); self.fp = self.system = None
            self.index += 1; self.counts['traps'] += 1
        host_write = bool(expected_csr and (expected_csr['address'] == 0x300 or
            expected_csr['address'] == 0x100 and not pre['virtualized']))
        fp_write = bool(expected_csr and expected_csr['address'] in (1,2,3))
        check(raw['hostFsWrite$$valid'] == int(host_write), 'decoded_host_fs_write', cycle)
        if host_write:
            check(raw['hostFsWrite$$bits'] == (expected_csr['value'] >> 13)&3, 'decoded_host_fs_value', cycle)
        check(raw['fpCsrWrite$$valid'] == int(fp_write), 'decoded_fp_csr_write', cycle)
        if fp_write:
            for field, value in (('address',expected_csr['address']), ('operation',expected_csr['operation']),
                                 ('write',1), ('value',expected_csr['source'])):
                check(raw['fpCsrWrite$$bits$$'+field] == value, 'decoded_fp_csr_payload', cycle)
        check(raw['hWrite$$valid'] == int(expected_csr is not None), 'decoded_h_csr_write', cycle)
        if expected_csr:
            check(raw['hWrite$$bits$$address'] == expected_csr['address'] and
                  raw['hWrite$$bits$$data'] == expected_csr['value'], 'decoded_h_csr_payload', cycle)
        check(raw['mutation$$valid'] == expected_mutation, 'precise_fp_mutation', cycle)
        if expected_mutation:
            check(raw['mutation$$bits$$guest'] == expected_guest, 'captured_mutation_context', cycle)
            self.counts['mutations'] += 1
        check(post['fcsr'] == self.state['fcsr'],
              'missing_sticky_flags' if fp_retired else 'flags_before_retirement', cycle)
        check(post == self.state, 'architectural_post_state', cycle)
        self.last_post = post.copy()


def load_recipe(path):
    recipe = json_row(clean_text(path, 2*1024*1024))
    need(type(recipe) is dict, 'recipe object required')
    expected_keys = ('schema', 'profile', 'reset_pc', 'terminal_pc', 'zero_pages', 'program', 'code',
        'ptes', 'bytes', 'fault_sites', 'phase_markers', 'schedules', 'cycle_limit', 'trace_bytes_limit',
        'native_timeout_seconds', 'scope', 'bounds_justification', 'arithmetic_cases')
    need(set(recipe) == set(expected_keys), 'recipe fields differ')
    exact([recipe['schema'], recipe['profile'], recipe['cycle_limit'], recipe['trace_bytes_limit'],
           recipe['native_timeout_seconds']], [1, 'guarded-guest-fp-multiply-v1', CYCLE_LIMIT, TRACE_LIMIT, TIMEOUT], 'recipe profile')
    need(unsigned(recipe['reset_pc']) and unsigned(recipe['terminal_pc']), 'invalid program bounds')
    # Metadata describes scope; only program/PTE/byte inputs drive interpretation.
    exact(recipe['scope']['all32_eager_contexts'], [], 'context itinerary')
    exact([recipe['scope'][name] for name in ('cold_reset','clocks','irq_msi','numerical_fd','inflight_younger_load_cancel')],
          [True,1,False,True,False], 'scope exclusions')
    return recipe



# Fixed-schema key groups cache only prefix selection. Every original scalar,
# invalid-payload, ordering and zero-normalization check remains active per row.
EVENT_PAYLOAD_FIELDS = {
    prefix: tuple(name for name in sorted(RAW_WIDTHS) if name.startswith(prefix+'$$bits'))
    for prefix in ('fpStart','systemStart','fpComplete','systemComplete','trap','pendingException',
                   'commit0','commit1','fpRetire','mutation','fpCsrWrite','hostFsWrite','hWrite','dataVirtualRequest')}
REQUEST_PAYLOAD_FIELDS = {
    prefix: tuple(name for name in sorted(RAW_WIDTHS) if name.startswith(prefix+'$$request$$bits'))
    for prefix in ('instruction','fetchPte','dataPte','data')}
SYSTEM_REQUEST_FIELDS = tuple(name for name in sorted(RAW_WIDTHS) if name.startswith('systemRequest$$'))


def sparse_raw(encoded, columns):
    need(type(encoded) is list, 'invalid sparse raw fields')
    raw = dict.fromkeys(columns, 0)
    last = -1
    for item in encoded:
        need(type(item) is list and len(item) == 2 and type(item[0]) is int and
             last < item[0] < len(columns), 'unordered or duplicate sparse field')
        index, value = item
        need(unsigned(value, RAW_WIDTHS[columns[index]]) and value != 0, 'invalid sparse scalar')
        raw[columns[index]] = value; last = index
    for prefix, fields in EVENT_PAYLOAD_FIELDS.items():
        if not raw[prefix+'$$valid']:
            need(not any(raw[name] for name in fields),
                 'invalid event payload must normalize to zero')
    for prefix, fields in REQUEST_PAYLOAD_FIELDS.items():
        if not raw[prefix+'$$request$$valid']:
            need(not any(raw[name] for name in fields),
                 'invalid request payload must normalize to zero')
    if not raw['systemExecute']:
        need(not any(raw[name] for name in SYSTEM_REQUEST_FIELDS),
             'inactive system request must normalize to zero')
    if not raw['ownerActive']:
        need(token(raw, 'ownerToken') == (0,0), 'inactive owner token must normalize to zero')
    return raw


def check_trace(path, recipe, schedule, mutate=None):
    need(schedule in SCHEDULES, 'unknown schedule')
    lines = clean_text(path).splitlines()
    need(3 < len(lines) <= 3*CYCLE_LIMIT+3, 'raw line bound')
    header = json_row(lines[0])
    columns = sorted(RAW_WIDTHS)
    exact(header, dict(type='header', schema=1, schedule=schedule, columns=columns,
                       state_columns=list(STATE_COLUMNS)), 'raw header')
    ledger = Replay(recipe, schedule)
    states, cycles = [], 0
    for line in lines[1:-1]:
        row = json_row(line)
        need(type(row) is list and bool(row), 'raw row array required')
        if row[0] == 'S':
            need(len(row) == 3 and type(row[1]) is int and row[1] == len(states) and type(row[2]) is list,
                 'state identity/order differs')
            need(len(row[2]) == len(STATE_COLUMNS), 'full passive state required')
            need(all(unsigned(v, STATE_WIDTHS[k]) for k,v in zip(STATE_COLUMNS,row[2])), 'invalid state scalar')
            state = dict(zip(STATE_COLUMNS,row[2]))
            need(not states or state != states[-1], 'redundant state id')
            states.append(state)
        else:
            need(len(row) == 5 and row[0] == 'C' and type(row[1]) is int and row[1] == cycles,
                 'every raw cycle must be present once')
            need(cycles < CYCLE_LIMIT, 'raw cycle bound')
            need(all(type(n) is int and 0 <= n < len(states) for n in row[2:4]), 'unknown state reference')
            raw = sparse_raw(row[4], columns)
            pre, post = states[row[2]].copy(), states[row[3]].copy()
            if mutate:
                mutate(ledger, raw, pre, post, cycles)
            ledger.step(raw, pre, post, cycles)
            cycles += 1
    footer = json_row(lines[-1])
    need(type(footer) is dict and set(footer) == {'type','cycles','native_checks','commits','traps',
        'fp_issues','fp_completions','fp_retires','final_memory'}, 'invalid footer fields')
    need(unsigned(footer['native_checks']) and footer['native_checks'] > 0, 'native checker receipt required')
    expected = {key: ledger.counts[key] for key in ('commits','traps','fp_issues','fp_completions','fp_retires')}
    exact(footer, dict(type='footer', cycles=cycles, native_checks=footer['native_checks'],
                      **expected, final_memory=ledger.arch.memory.changed()), 'footer')
    need(ledger.index == len(ledger.events) and ledger.started == ledger.executed == ledger.completed == len(ledger.systems),
         'program/system lifecycle incomplete')
    need(ledger.owner is None and ledger.fp is None and ledger.system is None, 'undrained final architectural owner')
    need(ledger.service.access_index == len(ledger.arch.accesses) and
         ledger.service.virtual_index == len(ledger.arch.virtual_accesses) and not ledger.service.pte_queue,
         'incomplete independent data/PTE ledger')
    need(all(not port['valid'] for name,port in ledger.service.ports.items() if name != 'instruction'),
         'undrained final data/PTE responses')
    exact(ledger.service.memory.changed(), ledger.arch.memory.changed(), 'independent final memory and neighbors')
    validate_program(ledger.events)
    traps = [event for event in ledger.events if event['trap']]
    need(Counter(event['cause'] for event in traps) == Counter({2:7,10:2}),
         'required reserved-rounding and FS-denial traps absent')
    need(sum(event['fp'] and event['trap'] for event in traps) == 7,
         'seven real FP illegal-instruction traps required')
    if schedule == 'staggered':
        need(ledger.counts['fp_held_cycles'] > 0 and ledger.counts['trap_held_cycles'] > 0 and
             all(ledger.service.counts[name+'_stalls'] > 0 for name in ledger.service.ports),
             'actual held retirement/trap/service coverage absent')
    return {**expected, 'cycles': cycles, 'native_checks': footer['native_checks'],
        'held_retire': ledger.counts['fp_held_cycles'], 'held_trap': ledger.counts['trap_held_cycles'],
        'data_virtual_requests': ledger.service.virtual_index, 'memory': dict(ledger.service.counts)}


def check_positive(log, trace, recipe, schedule):
    result = check_trace(trace, recipe, schedule)
    text = (f'GUARDED_GUEST_FP_MULTIPLY_PASS schedule={schedule} cycles={result["cycles"]} '
            f'commits={result["commits"]} traps={result["traps"]} checks={result["native_checks"]} '
            f'held_retire={result["held_retire"]} held_trap={result["held_trap"]}\n')
    exact(clean_text(log), text, 'native summary')
    return result


def arithmetic_checker(event):
    if not event.get('arithmetic'):
        return 'fp_completion_value'
    if not (event['instruction'] >> 25) & 1 and (event['lhs'] >> 32 != 0xffffffff or event['rhs'] >> 32 != 0xffffffff):
        return 'malformed_box_result'
    return 'rounding_result' if event['rounding'] == 3 and event['flags'] & NX else 'arithmetic_result'


NEGATIVES = {
    'wrong_numeric_result': 'arithmetic_result',
    'flags_before_retirement': 'flags_before_retirement',
    'missing_sticky_flags': 'missing_sticky_flags',
    'wrong_flags': 'missing_sticky_flags',
    'missing_underflow': 'missing_sticky_flags',
    'premature_tininess': 'missing_sticky_flags',
    'guest_context_mutation': 'captured_mutation_context',
    'malformed_box_treatment': 'malformed_box_result',
    'wrong_rounding': 'rounding_result',
    'reserved_rounding_trap': 'reserved_rounding_trap',
    'illegal_trap_suppression': 'architectural_post_state',
    'fault_retirement': 'fault_must_not_retire',
    'premature_owner_release': 'protected_owner_lifetime',
    'incomplete_release_drain': 'exception_release_drained',
    'incomplete_trap_drain': 'trap_drained',
    'duplicate_completion': 'once_fp_completion',
    'wrong_data_pte': 'exact_nested_data_pte_sequence',
    'wrong_physical_address': 'physical_address',
    'premature_start_credit': 'no_fp_fault_start_credit',
}


def mutation_control(name):
    need(name in NEGATIVES, 'unknown negative checker control')
    applied = []
    def mutate(ledger, raw, pre, post, cycle):
        if applied:
            return
        event = ledger.fp['event'] if ledger.fp else None
        arithmetic = event is not None and event.get('arithmetic')
        if name in ('wrong_numeric_result','malformed_box_treatment','wrong_rounding') and arithmetic and raw['fpComplete$$valid'] and arithmetic_checker(event) == NEGATIVES[name]:
            raw['fpComplete$$bits$$data'] ^= 1
        elif name == 'flags_before_retirement' and arithmetic and event['flags'] and not raw['fpRetire$$valid']:
            post['fcsr'] ^= 1
        elif name == 'missing_sticky_flags' and arithmetic and raw['fpRetire$$valid'] and ((event['before']['fcsr'] & 31) & ~event['flags']):
            old_only = (event['before']['fcsr'] & 31) & ~event['flags']
            post['fcsr'] &= ~(old_only & -old_only)
        elif name == 'missing_underflow' and arithmetic and event['flags'] == (UF|NX) and raw['fpRetire$$valid']:
            post['fcsr'] &= ~UF
        elif name == 'premature_tininess' and arithmetic and event['flags'] == NX and raw['fpRetire$$valid'] and (event['after']['fpr_'+str(event['rd'])] & 0x7fffffffffffffff) in (0x0010000000000000,0x7fffffff00800000):
            post['fcsr'] |= UF
        elif name == 'wrong_flags' and arithmetic and event['flags'] and raw['fpRetire$$valid']:
            post['fcsr'] &= ~event['flags']
        elif name == 'guest_context_mutation' and arithmetic and raw['mutation$$valid']:
            raw['mutation$$bits$$guest'] ^= 1
        elif name == 'reserved_rounding_trap' and raw['trap$$valid'] and ledger.current()['arithmetic_encoding'] and pre['hostFs'] and pre['guestFs']:
            raw['trap$$bits$$cause'] ^= 1
        elif name == 'illegal_trap_suppression' and raw['trap$$valid'] and ledger.current()['arithmetic_encoding'] and pre['hostFs'] and pre['guestFs']:
            raw['trap$$valid'] = 0
        elif name == 'premature_start_credit' and ledger.fp and ledger.fp['completed'] and event['trap'] and ledger.owner is None and not raw['trap$$valid']:
            raw['fpStartReady'] = 1
        elif name == 'wrong_physical_address' and raw['data$$request$$valid'] and raw['data$$request$$ready']:
            raw['data$$request$$bits$$address'] ^= 8
        elif name == 'fault_retirement' and raw['trap$$valid']:
            raw['commit0$$valid'] = 1
        elif name == 'premature_owner_release' and ledger.fp and raw['ownerActive']:
            raw['ownerActive'] = 0
        elif name == 'incomplete_release_drain' and raw['systemComplete$$valid'] and raw['systemComplete$$bits$$completion$$exception']:
            raw['adapterIdle'] = raw['memoryDrained'] = 0
        elif name == 'incomplete_trap_drain' and raw['trap$$valid']:
            raw['adapterIdle'] = raw['memoryDrained'] = 0
        elif name == 'duplicate_completion' and ledger.fp and ledger.fp['completed'] and not event['trap'] and not raw['fpRetire$$valid']:
            raw['fpComplete$$valid'] = 1
        elif name == 'wrong_data_pte' and raw['dataPte$$request$$valid'] and raw['dataPte$$request$$ready']:
            raw['dataPte$$request$$bits'] ^= 8
        else:
            return
        applied.append(cycle)
    return mutate, applied


def check_negative(trace, recipe, name):
    mutate, applied = mutation_control(name)
    try:
        check_trace(trace, recipe, 'staggered' if name in ('premature_start_credit','duplicate_completion','flags_before_retirement') else 'baseline', mutate)
    except CheckFailure as error:
        need(applied == [error.cycle] and error.name == NEGATIVES[name],
             'negative missed its exact named checker')
        return {'name': name, 'checker': error.name, 'cycle': error.cycle, 'diagnostic': str(error)}
    raise RuntimeError('negative control was not rejected')


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_pins():
    root = common.ROOT
    paths = list((root/'src/main/scala').rglob('*.scala'))
    paths += [root/path for path in ('Makefile','build.mill',
        'src/test/scala/ooo/GuardedGuestFpCoreGsim.scala',
        'src/test/scala/ooo/GuardedGuestFpMultiplyGsim.scala', 'src/test/scala/ooo/GuardedGuestFpMultiplyConfigSpec.scala',
        'simulator/gsim/guarded_guest_fp_multiply.py', 'simulator/gsim/test_guarded_guest_fp_multiply_entry.py',
        'simulator/gsim/harness/guarded_guest_fp_multiply.cpp', 'simulator/gsim/config/guarded_guest_fp_multiply.json',
        'simulator/gsim/guarded_guest_fp_multiply_program.py', 'simulator/gsim/run.py', 'simulator/gsim/gsim_initialization_setup.py', 'simulator/gsim/config/toolchain.json')]
    return {str(path.relative_to(root)): file_hash(path) for path in sorted(paths)}


def native_run(output, arguments, name, env):
    path = output/name
    with path.open('x') as log:
        result = subprocess.run([str(output/'run'), *arguments], cwd=common.ROOT,
            stdout=log, stderr=subprocess.STDOUT, env=env, timeout=TIMEOUT)
    need(type(result.returncode) is int and result.returncode == 0, 'native run failed; not checker evidence')
    return path


def save_json(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=common.BUILD/'guarded-guest-fp-multiply')
    args = parser.parse_args()
    need(not args.output.exists() and not args.output.is_symlink(), 'fresh output directory required')
    output = args.output.resolve()
    recipe_path = common.ROOT/'simulator/gsim/config/guarded_guest_fp_multiply.json'
    recipe = load_recipe(recipe_path)
    before = source_pins()
    # Reject malformed executable inputs before starting any build.
    validate_program(Architecture(recipe).run(recipe['terminal_pc']))
    gsim, cxx = common.setup(False)
    output.mkdir(parents=True)
    save_json(output/'source-pins.json', before)
    saved_recipe = output/'input-recipe.json'
    with saved_recipe.open('xb') as stream:
        stream.write(recipe_path.read_bytes())
    os.environ['UBSAN_OPTIONS'] = 'halt_on_error=1'
    env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0', 'UBSAN_OPTIONS': 'halt_on_error=1'}
    first = output/'raw-baseline.jsonl'
    built = common.test(gsim, cxx, str(output), 'ooo.GuardedGuestFpMultiplyGsimMain',
        'GuardedGuestFpMultiplyGsim', 'guarded_guest_fp_multiply.cpp',
        runtime_args=('--schedule','baseline','--trace',str(first),'--recipe',str(saved_recipe)),
        sanitizer=True, cxx_flags=('-fbracket-depth=4096',), timeout=TIMEOUT,
        mill_module='IonSoC.guardedGuestFpMultiply')
    need(built == output, 'generated model destination changed')
    summaries = [check_positive(output/'test.log', first, recipe, 'baseline')]
    second = output/'raw-staggered.jsonl'
    log = native_run(output, ('--schedule','staggered','--trace',str(second),'--recipe',str(saved_recipe)),
                     'staggered.log', env)
    summaries.append(check_positive(log, second, recipe, 'staggered'))
    exact(source_pins(), before, 'sources unchanged throughout build and pristine runs')
    pristine = {name: file_hash(output/name) for name in (
        'raw-baseline.jsonl','raw-staggered.jsonl','test.log','staggered.log','input-recipe.json','source-pins.json')}
    # Save the complete pristine receipts before any negative touches a copied row.
    save_json(output/'pristine-summary.json', {'schema':1, 'sha256':pristine, 'schedules':summaries})
    negatives = [check_negative(second if name in ('premature_start_credit','duplicate_completion','flags_before_retirement') else first, recipe, name)
                 for name in NEGATIVES]
    exact({name:file_hash(output/name) for name in pristine}, pristine, 'pristine evidence preserved after negatives')
    exact(source_pins(), before, 'final source pins')
    save_json(output/'entry-summary.json', {'schema':1, 'profile':'guarded-guest-fp-multiply-v1',
        'actual_core':True, 'fetched_guest_fp':True, 'external_architectural_injection':False,
        'scope':recipe['scope'], 'schedules':summaries, 'negative_controls':negatives,
        'pristine_sha256':pristine,
        'fetch_proof':'real translator, response bytes, retired instruction bytes; no canceled speculative fetch-walk prefix proof'})
    print(STANDARD_MARKER)


if __name__ == '__main__':
    main()
