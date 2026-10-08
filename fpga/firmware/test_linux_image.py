"""Host-only negative checks; no simulator or cross-compilation required."""
import struct
import tempfile
import unittest
from pathlib import Path

from build_linux import KERNEL, LOAD, MONITOR, image_header, validate_payload, validate_payload_elf


class LinuxImageTests(unittest.TestCase):
    def test_builder_padding_metadata_does_not_claim_all_zero(self):
        root = Path(__file__).resolve().parent
        for relative in ('build_linux.py', 'repack_linux.py', 'linux_net/build_image.py',
                         'debian_rootfs/build_image.py'):
            with self.subTest(builder=relative):
                source = (root / relative).read_text()
                self.assertIn('payload_alignment_padding_bytes', source)
                self.assertNotIn('payload_zero_padding_bytes', source)

    def test_elf_segments_and_payload_are_exactly_bound(self):
        kernel, padding = bytes(range(16)), b'\x01\x00' + bytes(6)
        combined = b'FW!' + bytes(KERNEL - LOAD - 3) + kernel + padding
        elf = bytearray(1024)
        ident = b'\x7fELF\x02\x01\x01' + bytes(9)
        elf[:64] = struct.pack('<16sHHIQQQIHHHHHH', ident, 2, 243, 1, LOAD,
                              64, 640, 0, 64, 56, 2, 64, 3, 2)
        struct.pack_into('<IIQQQQQQ', elf, 64, 1, 5, 384, LOAD, LOAD, 3, 3, 16)
        struct.pack_into('<IIQQQQQQ', elf, 120, 1, 5, 512, KERNEL, KERNEL, 24, 24, 16)
        elf[384:387] = b'FW!'
        names = b'\0.payload\0.shstrtab\0'
        elf[416:416+len(names)] = names
        elf[512:536] = kernel + padding
        struct.pack_into('<IIQQQQIIQQ', elf, 704, 1, 1, 6, KERNEL, 512, 24, 0, 0, 16, 0)
        struct.pack_into('<IIQQQQIIQQ', elf, 768, 10, 3, 0, 0, 416, len(names), 0, 0, 1, 0)
        self.assertEqual(validate_payload_elf(elf, combined, kernel)['load_segments_verified'], 2)
        for offset in (18, 32, 40, 54, 56, 58, 60, 62, 144, 384, 512, 728):
            bad = bytearray(elf)
            bad[offset:offset+2] = b'\xff\xff'
            with self.subTest(offset=offset), self.assertRaises(RuntimeError):
                validate_payload_elf(bad, combined, kernel)
        with self.assertRaises(RuntimeError):
            validate_payload_elf(elf, combined[:-1], kernel)
        with self.assertRaises(RuntimeError):
            validate_payload_elf(elf, combined, kernel, KERNEL + 16)

    def test_exact_retained_compressed_nop_alignment(self):
        prefix, kernel = bytes(KERNEL - LOAD), bytes(range(16))
        padding = b'\x01\x00' + bytes(6)
        self.assertEqual(validate_payload(prefix + kernel + padding, kernel), 8)
        for bad in (b'\x01', b'\x01\x00', padding[:-1], padding + bytes(8),
                    b'\x13\x00\x00\x00' + bytes(4), b'\x02\x00' + bytes(6)):
            with self.subTest(padding=bad), self.assertRaises(RuntimeError):
                validate_payload(prefix + kernel + bad, kernel)
        with self.assertRaises(RuntimeError):
            validate_payload(prefix + kernel + b'x' + padding, kernel + b'x')
        with self.assertRaises(RuntimeError):
            validate_payload(prefix + kernel + padding, kernel, KERNEL + len(kernel))

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
