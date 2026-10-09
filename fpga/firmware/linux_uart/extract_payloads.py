#!/usr/bin/env python3
"""Extract checked BIN or raw Linux Image from this delivery's single VLD payload."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib


def checked_payload(directory):
    manifest = json.loads((directory / 'manifest.json').read_text())
    wrapped = (directory / 'valence.vld').read_bytes()
    expected = manifest['files']['valence.vld']
    if len(wrapped) != expected['bytes'] or hashlib.sha256(wrapped).hexdigest() != expected['sha256']:
        raise RuntimeError('VLD length/SHA-256 mismatch')
    if len(wrapped) < 36:
        raise RuntimeError('Truncated VLD header')
    magic, version, base, entry, length, crc, chunk, flags, hcrc = struct.unpack('<9I', wrapped[:36])
    payload = wrapped[36:]
    if ((magic, version, base, entry, chunk, flags) != (0x31444c56, 1, 0x80200000, 0x80200000, 256, 0)
            or length != len(payload) or length > 0xfff78000 - base
            or zlib.crc32(wrapped[:32]) != hcrc or zlib.crc32(payload) != crc):
        raise RuntimeError('Invalid VLD header, CRC or 2 GiB menu memory range')
    return manifest, payload


def extract(directory, kinds):
    manifest, payload = checked_payload(directory)
    outputs = []
    for kind in kinds:
        if kind == 'bin':
            names = [name for name in manifest['files'] if name.startswith('opensbi_') and name.endswith('.bin')]
            if len(names) != 1:
                raise RuntimeError('Ambiguous OpenSBI BIN manifest entry')
            name, data = names[0], payload
        else:
            name = 'Image'
            length = manifest['files'][name]['bytes']
            # Existing combined image has OpenSBI at 0x80200000, Linux at 0x80400000.
            data = payload[0x200000:0x200000 + length]
        expected = manifest['files'][name]
        if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise RuntimeError('Extracted payload mismatch: ' + name)
        destination = directory / name
        if destination.exists() or destination.is_symlink():
            raise RuntimeError('Refusing to replace existing output: ' + name)
        outputs.append((destination, data))
    # Validate every requested payload and destination before writing any of them.
    for destination, data in outputs:
        with destination.open('xb') as stream:
            stream.write(data)
        print('VERIFIED', destination.name, len(data), hashlib.sha256(data).hexdigest())
    return [destination for destination, _ in outputs]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin', action='store_true', help='raw combined OpenSBI BIN for uart_load.py')
    parser.add_argument('--image', action='store_true', help='raw Linux Image with embedded initramfs for U-Boot')
    args = parser.parse_args()
    if not args.bin and not args.image:
        parser.error('choose --bin, --image, or both; direct BootROM TFTP uses valence.vld unchanged')
    extract(Path(__file__).resolve().parent, [name for name in ('bin', 'image') if getattr(args, name)])
