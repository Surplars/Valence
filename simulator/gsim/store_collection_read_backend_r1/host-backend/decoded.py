"""Small independently authored legal instruction catalog for decoded ingress."""
from dataclasses import dataclass

MASK64 = (1 << 64) - 1
RAM, LIMIT = 0x80200000, 0x100200000
READ_BEAT = 0xFEDCBA9876543210


def sx(value, bits):
    value &= (1 << bits) - 1
    return (value - (1 << bits) if value & (1 << (bits - 1)) else value) & MASK64


def addi(rd, rs, immediate):
    assert -2048 <= immediate < 2048
    return ((immediate & 4095) << 20) | (rs << 15) | (rd << 7) | 0x13


def shift(rd, rs, amount, right=False):
    assert 0 <= amount < 64
    return (amount << 20) | (rs << 15) | ((5 if right else 1) << 12) | (rd << 7) | 0x13


def csr(address, rs):
    return (address << 20) | (rs << 15) | (1 << 12) | 0x73


def sd(rs, data, offset):
    assert -2048 <= offset < 2048
    imm = offset & 4095
    return ((imm >> 5) << 25) | (data << 20) | (rs << 15) | (3 << 12) | ((imm & 31) << 7) | 0x23


def ld(rd, rs, offset):
    assert -2048 <= offset < 2048
    return ((offset & 4095) << 20) | (rs << 15) | (3 << 12) | (rd << 7) | 3


def divu(rd, left, right):
    return (1 << 25) | (right << 20) | (left << 15) | (5 << 12) | (rd << 7) | 0x33


@dataclass(frozen=True)
class Instruction:
    role: str
    word: int
    pc: int

    def decoded(self):
        w = self.word
        opcode, funct3 = w & 127, (w >> 12) & 7
        rd, rs1, rs2 = (w >> 7) & 31, (w >> 15) & 31, (w >> 20) & 31
        operation, immediate = 0, sx(w >> 20, 12)
        store, memory, system, muldiv = opcode == 0x23, opcode in (3, 0x23), opcode == 0x73, opcode == 0x33
        if opcode == 0x13:
            assert funct3 in (0, 1, 5)
            if funct3:
                assert w >> 26 == 0
                operation = 5 if funct3 == 1 else 6
            rs2 = 0
        elif muldiv:
            assert w >> 25 == 1 and funct3 == 5
        elif memory:
            assert funct3 == 3
            if store:
                rd = 0
                immediate = sx(((w >> 25) << 5) | ((w >> 7) & 31), 12)
            else:
                rs2 = 0
        elif system:
            assert funct3 == 1 and rd == 0 and w >> 20 in (0x3B0, 0x3B1, 0x3A0, 0x300)
            rs2 = 0
        else:
            raise ValueError('unsupported authored instruction')
        return {'predictedNextPc.valid': 0, 'predictedNextPc.bits': 0,
            'rename.pc': self.pc, 'rename.instruction': w, 'rename.rs1': rs1,
            'rename.rs2': rs2, 'rename.rd': rd, 'rename.writesRd': int(not store),
            'fetchFault': 0, 'fetchPageFault': 0, 'fetchTval': 0,
            'expandedInstruction': w, 'operation': operation, 'system': int(system),
            'mulDiv': int(muldiv), 'mulDivOp': 5 if muldiv else 0, 'word': 0,
            'usePc': 0, 'useImmediate': int(not (store or muldiv)),
            'immediate': immediate, 'controlFlow': 0, 'memory': int(memory),
            'atomic': 0, 'atomicOp': 0, 'store': int(store),
            'memorySize': 3 if memory else 0, 'memoryUnsigned': 0}

    def semantics(self, registers):
        d = self.decoded()
        a, b = registers[d['rename.rs1']], registers[d['rename.rs2']]
        address, value = None, 0
        if d['memory']:
            address = (a + d['immediate']) & MASK64
            value = 0 if d['store'] else READ_BEAT
        elif d['mulDiv']:
            value = a // b if b else MASK64
        elif not d['system']:
            right = d['immediate']
            value = a + right if d['operation'] == 0 else a << (right & 63) if d['operation'] == 5 else a >> (right & 63)
        return {'result': value & MASK64, 'address': address, 'store_data': b,
                'csr': self.word >> 20 if d['system'] else None,
                'csr_value': a if d['system'] else None}


def program():
    rows = [
        ('ram-low', addi(10, 0, 0x401)), ('ram-shift', shift(10, 10, 21)),
        ('pmp-lower-value', shift(30, 10, 2, True)), ('pmp-lower', csr(0x3B0, 30)),
        ('pmp-upper-a', addi(30, 0, 0x400)), ('pmp-upper-b', shift(30, 30, 11)),
        ('pmp-upper-c', addi(30, 30, 0x400)), ('pmp-upper-d', shift(30, 30, 9)),
        ('pmp-upper', csr(0x3B1, 30)), ('pmp-permissions-a', addi(30, 0, 15)),
        ('pmp-permissions-b', shift(30, 30, 8)), ('pmp-permissions', csr(0x3A0, 30)),
        ('data-privilege-a', addi(30, 0, 65)), ('data-privilege-b', shift(30, 30, 11)),
        ('data-privilege', csr(0x300, 30)), ('store-value', addi(11, 0, 0x135)),
        ('dividend', addi(25, 0, -1)), ('divisor', addi(26, 0, 7)),
        ('posted-store', sd(10, 11, 0x80)), ('older-divide', divu(24, 25, 26)),
        ('head-read', ld(20, 10, 0x108))]
    return [Instruction(role, word, RAM + 0x1000 + 4 * n) for n, (role, word) in enumerate(rows)]
