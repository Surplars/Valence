#!/usr/bin/env python3
"""Serialize existing rename_packet.cpp variant 1 plus a correctness-only tail.

The exact call/return instructions and offsets 0, 2, 6, 8, 0x1002, 0x1004
come from the independent checked-in fixture. Relocation changes only base.
The tail exercises a taken/not-taken branch and writes a signature through RAM.
This serializes ISA input bytes; it does not inspect or execute a DUT or NEMU.
"""
import hashlib
import json
from pathlib import Path

BASE = 0x80200000
DONE = BASE + 54
INSTRUCTIONS = [
    (0, 2, 0x440d, 'C.LI s0,3; original variant 1'),
    (2, 4, 0x00001497, 'AUIPC s1,1; original variant 1'),
    (6, 2, 0x9482, 'C.JALR s1; original variant 1, link=base+8'),
    (8, 2, 0x0409, 'C.ADDI s0,2; original variant 1'),
    (10, 4, 0x00300913, 'ADDI s2,zero,3; correctness tail'),
    (14, 4, 0x00140413, 'ADDI s0,s0,1; three loop iterations'),
    (18, 4, 0xfff90913, 'ADDI s2,s2,-1'),
    (22, 4, 0xfe091ce3, 'BNE s2,zero,-8; twice taken, once not taken'),
    (26, 4, 0x00400297, 'AUIPC t0,0x400; base+0x400000+26'),
    (30, 4, 0xfe628293, 'ADDI t0,t0,-26; 0x80600000'),
    (34, 4, 0x0082b023, 'SD s0,0(t0); independent signature=9'),
    (38, 4, 0x0002b303, 'LD t1,0(t0); architectural memory effect'),
    (42, 4, 0x0330000f, 'FENCE rw,rw'),
    (46, 4, 0x0000100f, 'FENCE.I; production board writes back dirty data'),
    (50, 4, 0x0330000f, 'FENCE rw,rw'),
    (54, 2, 0x0001, 'C.NOP; done retirement marker'),
    (56, 2, 0xa001, 'C.J 0; terminal self loop'),
    (0x1002, 2, 0x0405, 'C.ADDI s0,1; original variant 1'),
    (0x1004, 2, 0x8082, 'C.JR ra; original variant 1'),
    (0x1006, 2, 0x0001, 'Unexecuted padding to 4-byte reference input packing'),
]

def emit(directory):
    directory = Path(directory)
    data = bytearray(0x1008)
    occupied = set()
    for offset, size, instruction, comment in INSTRUCTIONS:
        slots = set(range(offset, offset + size))
        assert not occupied & slots and offset % 2 == 0
        occupied |= slots
        data[offset:offset+size] = instruction.to_bytes(size, 'little')
    # Decode the separately authored B-immediate to guard a transcribed offset.
    branch = int.from_bytes(data[22:26], 'little')
    immediate = ((branch >> 31) << 12) | (((branch >> 7) & 1) << 11) | (((branch >> 25) & 63) << 5) | (((branch >> 8) & 15) << 1)
    assert immediate - (8192 if immediate & 4096 else 0) == -8
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'compressed.bin').write_bytes(data)
    record = {'base': BASE, 'done': DONE, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
              'signature_address': 0x80600000, 'signature': 9,
              'origin': 'simulator/gsim/harness/rename_packet.cpp variant=1; integer-only input plus stated tail',
              'instructions': [dict(offset=o, bytes=s, encoding=hex(i), meaning=c) for o,s,i,c in INSTRUCTIONS]}
    (directory / 'compressed.json').write_text(json.dumps(record, indent=2)+'\n')
    return record

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    if output.exists():
        raise ValueError('fresh output required')
    emit(output)
