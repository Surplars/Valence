"""Host-only negative checks; no simulator or cross-compilation required."""
import struct
import tempfile
import unittest
from pathlib import Path

from build_linux import KERNEL, LOAD, MONITOR, image_header, validate_payload


class LinuxImageTests(unittest.TestCase):
    def test_payload_padding_and_integrity(self):
        kernel = b"small-kernel-payload"
        prefix = bytes(KERNEL - LOAD)
        self.assertEqual(validate_payload(prefix + kernel + bytes(20), kernel), 20)
        for bad in (prefix + kernel[:-1], prefix + kernel + bytes(23),
                    prefix + kernel + b"\x01", prefix + b"wrong-kernel-payload"):
            with self.assertRaises(RuntimeError):
                validate_payload(bad, kernel)

    def test_image_header_and_runtime_bounds(self):
        data = bytearray(64)
        data[0x30:0x38] = b"RISCV\0\0\0"
        data[0x38:0x3c] = b"RSC\x05"
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "Image"
            struct.pack_into("<QQQ", data, 8, 0x200000, 4096, 0)
            image.write_bytes(data)
            self.assertEqual(image_header(image), 4096)
            for offset, size, flags in ((0, 4096, 0), (0x200000, 63, 0),
                                        (0x200000, 4096, 1), (0x200000, MONITOR - KERNEL + 1, 0)):
                struct.pack_into("<QQQ", data, 8, offset, size, flags)
                image.write_bytes(data)
                with self.assertRaises(RuntimeError):
                    image_header(image)
            data[0x30] = 0
            image.write_bytes(data)
            with self.assertRaises(RuntimeError):
                image_header(image)


if __name__ == "__main__":
    unittest.main()
