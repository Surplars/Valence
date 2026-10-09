#!/usr/bin/env python3
"""Upload a flat RV64 RAM binary to automatic-start or legacy Valence BootROM (Windows or Linux)."""
import argparse
from dataclasses import dataclass
import os
import struct
import sys
import time
from pathlib import Path
from typing import Optional
import zlib

RAM_BASE = 0x80200000
IMAGE_LIMIT = 0xFC000  # Backward-compatible 1 MiB URAM profile.
DDR_IMAGE_LIMIT = 0x20000000 - 0x4000
IMAGE_LIMITS = {"uram": IMAGE_LIMIT, "ddr": DDR_IMAGE_LIMIT,
                "ddr1g": 0x40000000 - 0x4000, "ddr2g": 0xffff8000 - RAM_BASE}
# Explicit menu ROM profiles reserve512KiB boot-only diagnostic scratch.
IMAGE_LIMITS.update({name+"-menu": value-0x80000 for name,value in tuple(IMAGE_LIMITS.items()) if name.startswith("ddr")})
CHUNK_SIZE = 256
HEADER_SEQ = 0xFFFFFFFF
ACK = struct.Struct("<4sII")
STATUS = {1: "invalid header", 2: "invalid address/length", 3: "CRC mismatch",
          4: "unexpected chunk sequence", 5: "receive timeout or UART error"}
WINDOWS_KEYS = {"H": b"\x1b[A", "P": b"\x1b[B", "K": b"\x1b[D",
                "M": b"\x1b[C", "G": b"\x1b[H", "O": b"\x1b[F",
                "S": b"\x1b[3~"}


class ProtocolError(RuntimeError):
    pass


class ChunkCrcError(TimeoutError):
    pass


def validate_image(image, entry, image_limit=IMAGE_LIMIT):
    if image.startswith(b"\x7fELF"):
        raise ValueError("send a flat .bin, not ELF; use objcopy -O binary")
    if image_limit not in IMAGE_LIMITS.values():
        raise ValueError("unsupported memory profile limit")
    if not image or len(image) > image_limit:
        raise ValueError(f"image length must be 1..{image_limit} bytes for this memory profile")
    if entry & 3 or not RAM_BASE <= entry < RAM_BASE + len(image):
        raise ValueError("entry must be 4-byte aligned and inside the loaded image")


def image_header(image, entry=RAM_BASE, image_limit=IMAGE_LIMIT):
    validate_image(image, entry, image_limit)
    body = struct.pack("<4s7I", b"VLD1", 1, RAM_BASE, entry, len(image),
                       zlib.crc32(image), CHUNK_SIZE, 0)
    return body + struct.pack("<I", zlib.crc32(body))


def chunk_frame(sequence, payload):
    if not 1 <= len(payload) <= CHUNK_SIZE:
        raise ValueError("chunk length must be 1..256")
    return struct.pack("<4sIII", b"DATA", sequence, len(payload),
                       zlib.crc32(payload)) + payload


def send(port, data):
    offset = 0
    while offset < len(data):
        count = port.write(data[offset:])
        if not count:
            raise TimeoutError("serial write stalled")
        offset += count
    port.flush()


def wait_marker(port, marker, timeout):
    markers = (marker,) if isinstance(marker, bytes) else tuple(marker)
    width = max(map(len, markers))
    deadline, window = time.monotonic() + timeout, bytearray()
    while time.monotonic() < deadline:
        incoming = port.read(1)
        if incoming:
            window += incoming
            if any(window.endswith(item) for item in markers):
                return
            if len(window) > width:
                del window[:-width]
    raise TimeoutError(f"monitor did not send {marker!r}; reset board and close other terminals")


def wait_ready(port, timeout=5.0, output=None):
    """Return 'autoboot' or 'legacy' after VDON, without consuming guest output.

    AUTOBOOT announces the ROM's launch path, not evidence of guest execution.
    Read a byte at a time so bytes following the marker stay in the UART input
    buffer for console(). Forward consumed text immediately when a sink is given,
    including diagnostics on failure or timeout. Memory use stays bounded even
    if a damaged stream never contains a newline.
    """
    if not 0 < timeout < float("inf"):
        raise ValueError("boot status timeout must be finite and positive")
    deadline, line = time.monotonic() + timeout, bytearray()
    while time.monotonic() < deadline:
        incoming = port.read(1)
        if not incoming:
            continue
        if output is not None:
            output.write(incoming)
            output.flush()
        line += incoming
        if line == b"AUTOBOOT\r\n":
            return "autoboot"
        if line == b"ready to boot\r\n" or line.endswith(b"> "):
            return "legacy"
        if incoming == b"\n":
            if any(marker in line for marker in (b"CRC FAIL", b"RESET REQUIRED", b"NO IMAGE",
                                                b"NO TRUSTED IMAGE", b"IMAGE RECORD FAIL",
                                                b"VERIFY CANCELLED", b"DOWNLOAD ABORT")):
                raise ProtocolError("ROM refused to start after VDON: " +
                                    line.decode("utf-8", errors="replace").strip())
            line.clear()
        elif len(line) > 256:
            del line[:-256]
    raise TimeoutError("RAM verified, but no AUTOBOOT or legacy readiness status received; "
                       "no RUN command sent and guest execution is unconfirmed")


def finish_download(port, run=False, timeout=5.0, output=None):
    """Send g only when requested AND explicitly recognized as a legacy ROM."""
    state = wait_ready(port, timeout=timeout, output=output)
    if state == "legacy" and run:
        send(port, b"g")
    return state


def read_exact(port, size, deadline):
    result = bytearray()
    while len(result) < size and time.monotonic() < deadline:
        result += port.read(size - len(result))
    if len(result) != size:
        raise TimeoutError("incomplete monitor reply")
    return bytes(result)


def read_reply(port, timeout):
    deadline, window = time.monotonic() + timeout, bytearray()
    while time.monotonic() < deadline:
        incoming = port.read(1)
        if not incoming:
            continue
        window += incoming
        if len(window) > 4:
            del window[:-4]
        if window in (b"VACK", b"VDON"):
            tail = read_exact(port, 8, deadline)
            return ACK.unpack(bytes(window) + tail)
    raise TimeoutError("monitor reply timed out")


def verification_timeout(image_size):
    # Conservative 16 KiB/s RAM CRC budget; override for a measured target.
    return max(30.0, image_size / 16384.0)


@dataclass
class UploadStats:
    """VACK bounds upload; VDON proves RAM length/CRC, not a successful RUN."""
    payload_bytes: int = 0
    chunk_frames: int = 0
    retransmits: int = 0
    final_frame_seconds: Optional[float] = None
    upload_seconds: Optional[float] = None
    verify_seconds: Optional[float] = None
    elapsed_seconds: float = 0.0
    ram_verified: bool = False

    def summary(self):
        if not self.ram_verified:
            timing = f"total={self.elapsed_seconds:.2f}s"
            if self.upload_seconds is not None:
                timing = (f"upload={self.upload_seconds:.2f}s "
                          f"final_verification_wait={max(0.0, self.elapsed_seconds - self.upload_seconds):.2f}s "
                          + timing)
            return f"RAM verification not confirmed: {timing}. RUN/boot not confirmed."
        if self.upload_seconds is not None:
            timing = (f"upload={self.upload_seconds:.2f}s "
                      f"final_verification_wait={self.verify_seconds:.2f}s "
                      f"total={self.elapsed_seconds:.2f}s")
        else:
            # VDON remains valid if the final VACK was lost. Do not pretend the
            # send timestamp is the board's upload/verification boundary.
            timing = (f"total={self.elapsed_seconds:.2f}s; upload/final-verification split unavailable "
                      f"(final ACK not observed; final frame sent at {self.final_frame_seconds:.2f}s)")
        return (f"RAM VERIFIED: {timing}; payload={self.payload_bytes} "
                f"chunk_frames={self.chunk_frames} retransmits={self.retransmits}. "
                "Downloaded RAM length/CRC verified; RUN/boot not confirmed.")


def upload(port, image, entry=RAM_BASE, timeout=1.0, retries=2, progress=None,
           image_limit=IMAGE_LIMIT, verify_timeout=None, stats=None):
    """Acknowledge each <=256-byte block and return host-observed RAM-check timings.

    Upload time includes the download handshake and ends at the final VACK;
    final verification wait ends at VDON. If VACK was lost, only total is known.
    Pass a fresh UploadStats to retain observations if the operation fails.
    """
    stats = UploadStats() if stats is None else stats
    started = time.monotonic()
    try:
        return _upload(port, image, entry, timeout, retries, progress, image_limit,
                       verify_timeout, stats, started)
    finally:
        stats.elapsed_seconds = max(0.0, time.monotonic() - started)


def _upload(port, image, entry, timeout, retries, progress, image_limit, verify_timeout, stats, started):
    header = image_header(image, entry, image_limit)
    stats.payload_bytes = len(image)
    verify_timeout = verification_timeout(len(image)) if verify_timeout is None else verify_timeout
    if not 0 < verify_timeout < float("inf"):
        raise ValueError("verification timeout must be finite and positive")
    port.reset_input_buffer()
    send(port, b"d")
    wait_marker(port, b"VLOAD1\r\n", 5.0)
    send(port, header)
    magic, sequence, status = read_reply(port, timeout)
    if (magic, sequence, status) != (b"VACK", HEADER_SEQ, 0):
        raise ProtocolError("header rejected: " + STATUS.get(status, str(status)))
    crc = zlib.crc32(image)
    for sequence, offset in enumerate(range(0, len(image), CHUNK_SIZE)):
        block = image[offset:offset + CHUNK_SIZE]
        frame = chunk_frame(sequence, block)
        final = offset + len(block) == len(image)
        for attempt in range(retries + 1):
            send(port, frame)
            stats.chunk_frames += 1
            stats.retransmits += int(attempt != 0)
            if final:
                stats.final_frame_seconds = time.monotonic() - started
            try:
                while True:
                    # Full RAM CRC verification happens after the final ACK.
                    magic, number, status = read_reply(port, verify_timeout if final else timeout)
                    if magic == b"VDON":
                        if not final or (number, status) != (len(image), crc):
                            raise ProtocolError("invalid final length/CRC reply")
                        stats.ram_verified = True
                        if stats.upload_seconds is not None:
                            stats.verify_seconds = time.monotonic() - started - stats.upload_seconds
                        if progress and stats.upload_seconds is None:
                            progress(len(image), len(image))
                        return stats
                    if number < sequence:
                        continue  # a delayed duplicate ACK
                    if number == sequence and status == 0:
                        if final:
                            if stats.upload_seconds is None:
                                stats.upload_seconds = time.monotonic() - started
                                if progress:
                                    progress(len(image), len(image))
                            continue
                        break
                    if number == sequence and status == 3:
                        raise ChunkCrcError("chunk CRC mismatch; retransmitting")
                    raise ProtocolError(
                        f"chunk {sequence} rejected: " + STATUS.get(status, str(status)))
                break
            except TimeoutError as error:
                # A final frame cannot be replayed once the monitor left download mode.
                # Explicit CRC NAKs are safe to retry, but silence at this stage requires
                # starting a new session (the final image may already be valid).
                if (final and not isinstance(error, ChunkCrcError)) or attempt == retries:
                    raise
        if progress:
            progress(offset + len(block), len(image))
    raise ProtocolError("missing final completion")


def poll_windows_keyboard(keys):
    """Read pending keys without local echo; translate navigation keys to ANSI."""
    typed = bytearray()
    while keys.kbhit():
        key = keys.getwch()
        if key in ("\x00", "\xe0"):
            typed += WINDOWS_KEYS.get(keys.getwch(), b"")
        elif key == "\x03":
            raise KeyboardInterrupt
        else:
            typed += key.encode("utf-8", errors="replace")
    return bytes(typed)


def console_step(port, typed=b"", output=None):
    if typed:
        send(port, typed)
    data = port.read(256)
    if data:
        sink = sys.stdout.buffer if output is None else output
        sink.write(data)
        sink.flush()


def console(port):
    """Forward terminal input to UART while displaying UART output."""
    if os.name == "nt" and sys.stdin.isatty():
        import msvcrt
        while True:
            console_step(port, poll_windows_keyboard(msvcrt))
    elif sys.stdin.isatty():
        import select
        import termios
        import tty

        fd = sys.stdin.fileno()
        original = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        try:
            reading_stdin = True
            while True:
                typed = b""
                if reading_stdin and select.select([fd], [], [], 0)[0]:
                    typed = os.read(fd, 256)
                    if not typed:
                        reading_stdin = False
                console_step(port, typed)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, original)
    else:
        # Preserve receive-only use when output is captured or stdin is redirected.
        while True:
            console_step(port)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="COM5 on Windows, /dev/ttyUSB0 on Linux")
    parser.add_argument("image", type=Path, help="flat .bin linked at 0x80200000")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--entry", type=lambda value: int(value, 0), default=RAM_BASE)
    parser.add_argument("--memory", choices=IMAGE_LIMITS, default="uram",
                        help="must match ROM firmware; ddr allows 512 MiB minus 16 KiB")
    parser.add_argument("--verify-timeout", type=float,
                        help="seconds for final RAM CRC (default scales with image size)")
    parser.add_argument("--boot-status-timeout", type=float,
                        help="seconds after VDON for boot status (default scales with image size)")
    parser.add_argument("--run", action="store_true",
                        help="send g only to legacy ROMs; new ROMs start automatically even without --run")
    parser.add_argument("--console", action="store_true",
                        help="interactive UART terminal until Ctrl-C (TTY keyboard required)")
    args = parser.parse_args()
    stats = None
    try:
        image = args.image.read_bytes()
        image_limit = IMAGE_LIMITS[args.memory]
        validate_image(image, args.entry, image_limit)
        boot_timeout = (verification_timeout(len(image)) if args.boot_status_timeout is None
                        else args.boot_status_timeout)
        if not 0 < boot_timeout < float("inf"):
            raise ValueError("boot status timeout must be finite and positive")
        import serial
        with serial.Serial(args.port, args.baud, timeout=0.05, write_timeout=5) as port:
            last_percent = [-1]
            stats = UploadStats()

            def progress(done, total):
                percent = done * 100 // total
                if percent != last_percent[0]:
                    print(f"\rUpload {done}/{total} bytes ({percent}%)", end="", flush=True)
                    last_percent[0] = percent
                    if done == total and stats.upload_seconds is not None:
                        print(f"\nUpload ACKed in {stats.upload_seconds:.2f}s; waiting for final RAM verification.",
                              flush=True)

            upload(port, image, args.entry, progress=progress, image_limit=image_limit,
                   verify_timeout=args.verify_timeout, stats=stats)
            print("\n" + stats.summary(), flush=True)
            state = finish_download(port, run=args.run, timeout=boot_timeout, output=sys.stdout.buffer)
            if state == "autoboot":
                print("ROM automatic start announced (with or without --run); "
                      "guest execution must be confirmed from board UART output.", flush=True)
            elif args.run:
                print("\nLegacy RUN command sent; successful RUN/boot must be confirmed from board UART output.",
                      flush=True)
            else:
                print("\nLegacy ROM is ready; image was not started (use --run to send g).", flush=True)
            if args.console:
                console(port)
    except ImportError:
        parser.exit(1, "Install pyserial: python -m pip install pyserial\n")
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        if stats is not None and not stats.ram_verified:
            print("\n" + stats.summary(), flush=True)
        parser.exit(1, f"{error}\nRetry after download mode returns; reset if the app hangs.\n")
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
