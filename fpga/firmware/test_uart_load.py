import struct
import unittest
import zlib
import uart_load as protocol
from build import memory_images
import tempfile
from pathlib import Path


class FakePort:
    def __init__(self, *, reject_once=None, drop_ack_once=None):
        self.pending = bytearray()
        self.image = bytearray()
        self.reject_once = reject_once
        self.drop_ack_once = drop_ack_once
        self.expected = 0
        self.frame_count = {}
        self.state = "menu"

    def reset_input_buffer(self):
        self.pending.clear()

    def flush(self):
        pass

    def read(self, count):
        result = bytes(self.pending[:count])
        del self.pending[:count]
        return result

    def ack(self, sequence, status=0):
        self.pending += struct.pack("<4sII", b"VACK", sequence, status)

    def write(self, data):
        if data == b"d" and self.state == "menu":
            self.pending += b"VLOAD1\r\n"
            self.state = "header"
        elif self.state == "header":
            self.assert_header(data)
            self.state = "data"
            self.ack(protocol.HEADER_SEQ)
        else:
            magic, seq, size, crc = struct.unpack("<4sIII", data[:16])
            payload = data[16:]
            assert magic == b"DATA" and size == len(payload)
            assert zlib.crc32(payload) == crc
            self.frame_count[seq] = self.frame_count.get(seq, 0) + 1
            if seq == self.reject_once:
                self.reject_once = None
                self.ack(seq, 3)
            elif seq < self.expected:
                self.ack(seq)
            else:
                assert seq == self.expected
                self.image += payload
                self.expected += 1
                if seq == self.drop_ack_once:
                    self.drop_ack_once = None
                else:
                    self.ack(seq)
                if len(self.image) == self.length:
                    self.pending += struct.pack("<4sII", b"VDON", self.length, self.crc)
                    self.state = "menu"
        return len(data)

    def assert_header(self, data):
        magic, version, base, entry, length, crc, chunk, reserved, header_crc = (
            struct.unpack("<4s8I", data))
        assert (magic, version, base, chunk, reserved) == (
            b"VLD1", 1, protocol.RAM_BASE, 256, 0)
        assert zlib.crc32(data[:32]) == header_crc
        assert base <= entry < base + length
        self.length, self.crc = length, crc


class ProtocolTests(unittest.TestCase):
    def test_ready_without_prompt_and_legacy_compatibility(self):
        for status in (b"\r\nDOWNLOAD OK\r\nready to boot\r\n",
                       b"\r\nDOWNLOAD OK\r\nr:RAM d:LOAD g:RUN\r\n> "):
            port = FakePort()
            port.pending += status + b"NEXT"
            protocol.wait_ready(port, timeout=0.01)
            self.assertEqual(port.read(4), b"NEXT")

    def test_incomplete_or_invalid_state_is_not_ready(self):
        for status in (b"ready to boot\r", b"download mode (UART)\r\n",
                       b"NO IMAGE\r\n", b"DOWNLOAD OK\r\n"):
            port = FakePort()
            port.pending += status
            with self.assertRaises(TimeoutError):
                protocol.wait_ready(port, timeout=0.001)

    def test_crc_known_vector(self):
        self.assertEqual(zlib.crc32(b"123456789"), 0xcbf43926)

    def test_header_and_little_endian(self):
        header = protocol.image_header(bytes(4))
        self.assertEqual(len(header), 36)
        self.assertEqual(header[8:12], bytes.fromhex("00002080"))
        self.assertEqual(zlib.crc32(header[:32]),
                         struct.unpack("<I", header[32:])[0])

    def test_reject_elf_and_bad_bounds(self):
        for image, entry in ((b"", protocol.RAM_BASE),
                             (b"\x7fELF", protocol.RAM_BASE),
                             (bytes(protocol.IMAGE_LIMIT + 1), protocol.RAM_BASE),
                             (bytes(4), protocol.RAM_BASE + 4),
                             (bytes(8), protocol.RAM_BASE + 1)):
            with self.assertRaises(ValueError):
                protocol.image_header(image, entry)

    def test_transfer_retry_and_final_short_chunk(self):
        image = bytes(range(256)) * 2 + b"tail"
        port = FakePort(reject_once=1)
        protocol.upload(port, image, timeout=0.01)
        self.assertEqual(port.image, image)
        self.assertEqual(port.frame_count[1], 2)

    def test_lost_ack_resends_idempotently(self):
        image = bytes(516)
        port = FakePort(drop_ack_once=0)
        protocol.upload(port, image, timeout=0.005)
        self.assertEqual(port.image, image)
        self.assertEqual(port.frame_count[0], 2)

    def test_final_crc_nak_retries(self):
        image = bytes(8)
        port = FakePort(reject_once=0)
        protocol.upload(port, image, timeout=0.005)
        self.assertEqual(port.image, image)
        self.assertEqual(port.frame_count[0], 2)

    def test_final_done_without_ack(self):
        image = bytes(8)
        port = FakePort(drop_ack_once=0)
        protocol.upload(port, image, timeout=0.005)
        self.assertEqual(port.image, image)

    def test_ddr_upload_larger_than_one_mib(self):
        image = bytes(range(256)) * 4097 + b"tail"
        with self.assertRaises(ValueError):
            protocol.image_header(image)
        port = FakePort(reject_once=4096)
        protocol.upload(port, image, image_limit=protocol.DDR_IMAGE_LIMIT)
        self.assertEqual(port.image, image)
        self.assertEqual(port.frame_count[4096], 2)

    def test_ddr_limit_without_large_allocation(self):
        class SizedImage:
            def __init__(self, size):
                self.size = size
            def __len__(self):
                return self.size
            def startswith(self, prefix):
                return False
        limit = protocol.DDR_IMAGE_LIMIT
        self.assertEqual(protocol.RAM_BASE + limit, 0xa01fc000)
        protocol.validate_image(SizedImage(limit), protocol.RAM_BASE, limit)
        with self.assertRaises(ValueError):
            protocol.validate_image(SizedImage(limit + 1), protocol.RAM_BASE, limit)
        self.assertEqual(protocol.verification_timeout(1), 30.0)
        self.assertEqual(protocol.verification_timeout(2 * 1024 * 1024), 128.0)
        for invalid in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                protocol.upload(FakePort(), bytes(4), verify_timeout=invalid)

    def test_memory_images_byte_order_and_banks(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            memory_images(bytes.fromhex("1122334455667788"), output)
            self.assertEqual((output / "bootrom.even.hex").read_text().splitlines()[0],
                             "44332211")
            self.assertEqual((output / "bootrom.odd.hex").read_text().splitlines()[0],
                             "88776655")
            self.assertEqual(len((output / "bootrom.even.hex").read_text().splitlines()),
                             16384)


if __name__ == "__main__":
    unittest.main()
