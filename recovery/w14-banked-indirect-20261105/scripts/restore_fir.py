#!/usr/bin/env python3
"""Verify the complete FIR stream, or extract it to a new directory only."""
from pathlib import Path
import argparse
import hashlib
import json
import lzma

parser = argparse.ArgumentParser(description=__doc__)
mode = parser.add_mutually_exclusive_group(required=True)
mode.add_argument('--check', action='store_true')
mode.add_argument('--output-dir', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
meta = json.loads((root / 'FIR_SOURCE.json').read_text())
source = root / meta['compressed_path']
if meta['compression'] != 'xz' or source.stat().st_size != meta['compressed_bytes']:
    raise SystemExit('Compressed metadata mismatch')
with source.open('rb') as handle:
    compressed_hash = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b''):
        compressed_hash.update(chunk)
    digest = compressed_hash.hexdigest()
if digest != meta['compressed_sha256']:
    raise SystemExit('Compressed source hash mismatch')
output = None
if args.output_dir:
    args.output_dir.mkdir(parents=True, exist_ok=False)
    partial = args.output_dir / (meta['decompressed_filename'] + '.partial')
    output = partial.open('xb')
try:
    digest, size = hashlib.sha256(), 0
    with lzma.open(source, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
            size += len(chunk)
            if output:
                output.write(chunk)
finally:
    if output:
        output.close()
if size != meta['decompressed_bytes'] or digest.hexdigest() != meta['decompressed_sha256']:
    raise SystemExit('Decompressed source mismatch; any partial output was not finalized')
if output:
    partial.rename(args.output_dir / meta['decompressed_filename'])
print(json.dumps({'status': 'PASS', 'bytes': size, 'sha256': digest.hexdigest(), 'extracted': bool(output)}))
