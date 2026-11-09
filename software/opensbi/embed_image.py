#!/usr/bin/env python3
"""Wrap a flat OpenSBI image for the existing RPU loader (not its selftest mode)."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zlib

root = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('image', type=Path)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
out = a.output.resolve()
assert out.is_relative_to(root / 'build')
out.mkdir(parents=True, exist_ok=False)
data = a.image.read_bytes()
assert 0 < len(data) < 0x03c00000  # Fit the image and RPU program in its 64 MiB region.
with (out / 'i1_embedded_rv_image.h').open('w') as stream:
    stream.write('/* Generated image; use the RPU --load-only mode. */\n')
    stream.write('static const unsigned char i1_rv_image[%d] __attribute__((aligned(8))) = {\n' % len(data))
    # Sparse C initializers preserve the exact flat image without megabytes of textual zeros.
    for offset in range(0, len(data), 16):
        chunk = data[offset:offset + 16]
        if any(chunk):
            stream.write('    [%d] = ' % offset + ','.join('0x%02x' % value for value in chunk) + ',\n')
    stream.write('};\n#define I1_RV_IMAGE_BYTES %du\n' % len(data))
shutil.copyfile(a.image, out / 'rv-firmware.bin')
(out / 'receipt.json').write_text(json.dumps(dict(status='PACKED_NOT_BOOT_QUALIFIED',
    bytes=len(data), crc32=zlib.crc32(data), sha256=hashlib.sha256(data).hexdigest(),
    entry='0x80000000', ps_load='0x40000000', rpu_mode='--load-only'), indent=2) + '\n')
print('RPU_IMAGE_READY', out, flush=True)
