import io
import struct
import sys
import types
import unittest
from unittest.mock import patch
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


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TimedPort(FakePort):
    """One second per send; seven-second final RAM verification delay."""
    def __init__(self, clock, *, missing_done=False, duplicate_final_ack=False, **kwargs):
        super().__init__(**kwargs)
        self.clock = clock
        self.missing_done = missing_done
        self.duplicate_final_ack = duplicate_final_ack
        self.deferred = []

    def write(self, data):
        self.clock.advance(1.0)
        result = super().write(data)
        index = self.pending.find(b"VDON")
        if index >= 0:
            done = bytes(self.pending[index:])
            del self.pending[index:]
            if self.duplicate_final_ack:
                self.deferred.append((3.0, struct.pack("<4sII", b"VACK", self.expected - 1, 0)))
            if not self.missing_done:
                self.deferred.append((7.0, done))
        return result

    def read(self, count):
        if not self.pending:
            if self.deferred:
                delay, data = self.deferred.pop(0)
                self.clock.advance(delay)
                self.pending += data
            else:
                self.clock.advance(0.05)
        return super().read(count)


class StatusPort:
    """Independent post-VDON UART stream with packet gaps and a bounded clock."""
    def __init__(self, fragments, clock, output=None):
        self.fragments = list(fragments)
        self.clock = clock
        self.writes = []
        self.consumed = bytearray()
        self.output = output

    def read(self, count):
        if self.output is not None:
            # The last read must already be visible before the next UART read.
            assert self.output.getvalue() == bytes(self.consumed)
            assert self.output.flush_count == len(self.consumed)
        self.clock.advance(0.001)
        if not self.fragments:
            return b""
        result = self.fragments[0][:count]
        self.fragments[0] = self.fragments[0][count:]
        if not self.fragments[0]:
            self.fragments.pop(0)
        self.consumed += result
        return result

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def flush(self):
        pass


class FlushedOutput(io.BytesIO):
    def __init__(self):
        super().__init__()
        self.flush_count = 0

    def flush(self):
        self.flush_count += 1


class BootStatusTests(unittest.TestCase):
    def test_autoboot_never_sends_g_with_or_without_run(self):
        for run in (False, True):
            with self.subTest(run=run):
                clock, output = FakeClock(), FlushedOutput()
                status = b"\r\nDOWNLOAD OK\r\nAUTOBOOT\r\n"
                guest = b"GUEST first bytes\r\n> "
                port = StatusPort([status + guest], clock, output)
                with patch.object(protocol.time, "monotonic", clock):
                    self.assertEqual(protocol.finish_download(port, run=run, timeout=1, output=output),
                                     "autoboot")
                self.assertEqual(port.writes, [])
                self.assertEqual(output.getvalue(), status)
                # Everything after AUTOBOOT, including the first guest byte, is
                # still available for the regular receive/interactive console.
                port.output = None
                protocol.console_step(port, output=output)
                self.assertEqual(output.getvalue(), status + guest)

    def test_fragmented_autoboot_and_diagnostics_are_forwarded_immediately(self):
        clock, output = FakeClock(), FlushedOutput()
        fragments = [b"\r\nDOWNLOAD OK\r\n", b"", b"RAM check\r\n", b"AUT", b"",
                     b"OB", b"OOT\r", b"", b"\n", b"guest"]
        port = StatusPort(fragments, clock, output)
        with patch.object(protocol.time, "monotonic", clock):
            self.assertEqual(protocol.finish_download(port, run=True, timeout=1, output=output), "autoboot")
        self.assertEqual(output.getvalue(), b"\r\nDOWNLOAD OK\r\nRAM check\r\nAUTOBOOT\r\n")
        self.assertEqual(port.fragments, [b"guest"])
        self.assertEqual(port.writes, [])

    def test_legacy_readiness_sends_g_only_when_requested(self):
        for status in (b"\r\nDOWNLOAD OK\r\nready to boot\r\n",
                       b"\r\nDOWNLOAD OK\r\nr:RAM d:LOAD g:RUN\r\n> ",
                       b"\r\nDOWNLOAD OK\r\nmonitor> "):
            for run in (False, True):
                with self.subTest(status=status, run=run):
                    clock, output = FakeClock(), FlushedOutput()
                    port = StatusPort([status + b"NEXT"], clock, output)
                    with patch.object(protocol.time, "monotonic", clock):
                        self.assertEqual(protocol.finish_download(port, run=run, timeout=1, output=output),
                                         "legacy")
                    self.assertEqual(port.writes, [b"g"] if run else [])
                    self.assertEqual(output.getvalue(), status)
                    self.assertEqual(port.fragments, [b"NEXT"])

    def test_missing_or_partial_status_never_sends_g(self):
        for status in (b"", b"\r\nDOWNLOAD OK\r\n", b"AUTOBOOT\r", b"AUTOBOOT\n",
                       b"NOT AUTOBOOT\r\n", b"ready to boot\r", b"download mode (UART)\r\n"):
            with self.subTest(status=status):
                clock, output = FakeClock(), FlushedOutput()
                port = StatusPort([status], clock, output)
                with patch.object(protocol.time, "monotonic", clock), \
                        self.assertRaisesRegex(TimeoutError, "guest execution is unconfirmed"):
                    protocol.finish_download(port, run=True, timeout=0.2, output=output)
                self.assertEqual(output.getvalue(), status)
                self.assertEqual(port.writes, [])

    def test_launch_failure_after_vdon_does_not_trigger_legacy_prompt(self):
        for failure in (b"RAM CRC FAIL", b"IMAGE CRC FAIL", b"NO IMAGE", b"NO TRUSTED IMAGE",
                        b"IMAGE RECORD FAIL", b"VERIFY CANCELLED", b"DOWNLOAD ABORT",
                        b"MEMORY DMA BUSY; RESET REQUIRED"):
            with self.subTest(failure=failure):
                clock, output = FakeClock(), FlushedOutput()
                status = b"\r\nDOWNLOAD OK\r\n" + failure + b"\r\n"
                port = StatusPort([status + b"monitor> "], clock, output)
                with patch.object(protocol.time, "monotonic", clock), \
                        self.assertRaisesRegex(protocol.ProtocolError, "ROM refused to start after VDON"):
                    protocol.finish_download(port, run=True, timeout=1, output=output)
                self.assertEqual(output.getvalue(), status)
                self.assertEqual(port.fragments, [b"monitor> "])
                self.assertEqual(port.writes, [])

    def test_invalid_status_timeout_is_rejected_without_uart_io(self):
        for timeout in (0, -1, float("nan"), float("inf")):
            port = StatusPort([b"AUTOBOOT\r\n"], FakeClock())
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                protocol.finish_download(port, run=True, timeout=timeout)
            self.assertEqual(port.consumed, b"")
            self.assertEqual(port.writes, [])

    def test_cli_autoboot_console_preserves_guest_prefix_and_ignores_run(self):
        class AutomaticPort(FakePort):
            def __init__(self):
                super().__init__()
                self.writes = []

            def write(self, data):
                self.writes.append(bytes(data))
                if data == b"g":
                    return len(data)
                was_data = self.state == "data"
                result = super().write(data)
                if was_data and self.state == "menu":
                    self.pending += b"\r\nDOWNLOAD OK\r\nAUTOBOOT\r\nGUEST FIRST > prompt\r\n"
                return result

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        def receive_once(port):
            protocol.console_step(port)
            raise KeyboardInterrupt

        for run in (False, True):
            with self.subTest(run=run), tempfile.TemporaryDirectory() as directory:
                image = Path(directory) / "image.bin"
                image.write_bytes(bytes(8))
                port, raw = AutomaticPort(), io.BytesIO()
                stdout = io.TextIOWrapper(raw, encoding="utf-8")
                argv = ["uart_load.py", "TEST", str(image), "--console"] + (["--run"] if run else [])
                serial = types.SimpleNamespace(Serial=lambda *args, **kwargs: port)
                with patch.object(sys, "argv", argv), patch.object(sys, "stdout", stdout), \
                        patch.dict(sys.modules, {"serial": serial}), patch.object(protocol, "console", receive_once):
                    protocol.main()
                stdout.flush()
                text = raw.getvalue()
                self.assertNotIn(b"g", port.writes)
                self.assertIn(b"RAM VERIFIED", text)
                self.assertIn(b"ROM automatic start announced (with or without --run)", text)
                self.assertIn(b"guest execution must be confirmed", text)
                self.assertIn(b"GUEST FIRST > prompt\r\n", text)
                self.assertEqual(port.pending, b"")


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
            error = protocol.ProtocolError if status == b"NO IMAGE\r\n" else TimeoutError
            with self.assertRaises(error):
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

    def test_timing_separates_upload_from_final_ram_verification(self):
        clock = FakeClock()
        port = TimedPort(clock)
        progress = []
        with patch.object(protocol.time, "monotonic", clock):
            stats = protocol.upload(port, bytes(516), verify_timeout=30,
                                    progress=lambda done, total: progress.append((done, clock())))
        self.assertEqual((stats.payload_bytes, stats.chunk_frames, stats.retransmits), (516, 3, 0))
        self.assertEqual((stats.final_frame_seconds, stats.upload_seconds,
                          stats.verify_seconds, stats.elapsed_seconds), (5.0, 5.0, 7.0, 12.0))
        self.assertTrue(stats.ram_verified)
        self.assertEqual(progress, [(256, 3.0), (512, 4.0), (516, 5.0)])
        self.assertIn("upload=5.00s final_verification_wait=7.00s total=12.00s", stats.summary())
        self.assertIn("RUN/boot not confirmed", stats.summary())

    def test_timing_lost_final_ack_does_not_invent_a_phase_boundary(self):
        clock = FakeClock()
        port = TimedPort(clock, drop_ack_once=2)
        with patch.object(protocol.time, "monotonic", clock):
            stats = protocol.upload(port, bytes(516), verify_timeout=30)
        self.assertEqual((stats.final_frame_seconds, stats.elapsed_seconds), (5.0, 12.0))
        self.assertIsNone(stats.upload_seconds)
        self.assertIsNone(stats.verify_seconds)
        self.assertTrue(stats.ram_verified)
        self.assertEqual(port.frame_count[2], 1)
        self.assertIn("split unavailable (final ACK not observed", stats.summary())
        self.assertNotIn("final_verification_wait=", stats.summary())
        self.assertIn("RUN/boot not confirmed", stats.summary())

    def test_duplicate_final_ack_does_not_restart_upload_timing(self):
        clock = FakeClock()
        with patch.object(protocol.time, "monotonic", clock):
            stats = protocol.upload(TimedPort(clock, duplicate_final_ack=True), bytes(8), verify_timeout=30)
        self.assertEqual((stats.upload_seconds, stats.verify_seconds, stats.elapsed_seconds),
                         (3.0, 10.0, 13.0))

    def test_final_silence_is_not_verified_or_retransmitted(self):
        for lost_final_ack in (False, True):
            with self.subTest(lost_final_ack=lost_final_ack):
                clock = FakeClock()
                port = TimedPort(clock, missing_done=True,
                                 drop_ack_once=0 if lost_final_ack else None)
                stats = protocol.UploadStats()
                with patch.object(protocol.time, "monotonic", clock), self.assertRaises(TimeoutError):
                    protocol.upload(port, bytes(8), verify_timeout=0.2, stats=stats)
                self.assertEqual(port.frame_count[0], 1)
                self.assertEqual(stats.retransmits, 0)
                self.assertFalse(stats.ram_verified)
                self.assertIsNone(stats.verify_seconds)
                self.assertEqual(stats.upload_seconds, None if lost_final_ack else 3.0)
                self.assertGreaterEqual(stats.elapsed_seconds, 3.2)
                self.assertIn("verification not confirmed", stats.summary())
                if not lost_final_ack:
                    self.assertIn("upload=3.00s final_verification_wait=", stats.summary())

    def test_timing_crc_retry_counts_only_acknowledged_upload_boundary(self):
        clock = FakeClock()
        port = TimedPort(clock, reject_once=0)
        with patch.object(protocol.time, "monotonic", clock):
            stats = protocol.upload(port, bytes(8), verify_timeout=30)
        self.assertEqual((stats.chunk_frames, stats.retransmits), (2, 1))
        self.assertEqual((stats.final_frame_seconds, stats.upload_seconds,
                          stats.verify_seconds, stats.elapsed_seconds), (4.0, 4.0, 7.0, 11.0))

    def test_invalid_final_reply_never_reports_ram_verified(self):
        class CorruptDone(TimedPort):
            def write(self, data):
                result = super().write(data)
                if self.deferred:
                    delay, reply = self.deferred[-1]
                    self.deferred[-1] = (delay, reply[:-1] + bytes([reply[-1] ^ 1]))
                return result

        clock, stats = FakeClock(), protocol.UploadStats()
        with patch.object(protocol.time, "monotonic", clock), \
                self.assertRaisesRegex(protocol.ProtocolError, "invalid final length/CRC"):
            protocol.upload(CorruptDone(clock), bytes(8), verify_timeout=30, stats=stats)
        self.assertFalse(stats.ram_verified)
        self.assertIsNone(stats.verify_seconds)
        self.assertIn("verification not confirmed", stats.summary())

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
