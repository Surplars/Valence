#!/usr/bin/env python3
"""Execute compiled RV64I uart_init against a tiny independent 16550 register model.

This checks actual binary semantics, not just build arguments or a ROM hash.
Unsupported instruction/MMIO access fails closed. No serial port is opened.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

MASK = (1 << 64) - 1
UART = 0x10000000


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def audit(binary, elf, reference_hz, baud, prefix="riscv64-unknown-elf-"):
    data = Path(binary).read_bytes()
    symbols = {}
    for line in subprocess.check_output([prefix + "nm", "--defined-only", str(elf)], text=True).splitlines():
        fields = line.split()
        if len(fields) == 3:
            symbols[fields[2]] = int(fields[0], 16)
    pc, base = symbols["uart_init"], symbols["_start"]
    registers = [0] * 32
    registers[1] = MASK - 3  # Return sentinel, deliberately outside ROM.
    lcr, dll, dlm, ier, fcr = 0, None, None, None, None
    writes = []
    for _ in range(256):
        offset = pc - base
        if offset < 0 or offset + 4 > len(data) or offset % 4:
            raise ValueError("uart_init escaped aligned compiled ROM")
        instruction = int.from_bytes(data[offset:offset + 4], "little")
        opcode, rd = instruction & 127, (instruction >> 7) & 31
        funct3, rs1, rs2 = (instruction >> 12) & 7, (instruction >> 15) & 31, (instruction >> 20) & 31
        immediate = signed(instruction >> 20, 12)
        following = pc + 4
        if opcode == 0x37:
            registers[rd] = signed(instruction & 0xfffff000, 32) & MASK
        elif opcode == 0x13 and funct3 in (0, 7):
            registers[rd] = ((registers[rs1] + immediate) if funct3 == 0 else
                             (registers[rs1] & (immediate & MASK))) & MASK
        elif opcode == 0x03 and funct3 == 4:
            if (registers[rs1] + immediate) & MASK != UART + 5:
                raise ValueError("Unexpected uart_init MMIO read")
            registers[rd] = 0x60  # TEMT and THRE: UART quiescent at reset.
        elif opcode == 0x63 and funct3 == 0:
            branch = ((instruction >> 31) << 12) | (((instruction >> 7) & 1) << 11) | (
                ((instruction >> 25) & 63) << 5) | (((instruction >> 8) & 15) << 1)
            if registers[rs1] == registers[rs2]:
                following = pc + signed(branch, 13)
        elif opcode == 0x23 and funct3 == 0:
            displacement = signed(((instruction >> 25) << 5) | ((instruction >> 7) & 31), 12)
            address, value = (registers[rs1] + displacement) & MASK, registers[rs2] & 255
            writes.append(dict(address=hex(address), value=value, dlab=bool(lcr & 128)))
            if address == UART + 3:
                lcr = value
            elif address == UART and lcr & 128:
                dll = value
            elif address == UART + 1:
                if lcr & 128:
                    dlm = value
                else:
                    ier = value
            elif address == UART + 2:
                fcr = value
            else:
                raise ValueError("Unexpected UART write or DLAB ordering")
        elif opcode == 0x67 and funct3 == 0 and rd == 0 and rs1 == 1 and immediate == 0:
            break
        else:
            raise ValueError(f"Unsupported compiled uart_init instruction 0x{instruction:08x}")
        registers[0] = 0
        pc = following
    else:
        raise ValueError("uart_init did not return within bounded instruction budget")
    if dll is None or dlm is None:
        raise ValueError("DLL/DLM were not both written while DLAB was enabled")
    divisor = dll | dlm << 8
    if not divisor or reference_hz != 16 * baud * divisor:
        raise ValueError(f"Compiled UART baud mismatch: reference={reference_hz}, divisor={divisor}, expected={baud}")
    if (lcr, ier, fcr) != (3, 0, 7):
        raise ValueError("Compiled UART must leave 8N1, interrupts disabled, FIFO enabled and reset")
    return dict(status="PASS_COMPILED_BOOTROM_UART_CONTRACT", reference_hz=reference_hz,
                baud=baud, divisor=divisor, lcr=lcr, ier=ier, fcr=fcr, writes=writes,
                binary_sha256=hashlib.sha256(data).hexdigest(),
                elf_sha256=hashlib.sha256(Path(elf).read_bytes()).hexdigest(),
                auditor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--reference-hz", type=int, required=True)
    parser.add_argument("--baud", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.rom / "bootrom.bin", args.rom / "bootrom.elf", args.reference_hz, args.baud)
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["status"], "DLL/DLM=", result["divisor"], "FCR=", result["fcr"])


if __name__ == "__main__":
    main()
