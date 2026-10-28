#!/usr/bin/env python3
"""Narrow source-semantic reference; no DUT or repository ISA oracle imports.

This is deliberately not a general assembler/emulator. It interprets the fixed
branch source and independently encodes its declared RV64I operations, preserving
the source labels and repeat structure. Generated expected bytes are not an ELF
or a CPU execution result. A linked ELF can be checked, but never executed here.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

MASK = (1 << 64) - 1
ROM_BASE = 0x80000000
RAM_BASE = 0x80200000
RAM_BYTES = 128 * 1024
TAIL = """
.globl roi_begin, roi_end, benchmark_complete, benchmark_terminal
.set roi_begin, _start
roi_end:
    addi x0, x0, 0
benchmark_complete:
    addi x0, x0, 0
benchmark_terminal:
    ebreak
.rept 128
    addi x0, x0, 0
.endr
"""
BRANCH_FUNCT3 = {"beq": 0, "bne": 1, "blt": 4, "bge": 5, "bltu": 6, "bgeu": 7}
EVENT_FIELDS = ("pc", "instruction", "nextPc", "rd", "writes", "data")


class ReferenceError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReferenceError(message)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def signed(value: int, bits: int) -> int:
    value &= (1 << bits) - 1
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def register(text: str) -> int:
    require(re.fullmatch(r"x(?:[0-9]|[12][0-9]|3[01])", text) is not None, f"bad register {text}")
    return int(text[1:])


def expression(text: str, labels: dict[str, int]) -> int:
    text = text.strip()
    try:
        return int(text, 0)
    except ValueError:
        match = re.fullmatch(r"([A-Za-z_.$][\w.$]*)(?:([+-])(0x[0-9a-fA-F]+|[0-9]+))?", text)
        require(match is not None and match[1] in labels, f"unknown expression {text}")
        value = labels[match[1]]
        if match[2]:
            amount = int(match[3], 0)
            value += amount if match[2] == "+" else -amount
        return value


@dataclass(frozen=True)
class Op:
    pc: int
    mnemonic: str
    operands: tuple[str, ...]
    source_line: str


def expand_repeats(lines: list[str], index: int = 0, nested: bool = False) -> tuple[list[str], int]:
    expanded: list[str] = []
    while index < len(lines):
        line = lines[index]
        index += 1
        if line == ".endr":
            require(nested, "unmatched .endr")
            return expanded, index
        if line.startswith(".rept "):
            repeat = int(line.split()[1], 0)
            require(0 <= repeat <= 1024, "unbounded repeat")
            inner, index = expand_repeats(lines, index, True)
            expanded.extend(inner * repeat)
        else:
            expanded.append(line)
        require(len(expanded) <= 10000, "source expansion bound")
    require(not nested, "unterminated .rept")
    return expanded, index


class SourceProgram:
    def __init__(self, source: str, tail: str = TAIL):
        self.source = source
        self.tail = tail
        self.labels: dict[str, int] = {}
        self.ops: dict[int, Op] = {}
        self.original_end: int | None = None
        aliases: list[tuple[str, str]] = []
        cleaned = [line.split("#", 1)[0].strip() for line in (source + "\n" + tail).splitlines()]
        lines, _ = expand_repeats([line for line in cleaned if line])
        pc = RAM_BASE
        for line in lines:
            if line.endswith(":"):
                name = line[:-1]
                require(re.fullmatch(r"[A-Za-z_.$][\w.$]*", name) is not None, f"bad label {name}")
                require(name not in self.labels, f"duplicate label {name}")
                self.labels[name] = pc
                if name == ".Lend":
                    self.original_end = pc
                continue
            if line.startswith(".option "):
                require(line in (".option norvc", ".option norelax"), "unsupported option")
                continue
            if line.startswith(".section "):
                require(line == ".section .text", "only .text is supported")
                continue
            if line.startswith((".global ", ".globl ")):
                continue
            if line.startswith(".set "):
                parts = line[5:].split(",")
                require(len(parts) == 2, "invalid alias")
                aliases.append(tuple(part.strip() for part in parts))
                continue
            parts = line.split(None, 1)
            operands = tuple(part.strip() for part in parts[1].split(",")) if len(parts) == 2 else ()
            self.ops[pc] = Op(pc, parts[0], operands, line)
            pc += 4
            require(pc <= RAM_BASE + RAM_BYTES, "text exceeds common RAM")
        for name, target in aliases:
            require(name not in self.labels, f"duplicate alias {name}")
            self.labels[name] = expression(target, self.labels)
        require(self.labels.get("_start") == RAM_BASE, "entry must be start of common RAM")
        self.end = pc
        self.ops[ROM_BASE] = Op(ROM_BASE, "auipc", ("x31", "0x200"), "common boot AUIPC")
        self.ops[ROM_BASE + 4] = Op(ROM_BASE + 4, "jalr", ("x0", "0(x31)"), "common boot JALR")
        self.words = {address: self.encode(op) for address, op in self.ops.items()}
        require(self.words[ROM_BASE] == 0x00200F97 and self.words[ROM_BASE + 4] == 0x000F8067,
                "independently encoded boot differs from fixed common contract")

    def immediate(self, op: Op, token: str) -> int:
        high = re.fullmatch(r"%pcrel_hi\((.+)\)", token)
        if high:
            displacement = expression(high[1], self.labels) - op.pc
            return ((displacement + 0x800) >> 12) & 0xFFFFF
        low = re.fullmatch(r"%pcrel_lo\((.+)\)", token)
        if low:
            anchor = expression(low[1], self.labels)
            require(anchor in self.ops, "pcrel low anchor absent")
            upper_op = self.ops[anchor]
            require(upper_op.mnemonic == "auipc" and len(upper_op.operands) == 2, "pcrel low anchor not AUIPC")
            target = re.fullmatch(r"%pcrel_hi\((.+)\)", upper_op.operands[1])
            require(target is not None, "pcrel low anchor lacks high expression")
            displacement = expression(target[1], self.labels) - anchor
            return displacement - (((displacement + 0x800) >> 12) << 12)
        return expression(token, self.labels)

    def encode(self, op: Op) -> int:
        m, a = op.mnemonic, op.operands
        if m == ".word":
            require(len(a) == 1 and expression(a[0], self.labels) == 0, "only deliberate illegal .word 0 is allowed")
            return 0
        if m == "ebreak":
            require(not a, "EBREAK operands")
            return 0x00100073
        if m in ("addi", "ori"):
            require(len(a) == 3, f"{m} operands")
            rd, rs1 = register(a[0]), register(a[1])
            imm = self.immediate(op, a[2])
            require(-2048 <= imm <= 2047, "I immediate range")
            return ((imm & 0xFFF) << 20) | (rs1 << 15) | ((6 if m == "ori" else 0) << 12) | (rd << 7) | 0x13
        if m == "xor":
            require(len(a) == 3, "XOR operands")
            rd, rs1, rs2 = map(register, a)
            return (rs2 << 20) | (rs1 << 15) | (4 << 12) | (rd << 7) | 0x33
        if m == "auipc":
            require(len(a) == 2, "AUIPC operands")
            imm = self.immediate(op, a[1])
            require(0 <= imm < (1 << 20), "U immediate range")
            return (imm << 12) | (register(a[0]) << 7) | 0x17
        if m == "jalr":
            require(len(a) == 2, "JALR operands")
            address = re.fullmatch(r"(-?(?:0x[0-9a-fA-F]+|\d+))\((x\d+)\)", a[1])
            require(address is not None, "JALR address format")
            imm = int(address[1], 0)
            require(-2048 <= imm <= 2047, "JALR immediate range")
            return ((imm & 0xFFF) << 20) | (register(address[2]) << 15) | (register(a[0]) << 7) | 0x67
        if m == "jal":
            require(len(a) == 2, "JAL operands")
            offset = expression(a[1], self.labels) - op.pc
            require(-(1 << 20) <= offset < (1 << 20) and offset % 2 == 0, "J displacement range")
            bits = offset & 0x1FFFFF
            return (((bits >> 20) & 1) << 31) | (((bits >> 1) & 0x3FF) << 21) | (((bits >> 11) & 1) << 20) | (((bits >> 12) & 0xFF) << 12) | (register(a[0]) << 7) | 0x6F
        if m in BRANCH_FUNCT3:
            require(len(a) == 3, "branch operands")
            offset = expression(a[2], self.labels) - op.pc
            require(-4096 <= offset <= 4094 and offset % 2 == 0, "B displacement range")
            bits = offset & 0x1FFF
            return (((bits >> 12) & 1) << 31) | (((bits >> 5) & 0x3F) << 25) | (register(a[1]) << 20) | (register(a[0]) << 15) | (BRANCH_FUNCT3[m] << 12) | (((bits >> 1) & 0xF) << 8) | (((bits >> 11) & 1) << 7) | 0x63
        raise ReferenceError(f"unsupported source operation {m}")

    def text_bytes(self) -> bytes:
        return b"".join(self.words[pc].to_bytes(4, "little") for pc in range(RAM_BASE, self.end, 4))

    def execute(self, op: Op, registers: list[int]) -> dict:
        """Evaluate source operands before architectural destination update."""
        require(len(registers) == 32 and registers[0] == 0, "invalid input GPR state")
        m, a, pc = op.mnemonic, op.operands, op.pc
        rd, value, next_pc = 0, 0, (pc + 4) & MASK
        if m in ("addi", "ori"):
            rd, rs1 = register(a[0]), register(a[1])
            imm = self.immediate(op, a[2])
            value = registers[rs1] + imm if m == "addi" else registers[rs1] | (imm & MASK)
        elif m == "xor":
            rd, rs1, rs2 = map(register, a)
            value = registers[rs1] ^ registers[rs2]
        elif m == "auipc":
            rd = register(a[0])
            value = pc + signed(self.immediate(op, a[1]) << 12, 32)
        elif m == "jal":
            rd, value = register(a[0]), pc + 4
            next_pc = expression(a[1], self.labels) & MASK
        elif m == "jalr":
            rd = register(a[0])
            address = re.fullmatch(r"(-?(?:0x[0-9a-fA-F]+|\d+))\((x\d+)\)", a[1])
            require(address is not None, "invalid JALR")
            # This read MUST precede rd write when rd==rs1.
            old_source = registers[register(address[2])]
            next_pc = ((old_source + int(address[1], 0)) & MASK) & ~1
            value = pc + 4
        elif m in BRANCH_FUNCT3:
            left, right = registers[register(a[0])], registers[register(a[1])]
            predicates = {"beq": left == right, "bne": left != right,
                          "blt": signed(left, 64) < signed(right, 64),
                          "bge": signed(left, 64) >= signed(right, 64),
                          "bltu": left < right, "bgeu": left >= right}
            if predicates[m]:
                next_pc = expression(a[2], self.labels) & MASK
        elif m in (".word", "ebreak"):
            raise ReferenceError(f"unexpected {m} at {pc:#x}")
        else:
            raise ReferenceError(f"unsupported operation {m}")
        require(next_pc % 4 == 0, f"misaligned control target {next_pc:#x}")
        value &= MASK
        if rd:
            registers[rd] = value
        registers[0] = 0
        return {"pc": pc, "instruction": self.words.get(pc, self.encode(op)), "nextPc": next_pc,
                "rd": rd, "writes": bool(rd), "data": value if rd else 0}

    def run(self, bound: int = 10000) -> dict:
        names = ("roi_begin", "roi_end", "benchmark_complete", "benchmark_terminal")
        require(all(name in self.labels for name in names), "required marker missing")
        require(self.labels["roi_begin"] == RAM_BASE, "ROI begin must alias original entry")
        require(self.labels["roi_begin"] < self.labels["roi_end"] < self.labels["benchmark_complete"] < self.labels["benchmark_terminal"], "marker address order")
        registers = [0] * 32
        pc, events = ROM_BASE, []
        begin = end = complete = None
        for _ in range(bound):
            require(pc in self.ops, f"execution outside fixed program at {pc:#x}")
            op = self.ops[pc]
            if pc == self.labels["benchmark_terminal"]:
                require(op.mnemonic == "ebreak" and self.words[pc] == 0x00100073, "terminal is not EBREAK")
                require(begin is not None and end is not None and complete is not None and begin < end < complete < len(events), "missing or unordered retired ROI/completion marker")
                text = self.text_bytes()
                return {"schema": "branch-source-reference-v1", "source_sha256": sha(self.source.encode()),
                        "evaluator_sha256": sha(Path(__file__).read_bytes()), "tail_sha256": sha(self.tail.encode()),
                        "text_sha256": sha(text), "text_bytes": len(text),
                        "original_body_bytes": None if self.original_end is None else self.original_end - RAM_BASE,
                        "markers": {name: self.labels[name] for name in ("_start", *names)},
                        "events": events, "regs": registers, "retired": len(events),
                        "roi_begin_index": begin, "roi_end_index": end,
                        "terminal": {"pc": pc, "cause": 3, "tval": pc}}
            if pc == self.labels["roi_begin"]:
                require(begin is None, "duplicate ROI begin")
                begin = len(events)
            if pc == self.labels["roi_end"]:
                require(begin is not None and end is None, "unmatched/duplicate ROI end")
                end = len(events)
            if pc == self.labels["benchmark_complete"]:
                require(end is not None and complete is None, "unmatched/duplicate completion")
                complete = len(events)
            event = self.execute(op, registers)
            events.append(event)
            pc = event["nextPc"]
        raise ReferenceError(f"instruction bound {bound} before terminal")


def compare_transcripts(expected: dict, actual: dict) -> None:
    """Exact architectural comparator; never fixes/resynchronizes a mismatch."""
    for name in ("regs", "retired", "roi_begin_index", "roi_end_index", "terminal"):
        require(name in actual and expected[name] == actual[name], f"transcript {name} mismatch")
    require("events" in actual and len(expected["events"]) == len(actual["events"]), "transcript event count mismatch")
    for index, (left, right) in enumerate(zip(expected["events"], actual["events"])):
        for name in EVENT_FIELDS:
            require(name in right and left[name] == right[name], f"transcript event {index} {name} mismatch")


def inspect_elf(path: Path, program: SourceProgram) -> dict:
    """Strict ELF container inspection only; no emulator or executable launch."""
    data = path.read_bytes()
    require(len(data) >= 64, "short ELF")
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", data)
    ident, kind, machine = header[:3]
    require(ident[:4] == b"\x7fELF" and ident[4:7] == bytes([2, 1, 1]), "not little-endian ELF64")
    require(kind == 2 and machine == 243 and header[3] == 1, "ELF must be RISC-V ET_EXEC")
    entry, phoff, shoff = header[4:7]
    ehsize, phsize, phnum, shsize, shnum, shstr = header[8:14]
    require(entry == RAM_BASE and ehsize == 64 and phsize == 56 and shsize == 64, "ELF ABI/layout mismatch")
    require(0 < phnum <= 32 and 0 < shnum <= 256 and shstr < shnum, "ELF table count")
    require(phoff + phsize * phnum <= len(data) and shoff + shsize * shnum <= len(data), "ELF table bounds")
    segments = []
    for index in range(phnum):
        p = struct.unpack_from("<IIQQQQQQ", data, phoff + index * phsize)
        if p[0] != 1:
            continue
        _, flags, offset, virtual, physical, filesz, memsz, alignment = p
        require(virtual == physical and 0 < memsz <= RAM_BYTES and RAM_BASE <= physical and physical + memsz <= RAM_BASE + RAM_BYTES,
                "ELF LOAD outside common RAM")
        require(filesz <= memsz and offset + filesz <= len(data), "ELF LOAD file bounds")
        require(not (flags & 2), "branch ELF unexpectedly writable")
        segments.append((physical, offset, filesz, memsz))
    require(segments, "ELF missing LOAD")
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, shoff + index * shsize) for index in range(shnum)]
    def section_bytes(section):
        require(section[4] + section[5] <= len(data), "ELF section bounds")
        return data[section[4]:section[4] + section[5]]
    strings = section_bytes(sections[shstr])
    def string(table, at):
        require(at < len(table), "ELF string offset")
        end = table.find(b"\0", at)
        require(end >= 0, "ELF unterminated string")
        return table[at:end].decode("ascii")
    named = {string(strings, section[0]): section for section in sections}
    require(".text" in named, "ELF .text absent")
    text_section = named[".text"]
    expected_text = program.text_bytes()
    require(text_section[3] == RAM_BASE and section_bytes(text_section) == expected_text, "ELF .text differs from independent source encoding")
    require(any(start <= RAM_BASE and RAM_BASE + len(expected_text) <= start + filesz and data[offset + RAM_BASE - start:offset + RAM_BASE - start + len(expected_text)] == expected_text
                for start, offset, filesz, _ in segments), "ELF .text not mapped by LOAD")
    symbols = {}
    required_symbols = ("_start", "roi_begin", "roi_end", "benchmark_complete", "benchmark_terminal")
    for section in sections:
        require(section[1] not in (4, 9) or section[5] == 0, "ELF still has relocations")
        if section[1] != 2:
            continue
        require(section[9] == 24 and section[5] % 24 == 0 and section[6] < len(sections), "ELF symbol table layout")
        symbol_strings = section_bytes(sections[section[6]])
        raw = section_bytes(section)
        for offset in range(0, len(raw), 24):
            symbol = struct.unpack_from("<IBBHQQ", raw, offset)
            if symbol[0] and symbol[3]:
                name = string(symbol_strings, symbol[0])
                # RISC-V local mapping symbols ($x/$d) repeat by design. Only
                # exported entry/marker identities are part of this contract.
                if name in required_symbols:
                    require(symbol[1] >> 4 == 1, f"ELF marker {name} not global")
                    require(name not in symbols, f"duplicate ELF marker {name}")
                    symbols[name] = symbol[4]
    for name in required_symbols:
        require(symbols.get(name) == program.labels[name], f"ELF marker {name} mismatch")
    return {"elf_sha256": sha(data), "entry": entry, "text_sha256": sha(expected_text),
            "status": "PASS_EXACT_SOURCE_ENCODING_LOAD_AND_MARKERS", "cpu_executed": False}


def write_header(result: dict, path: Path) -> None:
    require(result.get("cross_reference_check") == "PASS_EXACT_ARCHITECTURAL_TRACE" and "elf_check" in result,
            "header export requires linked ELF and distinct reference agreement")
    lines = ["#pragma once", "#include <array>", "#include <cstdint>",
             "namespace branch_source_gold {",
             "struct Event { uint64_t pc; uint32_t instruction; uint64_t nextPc; unsigned rd; bool writes; uint64_t data; };",
             f'inline constexpr char source_sha256[] = "{result["source_sha256"]}";',
             f'inline constexpr char evaluator_sha256[] = "{result["evaluator_sha256"]}";',
             f'inline constexpr char elf_sha256[] = "{result["elf_check"]["elf_sha256"]}";',
             f'inline constexpr char distinct_reference_sha256[] = "{result["distinct_reference_sha256"]}";',
             f'inline constexpr std::array<Event, {len(result["events"])}> events{{{{']
    for event in result["events"]:
        lines.append("    {0x%xULL, 0x%08xU, 0x%xULL, %du, %s, 0x%xULL}," %
                     (event["pc"], event["instruction"], event["nextPc"], event["rd"],
                      "true" if event["writes"] else "false", event["data"]))
    lines.extend(["}};", "inline constexpr std::array<uint64_t,32> regs{{" +
                  ",".join(f"0x{value:x}ULL" for value in result["regs"]) + "}};"])
    for name in ("retired", "roi_begin_index", "roi_end_index"):
        lines.append(f"inline constexpr uint64_t {name} = {result[name]}ULL;")
    for name in ("pc", "cause", "tval"):
        lines.append(f"inline constexpr uint64_t terminal_{name} = 0x{result['terminal'][name]:x}ULL;")
    lines.append("} // namespace branch_source_gold")
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--text-out", type=Path)
    parser.add_argument("--elf", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--header-out", type=Path)
    args = parser.parse_args()
    try:
        program = SourceProgram(args.source.read_text())
        result = program.run()
        if args.elf:
            result["elf_check"] = inspect_elf(args.elf, program)
        if args.compare:
            distinct_bytes = args.compare.read_bytes()
            compare_transcripts(result, json.loads(distinct_bytes))
            result["distinct_reference_sha256"] = sha(distinct_bytes)
            result["cross_reference_check"] = "PASS_EXACT_ARCHITECTURAL_TRACE"
        if args.header_out:
            write_header(result, args.header_out)
        if args.text_out:
            args.text_out.write_bytes(program.text_bytes())
        args.out.write_text(json.dumps(result, indent=2) + "\n")
        print(f"SOURCE_REFERENCE_PASS retired={result['retired']} roi_retired={result['roi_end_index'] - result['roi_begin_index']} text_sha256={result['text_sha256']}")
        return 0
    except (ReferenceError, ValueError, OSError, struct.error) as error:
        print(f"SOURCE_REFERENCE_FAIL {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
