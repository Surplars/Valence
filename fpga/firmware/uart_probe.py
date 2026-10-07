#!/usr/bin/env python3
"""Diagnose BootROM header reception without sending or executing a payload.

The d command invalidates any previously verified RAM image. No bitstream,
flash or payload memory is written by this tool. BootROM still uses its DDR
stack/buffers while processing the probe headers.
"""
import argparse
from pathlib import Path
import struct
import time
import zlib


def make_header(length, image_crc=0, magic=b"VLD1"):
    body = struct.pack("<4s7I", magic, 1, 0x80200000, 0x80200000,
                       length, image_crc, 256, 0)
    return body + struct.pack("<I", zlib.crc32(body))


def probe_cases(image):
    zero = make_header(0)
    bad_crc = zero[:-4] + struct.pack("<I", struct.unpack("<I", zero[-4:])[0] ^ 1)
    return (
        ("bad magic / valid CRC", make_header(0, magic=b"BAD!"), 1),
        ("valid header / zero length", zero, 2),
        ("bad CRC / zero length", bad_crc, 1),
        ("actual image header / NO payload", make_header(len(image), zlib.crc32(image)), 0),
    )


def show(label, data):
    print(f"{label} hex: {data.hex(' ')}", flush=True)
    print(f"{label} raw: {data!r}", flush=True)


def capture_until(port, marker, timeout):
    received = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        received += port.read(1)
        if received.endswith(marker):
            return bytes(received)
        if len(received) > 4096:
            show("RX excessive/noisy", received)
            raise RuntimeError("More than 4096 bytes without expected marker")
    show("RX timeout", received)
    raise TimeoutError(f"Did not receive {marker!r}")


def send_paced(port, data, interval):
    show("TX", data)
    for value in data:
        if port.write(bytes([value])) != 1:
            raise TimeoutError("Serial write made no progress")
        port.flush()
        time.sleep(interval)


def decode_acks(data):
    replies = []
    start = 0
    while True:
        index = data.find(b"VACK", start)
        if index < 0 or index + 12 > len(data):
            return replies
        sequence, status = struct.unpack_from("<II", data, index + 4)
        replies.append((sequence, status))
        start = index + 12


def self_test():
    cases = probe_cases(bytes(6040))
    for index, (_, header, expected) in enumerate(cases):
        assert len(header) == 36
        magic, version, base, entry, length, _, chunk, reserved, crc = struct.unpack("<4s8I", header)
        valid = magic == b"VLD1" and version == 1 and chunk == 256 and reserved == 0
        valid = valid and crc == zlib.crc32(header[:32])
        actual = 1 if not valid else 2 if not length else 0
        assert actual == expected, index
        assert base == entry == 0x80200000
    raw = b"noise" + struct.pack("<4sII", b"VACK", 0xffffffff, 0)
    raw += struct.pack("<4sII", b"VACK", 0, 5) + b"\r\nDOWNLOAD ABORT\r\n"
    assert decode_acks(raw) == [(0xffffffff, 0), (0, 5)]
    print("Offline probe self-test: PASS (no serial port opened)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?")
    parser.add_argument("image", nargs="?", type=Path)
    parser.add_argument("--baud", type=int, default=1500000)
    parser.add_argument("--byte-delay-ms", type=float, default=2.0)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.port or not args.image:
        parser.error("provide PORT IMAGE.bin")
    if not 0 <= args.byte_delay_ms <= 100:
        parser.error("byte delay must be 0..100 ms")
    try:
        image = args.image.read_bytes()
        if not image or image.startswith(b"\x7fELF") or len(image) > 0x1fffc000:
            raise ValueError("Expected a nonempty flat binary within the DDR loader limit")
        import serial
        with serial.Serial(args.port, args.baud, timeout=0.05, write_timeout=5,
                           bytesize=8, parity="N", stopbits=1,
                           xonxoff=False, rtscts=False, dsrdtr=False) as port:
            print("Port open. PRESS THE BOARD RESET BUTTON NOW (within 30 seconds).", flush=True)
            print("Header probes only; no payload or RUN will be sent. Previous verified image is invalidated.", flush=True)
            start = capture_until(port, b"download mode (UART)\r\n", 30)
            show("RX reset", start)
            if b"Valence Bootrom V0.1\r\n" not in start:
                raise RuntimeError("Fresh reset banner not captured; reset is required before probing")
            matched = 0
            for label, header, expected in probe_cases(image):
                print(f"\nCASE: {label}; expected header status={expected}", flush=True)
                time.sleep(1)
                send_paced(port, b"d", args.byte_delay_ms / 1000)
                show("RX handshake", capture_until(port, b"VLOAD1\r\n", 5))
                send_paced(port, header, args.byte_delay_ms / 1000)
                # A correctly accepted image header will time out waiting for its
                # first DATA frame; no DATA frame is ever sent by this tool.
                response = capture_until(port, b"download mode (UART)\r\n", 8)
                show("RX reply", response)
                replies = decode_acks(response)
                for sequence, status in replies:
                    print(f"ACK sequence=0x{sequence:08x} status={status}", flush=True)
                wanted = [(0xffffffff, expected)]
                if expected == 0:
                    wanted.append((0, 5))
                good = replies == wanted
                matched += good
                print("CASE MATCH" if good else f"CASE MISMATCH wanted={wanted!r}", flush=True)
            print(f"\nProtocol probe summary: {matched}/4 matched. No program downloaded or executed.")
    except (OSError, RuntimeError, ValueError, TimeoutError) as error:
        parser.exit(1, f"Probe stopped: {error}\n")
    except ImportError:
        parser.exit(1, "Install pyserial: python -m pip install pyserial\n")
    except KeyboardInterrupt:
        print("\nProbe interrupted; reset board before retrying.")


if __name__ == "__main__":
    main()
