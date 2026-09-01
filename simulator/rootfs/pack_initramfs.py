#!/usr/bin/env python3
"""Create a reproducible newc initramfs containing IonSoC's bring-up init."""

import argparse
import dataclasses
import pathlib
import stat


@dataclasses.dataclass(frozen=True)
class Entry:
    name: str
    mode: int
    data: bytes = b""
    rdev_major: int = 0
    rdev_minor: int = 0


def pad(output: bytearray, alignment: int) -> None:
    output.extend(b"\0" * (-len(output) % alignment))


def append_entry(output: bytearray, inode: int, entry: Entry) -> None:
    name = entry.name.encode() + b"\0"
    fields = (
        inode,
        entry.mode,
        0,
        0,
        2 if stat.S_ISDIR(entry.mode) else 1,
        0,
        len(entry.data),
        0,
        0,
        entry.rdev_major,
        entry.rdev_minor,
        len(name),
        0,
    )
    output.extend(b"070701" + b"".join(f"{value:08x}".encode() for value in fields))
    output.extend(name)
    pad(output, 4)
    output.extend(entry.data)
    pad(output, 4)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()

    entries = [
        Entry(".", stat.S_IFDIR | 0o755),
        Entry("dev", stat.S_IFDIR | 0o755),
        Entry("dev/console", stat.S_IFCHR | 0o600, rdev_major=5, rdev_minor=1),
        Entry("proc", stat.S_IFDIR | 0o555),
        Entry("sys", stat.S_IFDIR | 0o555),
        Entry("tmp", stat.S_IFDIR | 0o777),
        Entry("init", stat.S_IFREG | 0o755, args.init.read_bytes()),
        Entry("TRAILER!!!", 0),
    ]

    output = bytearray()
    for inode, entry in enumerate(entries, start=1):
        append_entry(output, inode, entry)
    pad(output, 512)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    print(f"Wrote {args.output} ({len(output)} bytes)")


if __name__ == "__main__":
    main()
