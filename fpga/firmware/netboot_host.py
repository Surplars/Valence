#!/usr/bin/env python3
"""Explicitly started static-IP TFTP server + Valence checked-image packer.

No firewall/network configuration or board reset is performed by this tool.
Serve the packed image on a trusted, directly connected Ethernet segment only.
"""
import argparse
from dataclasses import dataclass
import ipaddress
from pathlib import Path
import socket
import struct
import sys
import time
import zlib

BASE = 0x80200000
LIMIT = 512 * 1024 * 1024 - 0x4000
LIMITS = {"ddr": LIMIT, "ddr1g": 0x40000000 - 0x4000, "ddr2g": 0xffff8000 - BASE}
MAGIC = 0x31444C56

def header(length, crc, base=BASE, entry=BASE, limit=LIMIT):
    if limit not in LIMITS.values() or base != BASE or not 0 < length <= limit or entry & 3 or not base <= entry < base + length:
        raise ValueError("image outside selected DDR download/entry range")
    first = struct.pack("<8I", MAGIC, 1, base, entry, length, crc, 256, 0)
    return first + struct.pack("<I", zlib.crc32(first))

def pack(image, output, entry=BASE, limit=LIMIT):
    image, output = Path(image), Path(output)
    if image.resolve() == output.resolve():
        raise ValueError("output must not replace the input image")
    if output.exists():
        raise ValueError("output already exists; use a new file name")
    length, crc = 0, 0
    with image.open("rb") as source:
        while data := source.read(1024 * 1024):
            length += len(data)
            if length > limit:
                raise ValueError("image overlaps BootROM globals/stack")
            crc = zlib.crc32(data, crc)
    prefix = header(length, crc, entry=entry, limit=limit)
    with output.open("xb") as dest, image.open("rb") as source:
        dest.write(prefix)
        while data := source.read(1024 * 1024):
            dest.write(data)
    print(f"PACKED {output} payload={length} entry=0x{entry:08x} CRC32={crc:08x}")

def validate(image, limit=LIMIT):
    with image.open("rb") as source:
        prefix = source.read(36)
        if len(prefix) != 36:
            raise ValueError("not a packed Valence image")
        magic, version, base, entry, length, crc, chunk, flags, check = struct.unpack("<9I", prefix)
        if magic != MAGIC or version != 1 or chunk != 256 or flags or check != zlib.crc32(prefix[:32]):
            raise ValueError("invalid packed-image header")
        if header(length, crc, base, entry, limit) != prefix:
            raise ValueError("invalid packed-image range")
        actual, count = 0, 0
        while data := source.read(1024 * 1024):
            actual = zlib.crc32(data, actual)
            count += len(data)
        if count != length or actual != crc:
            raise ValueError("packed-image length/CRC mismatch")
    return length

def request(packet):
    if len(packet) > 200 or not packet.startswith(b"\x00\x01"):
        return None
    fields = packet[2:].split(b"\x00")
    if len(fields) != 3 or fields[2] or fields[1].lower() != b"octet":
        return None
    try:
        name = fields[0].decode("ascii")
    except UnicodeDecodeError:
        return None
    if not name or len(name) > 127 or any(c not in
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in name):
        return None
    return name

class TransferProgress:
    """Throttled ACKed-byte progress; 100% includes the final EOF ACK."""
    def __init__(self, size, stream=None, clock=None, interval=0.25):
        self.size = size
        self.stream = sys.stdout if stream is None else stream
        self.clock = time.monotonic if clock is None else clock
        self.inline = self.stream.isatty()
        self.interval = interval if self.inline else max(interval, 1.0)
        self.started = self.clock()
        self.last_update = self.started
        self.total = 0
        self.width = 0
        self.closed = False
        self.update(0, force=True)

    def update(self, total, complete=False, force=False):
        self.total = total
        now = self.clock()
        if not (complete or force) and now - self.last_update < self.interval:
            return
        elapsed = max(0.0, now - self.started)
        rate = total / elapsed if elapsed > 0 else 0.0
        fraction = min(1.0, total / self.size) if self.size else float(complete)
        if not complete:
            fraction = min(fraction, 0.999)
        filled = int(20 * fraction)
        eta = f"{max(0, self.size - total) / rate:.1f}s" if rate else "--"
        line = (f"TFTP [{'#' * filled}{'-' * (20 - filled)}] {fraction * 100:5.1f}% "
                f"{total:,}/{self.size:,} bytes {rate / 1048576:.3f} MiB/s ETA {eta}")
        if self.inline:
            self.width = max(self.width, len(line))
            print("\r" + line.ljust(self.width), end="\n" if complete else "",
                  file=self.stream, flush=True)
        else:
            print(line, file=self.stream, flush=True)
        self.last_update = now
        if complete:
            self.closed = True

    def close(self):
        if not self.closed and self.inline:
            print(file=self.stream, flush=True)
        self.closed = True


@dataclass
class TransferStats:
    """Host observations only. An EOF ACK does not prove board RAM verification."""
    bytes_acked: int = 0
    data_packets: int = 0
    acked_blocks: int = 0
    retransmits: int = 0
    timeouts: int = 0
    reply_packets: int = 0
    ignored_packets: int = 0
    read_seconds: float = 0.0
    send_seconds: float = 0.0
    ack_wait_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    eof_acked: bool = False

    def summary(self):
        other = max(0.0, self.elapsed_seconds - self.read_seconds -
                    self.send_seconds - self.ack_wait_seconds)
        return (f"TFTP STATS bytes_acked={self.bytes_acked} data_packets={self.data_packets} "
                f"acked_blocks={self.acked_blocks} retransmits={self.retransmits} "
                f"timeouts={self.timeouts} rx_packets={self.reply_packets} "
                f"ignored_packets={self.ignored_packets} read={self.read_seconds:.6f}s "
                f"send={self.send_seconds:.6f}s ack_wait={self.ack_wait_seconds:.6f}s "
                f"other={other:.6f}s elapsed={self.elapsed_seconds:.6f}s "
                f"eof_acked={'yes' if self.eof_acked else 'no'}")


def transfer(sock, peer, source, retry_seconds=1, retries=10, progress=None, stats=None, clock=None):
    """Window 1, 512-byte DATA, including rollover and the short/zero EOF ACK.

    Pass a fresh TransferStats to retain counters on success or failure. Timings
    are wall time in source.read, sendto and the ACK wait loop, not CPU timings.
    """
    stats = TransferStats() if stats is None else stats
    clock = time.monotonic if clock is None else clock
    started = clock()
    try:
        return _transfer(sock, peer, source, retry_seconds, retries, progress, stats, clock)
    finally:
        stats.elapsed_seconds = max(0.0, clock() - started)


def _transfer(sock, peer, source, retry_seconds, retries, progress, stats, clock):
    block, total = 1, 0
    while True:
        started = clock()
        try:
            data = source.read(512)
        finally:
            stats.read_seconds += clock() - started
        wire_block = block & 0xffff
        packet = struct.pack("!HH", 3, wire_block) + data
        expected_ack = struct.pack("!HH", 4, wire_block)
        acked = False
        for attempt in range(retries):
            started = clock()
            try:
                sock.sendto(packet, peer)
            finally:
                stats.send_seconds += clock() - started
            stats.data_packets += 1
            stats.retransmits += int(attempt != 0)
            started = clock()
            deadline = started + retry_seconds
            try:
                while clock() < deadline:
                    sock.settimeout(max(0.001, deadline - clock()))
                    try:
                        reply, who = sock.recvfrom(2048)
                    except socket.timeout:
                        break
                    stats.reply_packets += 1
                    if who != peer:
                        stats.ignored_packets += 1
                        continue
                    if reply.startswith(b"\x00\x05"):
                        raise RuntimeError("board rejected image: " + repr(reply[4:]))
                    if reply == expected_ack:
                        acked = True
                        break
                    stats.ignored_packets += 1
            finally:
                stats.ack_wait_seconds += clock() - started
            if acked:
                break
            stats.timeouts += 1
        if not acked:
            raise TimeoutError(f"no board ACK for block {wire_block}, completed={total}")
        total += len(data)
        stats.bytes_acked = total
        stats.acked_blocks += 1
        stats.eof_acked = len(data) < 512
        if progress is not None:
            progress(total, stats.eof_acked)
        if stats.eof_acked:
            return total
        block += 1

def serve(image, bind, port=69, board="192.168.137.30", once=False, show_progress=True, limit=LIMIT):
    image = Path(image).resolve()
    size = validate(image, limit)
    ipaddress.IPv4Address(bind)
    ipaddress.IPv4Address(board)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
        listener.bind((bind, port))
        print(f"TFTP LISTEN {bind}:{port} file={image.name} board={board} payload={size}", flush=True)
        print("Reset board to request the file, or send n via UART. UART d remains recovery.", flush=True)
        while True:
            packet, peer = listener.recvfrom(2048)
            if peer[0] != board:
                continue
            name = request(packet)
            if name != image.name:
                listener.sendto(b"\x00\x05\x00\x01file unavailable\x00", peer)
                continue
            started = time.monotonic()
            display = TransferProgress(image.stat().st_size) if show_progress else None
            stats = TransferStats()
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as session, image.open("rb") as source:
                    session.bind((bind, 0))
                    sent = transfer(session, peer, source, progress=display.update if display else None,
                                    stats=stats)
                elapsed = max(time.monotonic() - started, 1e-9)
                print(f"TFTP SENT {sent} bytes to {peer} in {elapsed:.2f}s ({sent / elapsed / 1048576:.3f} MiB/s); "
                      "final EOF ACK received; RAM verification and RUN/boot are not confirmed. "
                      "Check board UART status.", flush=True)
                print(stats.summary(), flush=True)
                if once:
                    return
            except (TimeoutError, RuntimeError, OSError) as error:
                if display:
                    display.close()
                print(f"TFTP FAILED {peer}: {error}; waiting for a new RRQ", flush=True)
                print(stats.summary(), flush=True)
            finally:
                if display:
                    display.close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("pack")
    p.add_argument("image", type=Path)
    p.add_argument("--out", type=Path, default=Path("valence.vld"))
    p.add_argument("--entry", type=lambda s: int(s, 0), default=BASE)
    p.add_argument("--memory", choices=LIMITS, default="ddr")
    p = sub.add_parser("serve")
    p.add_argument("image", type=Path)
    p.add_argument("--bind", default="192.168.137.1")
    p.add_argument("--board", default="192.168.137.30")
    p.add_argument("--port", type=int, default=69)
    p.add_argument("--once", action="store_true")
    p.add_argument("--no-progress", action="store_true", help="disable ACKed-byte progress display")
    p.add_argument("--memory", choices=LIMITS, default="ddr")
    args = parser.parse_args()
    if args.action == "pack":
        pack(args.image, args.out, args.entry, LIMITS[args.memory])
    else:
        serve(args.image, args.bind, args.port, args.board, args.once, not args.no_progress, LIMITS[args.memory])

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nTFTP stopped")
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))
