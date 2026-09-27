#!/usr/bin/env python3
"""Pack several ELF64 images and addressed blobs into one load-only ELF."""

import argparse
import dataclasses
import pathlib
import struct
import sys


ELF_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
PROGRAM_HEADER = struct.Struct("<IIQQQQQQ")
PT_LOAD = 1
EM_RISCV = 243


@dataclasses.dataclass
class Segment:
    address: int
    data: bytes
    memory_size: int
    flags: int
    source: str
    file_offset: int = 0


def integer(value: str) -> int:
    return int(value, 0)


def load_elf(path: pathlib.Path) -> list[Segment]:
    raw = path.read_bytes()
    if len(raw) < ELF_HEADER.size:
        raise ValueError(f"{path}: file is too small for ELF64")
    fields = ELF_HEADER.unpack_from(raw)
    ident = fields[0]
    if ident[:4] != b"\x7fELF" or ident[4] != 2 or ident[5] != 1:
        raise ValueError(f"{path}: only little-endian ELF64 is supported")
    phoff, phentsize, phnum = fields[5], fields[9], fields[10]
    if phentsize != PROGRAM_HEADER.size:
        raise ValueError(f"{path}: unsupported program-header size {phentsize}")

    segments: list[Segment] = []
    for index in range(phnum):
        offset = phoff + index * phentsize
        if offset + phentsize > len(raw):
            raise ValueError(f"{path}: truncated program headers")
        p_type, flags, file_offset, vaddr, paddr, file_size, memory_size, _ = PROGRAM_HEADER.unpack_from(raw, offset)
        if p_type != PT_LOAD or memory_size == 0:
            continue
        if file_offset + file_size > len(raw):
            raise ValueError(f"{path}: truncated PT_LOAD segment {index}")
        address = paddr or vaddr
        segments.append(Segment(address, raw[file_offset : file_offset + file_size], memory_size, flags, str(path)))
    if not segments:
        raise ValueError(f"{path}: contains no loadable segments")
    return segments


def addressed_blob(spec: str) -> Segment:
    try:
        address_text, path_text = spec.split(":", 1)
    except ValueError as error:
        raise ValueError(f"invalid blob '{spec}', expected ADDRESS:PATH") from error
    path = pathlib.Path(path_text)
    data = path.read_bytes()
    return Segment(integer(address_text), data, len(data), 4, str(path))


def align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def validate(segments: list[Segment]) -> None:
    segments.sort(key=lambda segment: segment.address)
    for previous, current in zip(segments, segments[1:]):
        previous_end = previous.address + previous.memory_size
        if previous_end > current.address:
            raise ValueError(
                f"overlapping images: {previous.source} ends at 0x{previous_end:x}, "
                f"but {current.source} starts at 0x{current.address:x}"
            )


def write_elf(path: pathlib.Path, entry: int, segments: list[Segment]) -> None:
    validate(segments)
    cursor = align(ELF_HEADER.size + PROGRAM_HEADER.size * len(segments), 0x1000)
    for segment in segments:
        segment.file_offset = cursor
        cursor = align(cursor + len(segment.data), 0x1000)

    output = bytearray(cursor)
    ident = bytearray(16)
    ident[:7] = b"\x7fELF\x02\x01\x01"
    ELF_HEADER.pack_into(
        output,
        0,
        bytes(ident),
        2,
        EM_RISCV,
        1,
        entry,
        ELF_HEADER.size,
        0,
        0,
        ELF_HEADER.size,
        PROGRAM_HEADER.size,
        len(segments),
        0,
        0,
        0,
    )
    for index, segment in enumerate(segments):
        PROGRAM_HEADER.pack_into(
            output,
            ELF_HEADER.size + index * PROGRAM_HEADER.size,
            PT_LOAD,
            segment.flags,
            segment.file_offset,
            segment.address,
            segment.address,
            len(segment.data),
            segment.memory_size,
            1,
        )
        output[segment.file_offset : segment.file_offset + len(segment.data)] = segment.data

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--entry", required=True, type=integer)
    parser.add_argument("--elf", action="append", default=[], type=pathlib.Path)
    parser.add_argument("--blob", action="append", default=[])
    args = parser.parse_args()

    try:
        segments = [segment for elf in args.elf for segment in load_elf(elf)]
        segments.extend(addressed_blob(blob) for blob in args.blob)
        if not segments:
            raise ValueError("at least one --elf or --blob is required")
        write_elf(args.output, args.entry, segments)
    except (OSError, ValueError) as error:
        print(f"merge_elf.py: {error}", file=sys.stderr)
        return 1

    print(f"Wrote {args.output} with {len(segments)} loadable segments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
