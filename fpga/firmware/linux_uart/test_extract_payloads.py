#!/usr/bin/env python3
"""Independent small VLD fixtures: exact extraction and fail-before-write behavior."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from extract_payloads import extract

BIN = 'opensbi_fixture.bin'


def fixture(root, corrupt_crc=False):
    image = b'fixture-Linux-Image' * 13
    payload = bytes(0x200000) + image + bytes(8)
    words = (0x31444c56, 1, 0x80200000, 0x80200000, len(payload), zlib.crc32(payload) ^ int(corrupt_crc), 256, 0)
    header = struct.pack('<8I', *words)
    wrapped = header + struct.pack('<I', zlib.crc32(header)) + payload
    manifest = {'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        for name, data in [('valence.vld', wrapped), (BIN, payload), ('Image', image)]}}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    (root / 'valence.vld').write_bytes(wrapped)
    return image, payload


class ExtractTests(unittest.TestCase):
    def test_both_exact_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); image, payload = fixture(root)
            extract(root, ['image', 'bin'])
            self.assertEqual((root / 'Image').read_bytes(), image)
            self.assertEqual((root / BIN).read_bytes(), payload)

    def test_corrupt_crc_rejected_even_with_valid_wrapper_hash(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); fixture(root, corrupt_crc=True)
            with self.assertRaises(RuntimeError):
                extract(root, ['image', 'bin'])
            self.assertFalse((root / 'Image').exists())

    def test_existing_output_does_not_partially_write_another(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); fixture(root)
            (root / BIN).write_bytes(b'preserve')
            with self.assertRaises(RuntimeError):
                extract(root, ['image', 'bin'])
            self.assertFalse((root / 'Image').exists())
            self.assertEqual((root / BIN).read_bytes(), b'preserve')

    def test_wrong_extracted_image_digest_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); fixture(root)
            m = json.loads((root / 'manifest.json').read_text()); m['files']['Image']['sha256'] = '0' * 64
            (root / 'manifest.json').write_text(json.dumps(m))
            with self.assertRaises(RuntimeError):
                extract(root, ['bin', 'image'])
            self.assertFalse((root / BIN).exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
