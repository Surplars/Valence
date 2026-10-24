#!/usr/bin/env python3
"""Apply an exact reviewed prefix to one matching VLD, never overwrite inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_vld(data):
    if len(data) < 36:
        raise ValueError('short VLD')
    magic, version, base, entry, size, crc, chunk, flags, check = struct.unpack('<9I', data[:36])
    if magic != 0x31444c56 or version != 1 or base != 0x80200000 or entry != base or chunk != 256 or flags:
        raise ValueError('unexpected VLD contract')
    if size != len(data)-36 or zlib.crc32(data[:32]) != check or zlib.crc32(data[36:]) != crc:
        raise ValueError('VLD size/CRC mismatch')


def apply(original, prefix, manifest, output):
    original, prefix, manifest, output = map(Path, (original, prefix, manifest, output))
    if output.exists() or output.resolve() in (original.resolve(), prefix.resolve(), manifest.resolve()):
        raise ValueError('Output must be a new filename; original is preserved')
    record = json.loads(manifest.read_text())
    old, head = original.read_bytes(), prefix.read_bytes()
    validate_vld(old)
    if digest(old) != record['original_vld_sha256'] or len(old) != record['original_vld_bytes']:
        raise ValueError('Wrong firmware: this patch accepts only exact I1 boot-pair/O2 r1')
    if digest(head) != record['new_prefix_sha256'] or len(head) != record['prefix_bytes']:
        raise ValueError('Prefix integrity mismatch')
    body = old[record['prefix_bytes']:]
    if digest(body) != record['unchanged_body_sha256']:
        raise ValueError('Unchanged kernel/rootfs body mismatch')
    new = head + body
    validate_vld(new)
    if digest(new) != record['new_vld_sha256'] or len(new) != record['new_vld_bytes']:
        raise ValueError('Reassembled firmware identity mismatch')
    with output.open('xb') as stream:
        stream.write(new)
    print('VERIFIED_NEW_VLD', str(output), len(new), digest(new))
    print('Original preserved. This does not program a board or claim a successful boot.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', required=True)
    parser.add_argument('--prefix', default='i1-sbi-console-fixed.prefix')
    parser.add_argument('--manifest', default='prefix-patch.json')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    apply(args.original, args.prefix, args.manifest, args.output)
