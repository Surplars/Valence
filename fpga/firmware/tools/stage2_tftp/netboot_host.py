#!/usr/bin/env python3
"""Explicitly started static-IP TFTP server + Valence checked-image packer.

No firewall/network configuration or board reset is performed by this tool.
Serve the packed image on a trusted, directly connected Ethernet segment only.
"""
import argparse
from dataclasses import dataclass
import ipaddress
import math
from pathlib import Path
import socket
import struct
import sys
import time
import zlib

BASE = 0x80200000
LIMIT = 512 * 1024 * 1024 - 0x4000
LIMITS = {"ddr": LIMIT, "ddr1g": 0x40000000 - 0x4000, "ddr2g": 0xffff8000 - BASE}
# Explicit menu ROM profiles reserve512KiB boot-only diagnostic scratch.
LIMITS.update({name+"-menu": value-0x80000 for name,value in tuple(LIMITS.items()) if name.startswith("ddr")})
MAGIC = 0x31444C56
MAX_BLKSIZE = 1024
MAX_WINDOWSIZE = 16
DEFAULT_WINDOWSIZE = 4
DEFAULT_PACKET_DELAY_US = 100


def high_resolution_time():
    """Monotonic high-resolution seconds, including on older Windows Python.

    Use the performance counter rather than a potentially coarse monotonic
    tick. An injected test clock still takes/returns seconds everywhere.
    This changes measurement precision, not the OS sleep scheduler.
    """
    return time.perf_counter_ns() / 1_000_000_000

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

@dataclass(frozen=True)
class TftpRequest:
    name: str
    blksize: int = 512
    windowsize: int = 1
    options: tuple = ()

    @property
    def oack(self):
        if not self.options:
            return None
        return b"\x00\x06" + b"".join(
            key.encode("ascii") + b"\x00" + str(value).encode("ascii") + b"\x00"
            for key, value in self.options)


def parse_request(packet, max_blksize=MAX_BLKSIZE, max_windowsize=DEFAULT_WINDOWSIZE):
    """Parse a bounded RRQ and negotiate only supported RFC 2347/7440 options.

    Caps never increase the client's request. Unknown options are ignored, as
    RFC 2347 requires; malformed/duplicate options reject the whole request.
    Only 512/1024-byte blocks are supported by this board-specific server.
    """
    if max_blksize not in (512, 1024) or not 1 <= max_windowsize <= MAX_WINDOWSIZE:
        raise ValueError("invalid TFTP negotiation limits")
    if len(packet) > 512 or not packet.startswith(b"\x00\x01"):
        return None
    fields = packet[2:].split(b"\x00")
    if len(fields) < 3 or len(fields) % 2 != 1 or fields[-1] or fields[1].lower() != b"octet":
        return None
    try:
        name = fields[0].decode("ascii")
    except UnicodeDecodeError:
        return None
    if not name or len(name) > 127 or any(c not in
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in name):
        return None
    options, seen = [], set()
    blksize, windowsize = 512, 1
    for index in range(2, len(fields) - 1, 2):
        key, value = fields[index].lower(), fields[index + 1]
        if not key or not value or key in seen or any(c < 33 or c > 126 for c in key + value):
            return None
        seen.add(key)
        if key not in (b"blksize", b"windowsize"):
            continue
        if len(value) > 5 or not value.isdigit():
            return None
        number = int(value)
        if key == b"blksize":
            if not 512 <= number <= 65464:
                return None
            blksize = min(max_blksize, 1024 if number >= 1024 else 512)
            options.append(("blksize", blksize))
        else:
            if not 1 <= number <= 65535:
                return None
            windowsize = min(max_windowsize, number)
            options.append(("windowsize", windowsize))
    return TftpRequest(name, blksize, windowsize, tuple(options))


def request(packet):
    """Compatibility helper returning the filename of a valid RRQ."""
    parsed = parse_request(packet)
    return parsed.name if parsed else None

class TransferProgress:
    """Throttled ACKed-byte progress; 100% includes the final EOF ACK."""
    def __init__(self, size, stream=None, clock=None, interval=0.25):
        self.size = size
        self.stream = sys.stdout if stream is None else stream
        self.clock = high_resolution_time if clock is None else clock
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
    pacing_seconds: float = 0.0
    ack_wait_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    eof_acked: bool = False
    blksize: int = 512
    windowsize: int = 1
    oack_packets: int = 0
    oack_retransmits: int = 0
    windows_sent: int = 0
    window_restarts: int = 0
    max_buffered_blocks: int = 0
    max_buffered_bytes: int = 0

    def summary(self):
        other = max(0.0, self.elapsed_seconds - self.read_seconds -
                    self.send_seconds - self.pacing_seconds - self.ack_wait_seconds)
        return (f"TFTP STATS bytes_acked={self.bytes_acked} data_packets={self.data_packets} "
                f"acked_blocks={self.acked_blocks} retransmits={self.retransmits} "
                f"timeouts={self.timeouts} rx_packets={self.reply_packets} "
                f"ignored_packets={self.ignored_packets} read={self.read_seconds:.6f}s "
                f"send={self.send_seconds:.6f}s ack_wait={self.ack_wait_seconds:.6f}s "
                f"other={other:.6f}s elapsed={self.elapsed_seconds:.6f}s "
                f"eof_acked={'yes' if self.eof_acked else 'no'} "
                f"blksize={self.blksize} windowsize={self.windowsize} "
                f"oack_packets={self.oack_packets} oack_retransmits={self.oack_retransmits} "
                f"windows_sent={self.windows_sent} window_restarts={self.window_restarts} "
                f"max_buffered_blocks={self.max_buffered_blocks} "
                f"max_buffered_bytes={self.max_buffered_bytes} pacing={self.pacing_seconds:.6f}s")


def transfer(sock, peer, source, retry_seconds=1, retries=10, progress=None, stats=None, clock=None,
             *, blksize=512, windowsize=1, oack=None,
             inter_packet_seconds=DEFAULT_PACKET_DELAY_US / 1_000_000, sleeper=None):
    """Send bounded RFC 7440 windows, retaining at most one unACKed window.

    Defaults preserve legacy TFTP. Pass negotiated sizes and the request's OACK
    to perform the ACK0 handshake before reading/sending DATA. Counters and
    progress only credit cumulative ACKs; EOF needs its own short/zero DATA ACK.
    Retries bound each DATA packet's total sends, including gap recovery.
    Within-window DATA spacing defaults to 100 us. Explicit zero disables
    pacing; no busy wait or timer-resolution change is used. No extra delay
    is imposed before the first DATA of a new/retried window or after its last
    DATA. Sleeper and clock can be injected together for deterministic tests.
    """
    if blksize not in (512, 1024) or not 1 <= windowsize <= MAX_WINDOWSIZE:
        raise ValueError("invalid TFTP transfer sizes")
    if not math.isfinite(retry_seconds) or retry_seconds <= 0 or retries < 1:
        raise ValueError("TFTP timeout and retry count must be positive")
    if not math.isfinite(inter_packet_seconds) or inter_packet_seconds < 0:
        raise ValueError("TFTP inter-packet delay must be finite and nonnegative")
    sleeper = time.sleep if sleeper is None else sleeper
    stats = TransferStats() if stats is None else stats
    stats.blksize, stats.windowsize = blksize, windowsize
    clock = high_resolution_time if clock is None else clock
    started = clock()
    try:
        if oack is not None:
            _negotiate(sock, peer, oack, retry_seconds, retries, stats, clock)
        return _transfer(sock, peer, source, retry_seconds, retries, progress, stats, clock,
                         blksize, windowsize, inter_packet_seconds, sleeper)
    finally:
        stats.elapsed_seconds = max(0.0, clock() - started)


def _send(sock, peer, packet, stats, clock):
    started = clock()
    try:
        sock.sendto(packet, peer)
    finally:
        stats.send_seconds += clock() - started


def _receive_ack(sock, peer, deadline, stats, clock):
    """Ignore foreign, malformed and non-ACK traffic without extending timeout."""
    while clock() < deadline:
        sock.settimeout(max(0.001, deadline - clock()))
        try:
            reply, who = sock.recvfrom(2048)
        except socket.timeout:
            return None
        stats.reply_packets += 1
        if who != peer:
            stats.ignored_packets += 1
            continue
        if len(reply) >= 4 and reply.startswith(b"\x00\x05"):
            raise RuntimeError("board rejected image: " + repr(reply[4:]))
        if len(reply) == 4 and reply.startswith(b"\x00\x04"):
            return struct.unpack("!H", reply[2:])[0]
        stats.ignored_packets += 1
    return None


def _negotiate(sock, peer, oack, retry_seconds, retries, stats, clock):
    for attempt in range(retries):
        _send(sock, peer, oack, stats, clock)
        stats.oack_packets += 1
        stats.oack_retransmits += int(attempt != 0)
        started = clock()
        deadline = started + retry_seconds
        try:
            while (ack := _receive_ack(sock, peer, deadline, stats, clock)) is not None:
                if ack == 0:
                    return
                stats.ignored_packets += 1
        finally:
            stats.ack_wait_seconds += clock() - started
        stats.timeouts += 1
    raise TimeoutError("no board ACK0 for TFTP option negotiation")


def _transfer(sock, peer, source, retry_seconds, retries, progress, stats, clock, blksize, windowsize,
              inter_packet_seconds, sleeper):
    # Logical block numbers disambiguate current-window ACKs across 65535 -> 0.
    # A packet is retained byte-for-byte until its cumulative ACK, never reread.
    pending = []  # [logical block, encoded DATA, send count]
    next_block, acked_block, total = 1, 0, 0
    eof = False
    duplicate_restart_used = False
    paced = windowsize > 1 and inter_packet_seconds > 0
    while True:
        while len(pending) < windowsize and not eof:
            started = clock()
            try:
                data = source.read(blksize)
            finally:
                stats.read_seconds += clock() - started
            if len(data) > blksize:
                raise ValueError("source returned more than the requested TFTP block")
            pending.append([next_block, struct.pack("!HH", 3, next_block & 0xffff) + data, 0])
            next_block += 1
            eof = len(data) < blksize
        stats.max_buffered_blocks = max(stats.max_buffered_blocks, len(pending))
        stats.max_buffered_bytes = max(stats.max_buffered_bytes,
                                       sum(len(item[1]) for item in pending))
        if any(item[2] >= retries for item in pending):
            raise TimeoutError(f"no board ACK for block {pending[0][0] & 0xffff}, completed={total}")
        last_send = None  # ACK/timeout already separates successive windows.
        for item in pending:
            if paced and last_send is not None:
                pause = last_send + inter_packet_seconds - clock()
                if pause > 0:
                    started = clock()
                    try:
                        sleeper(pause)
                    finally:
                        stats.pacing_seconds += clock() - started
            _send(sock, peer, item[1], stats, clock)
            if paced:
                last_send = clock()
            stats.data_packets += 1
            stats.retransmits += int(item[2] != 0)
            item[2] += 1
        stats.windows_sent += 1
        started = clock()
        deadline = started + retry_seconds
        try:
            while True:
                ack = _receive_ack(sock, peer, deadline, stats, clock)
                if ack is None:
                    stats.timeouts += 1
                    break
                count = (ack - (acked_block & 0xffff)) & 0xffff
                if 1 <= count <= len(pending):
                    # A partial cumulative ACK signals a gap: discard only the
                    # acknowledged prefix, refill, then restart at ACK + 1.
                    total += sum(len(item[1]) - 4 for item in pending[:count])
                    acked_block += count
                    stats.bytes_acked = total
                    stats.acked_blocks += count
                    stats.eof_acked = eof and count == len(pending)
                    if progress is not None:
                        progress(total, stats.eof_acked)
                    if stats.eof_acked:
                        return total
                    if count < len(pending):
                        stats.window_restarts += 1
                    del pending[:count]
                    duplicate_restart_used = False
                    break
                if count == 0 and windowsize > 1 and not duplicate_restart_used:
                    # Lost first DATA can produce ACK of the window base.
                    # Allow one fast restart per base; duplicates thereafter
                    # cannot amplify traffic or keep the deadline alive.
                    duplicate_restart_used = True
                    stats.window_restarts += 1
                    break
                stats.ignored_packets += 1
        finally:
            stats.ack_wait_seconds += clock() - started

def serve(image, bind, port=69, board="192.168.137.30", once=False, show_progress=True, limit=LIMIT,
          max_blksize=MAX_BLKSIZE, max_windowsize=DEFAULT_WINDOWSIZE,
          packet_delay_us=DEFAULT_PACKET_DELAY_US):
    image = Path(image).resolve()
    if not math.isfinite(packet_delay_us) or packet_delay_us < 0:
        raise ValueError("TFTP packet delay must be finite and nonnegative")
    size = validate(image, limit)
    ipaddress.IPv4Address(bind)
    ipaddress.IPv4Address(board)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
        listener.bind((bind, port))
        print(f"TFTP LISTEN {bind}:{port} file={image.name} board={board} payload={size}", flush=True)
        print(f"TFTP OPTIONS max_blksize={max_blksize} max_windowsize={max_windowsize} "
              f"packet_delay_us={packet_delay_us:g}; "
              "legacy RRQ uses blksize=512 windowsize=1", flush=True)
        print("Reset board to request the file, or send n via UART. UART d remains recovery.", flush=True)
        while True:
            packet, peer = listener.recvfrom(2048)
            if peer[0] != board:
                continue
            requested = parse_request(packet, max_blksize, max_windowsize)
            if requested is None or requested.name != image.name:
                listener.sendto(b"\x00\x05\x00\x01file unavailable\x00", peer)
                continue
            started = high_resolution_time()
            display = TransferProgress(image.stat().st_size) if show_progress else None
            stats = TransferStats()
            print(f"TFTP NEGOTIATED {peer} blksize={requested.blksize} "
                  f"windowsize={requested.windowsize} oack={'yes' if requested.oack else 'no'}", flush=True)
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as session, image.open("rb") as source:
                    session.bind((bind, 0))
                    sent = transfer(session, peer, source, progress=display.update if display else None,
                                    stats=stats, blksize=requested.blksize,
                                    windowsize=requested.windowsize, oack=requested.oack,
                                    inter_packet_seconds=packet_delay_us / 1_000_000)
                elapsed = max(high_resolution_time() - started, 1e-9)
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
    p.add_argument("--max-blksize", type=int, choices=(512, 1024), default=MAX_BLKSIZE,
                   help="maximum negotiated DATA bytes (default: 1024); legacy uses 512")
    p.add_argument("--max-windowsize", type=int, choices=range(1, MAX_WINDOWSIZE + 1), default=DEFAULT_WINDOWSIZE,
                   help="maximum negotiated DATA blocks per window (default: 4); legacy uses 1")
    p.add_argument("--packet-delay-us", type=float, default=DEFAULT_PACKET_DELAY_US,
                   help="within-window DATA spacing (default: 100 us); explicit 0 disables pacing")
    p.add_argument("--memory", choices=LIMITS, default="ddr")
    args = parser.parse_args()
    if args.action == "pack":
        pack(args.image, args.out, args.entry, LIMITS[args.memory])
    else:
        serve(args.image, args.bind, args.port, args.board, args.once, not args.no_progress,
              LIMITS[args.memory], args.max_blksize, args.max_windowsize, args.packet_delay_us)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nTFTP stopped")
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))
