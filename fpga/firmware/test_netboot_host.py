import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import socket
import struct
import netboot_host as host


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.replies = []
        self.dropped = False
    def settimeout(self, value):
        pass
    def sendto(self, data, peer):
        self.sent.append(data)
        block = struct.unpack("!H", data[2:4])[0]
        if block == 2 and not self.dropped:
            self.dropped = True
            self.replies.append("timeout")
        else:
            self.replies.append((struct.pack("!HH", 4, block), peer))
    def recvfrom(self, size):
        item = self.replies.pop(0)
        if item == "timeout":
            raise socket.timeout()
        return item

class Tests(unittest.TestCase):
    def test_pack_validate(self):
        with tempfile.TemporaryDirectory() as d:
            source, output = Path(d) / "app.bin", Path(d) / "valence.vld"
            source.write_bytes(bytes(range(256)) * 5)
            host.pack(source, output)
            self.assertEqual(host.validate(output), 1280)
            with self.assertRaises(ValueError):
                host.pack(source, source)
            with self.assertRaises(ValueError):
                host.pack(source, output)
            data = bytearray(output.read_bytes())
            data[-1] ^= 1
            output.write_bytes(data)
            with self.assertRaises(ValueError):
                host.validate(output)
    def test_range(self):
        for args in ((0, 0), (host.LIMIT + 1, 0), (4, 0, host.BASE + 8, host.BASE),
                     (4, 0, host.BASE, host.BASE + 1), (4, 0, host.BASE, host.BASE + 4)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                host.header(*args)
    def test_rrq(self):
        self.assertEqual(host.request(b"\0\1valence.vld\0octet\0"), "valence.vld")
        for bad in (b"", b"\0\1../test\0octet\0", b"\0\1x\0netascii\0",
                    b"\0\1x\0octet\0blksize\01024\0", b"\0\1\xff\0octet\0"):
            self.assertIsNone(host.request(bad))
    def test_retry_and_zero_eof(self):
        for size in (4, 512, 1024, 1025):
            fake = FakeSocket()
            self.assertEqual(host.transfer(fake, ("192.168.137.30", 49152), io.BytesIO(bytes(size))), size)
            if size % 512 == 0:
                self.assertEqual(len(fake.sent[-1]), 4)
            if size > 512:
                self.assertGreater(len(fake.sent), (size + 511) // 512)

    def test_progress_counts_acked_bytes_only(self):
        updates = []
        fake = FakeSocket()
        self.assertEqual(host.transfer(fake, ("192.168.137.30", 49152), io.BytesIO(bytes(1025)),
                                       progress=lambda *args: updates.append(args)), 1025)
        self.assertEqual(updates, [(512, False), (1024, False), (1025, True)])
        self.assertEqual(len(fake.sent), 4)  # Block 2 was retransmitted once.

    def test_progress_waits_for_zero_eof_ack(self):
        updates = []
        host.transfer(FakeSocket(), ("192.168.137.30", 49152), io.BytesIO(bytes(512)),
                      progress=lambda *args: updates.append(args))
        self.assertEqual(updates, [(512, False), (512, True)])

    def test_progress_timeout_does_not_finish(self):
        class MissingEofAck(FakeSocket):
            def recvfrom(self, size):
                if len(self.sent[-1]) == 4:
                    raise socket.timeout()
                return super().recvfrom(size)
        updates = []
        with self.assertRaises(TimeoutError):
            host.transfer(MissingEofAck(), ("192.168.137.30", 49152), io.BytesIO(bytes(512)),
                          retries=2, progress=lambda *args: updates.append(args))
        self.assertEqual(updates, [(512, False)])

    def test_progress_ignores_wrong_peer_and_ack(self):
        class UnrelatedReplies(FakeSocket):
            def sendto(self, data, peer):
                super().sendto(data, peer)
                self.replies.insert(0, (b"\x00\x04\x00\x09", peer))
                self.replies.insert(0, (b"\x00\x04" + data[2:4], ("192.168.137.99", peer[1])))
        updates = []
        host.transfer(UnrelatedReplies(), ("192.168.137.30", 49152), io.BytesIO(bytes(100)),
                      progress=lambda *args: updates.append(args))
        self.assertEqual(updates, [(100, True)])

    def test_progress_log_rate_eta_and_throttle(self):
        now = [0.0]
        stream = io.StringIO()
        progress = host.TransferProgress(2 * 1048576, stream=stream, clock=lambda: now[0])
        initial = stream.getvalue()
        now[0] = 0.1
        progress.update(512)
        self.assertEqual(stream.getvalue(), initial)
        now[0] = 1.0
        progress.update(1048576)
        self.assertIn("50.0%", stream.getvalue())
        self.assertIn("1.000 MiB/s ETA 1.0s", stream.getvalue())
        now[0] = 1.1
        progress.update(2 * 1048576, complete=True)
        progress.close()
        self.assertIn("100.0%", stream.getvalue())
        self.assertIn("2,097,152/2,097,152 bytes", stream.getvalue())
        self.assertEqual(len(stream.getvalue().splitlines()), 3)
        self.assertNotIn("\r", stream.getvalue())

    def test_progress_terminal_close_and_eof_pending(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True
        stream = Terminal()
        progress = host.TransferProgress(512, stream=stream, clock=lambda: 1.0)
        progress.update(512, force=True)
        progress.close()
        progress.close()
        self.assertIn("99.9%", stream.getvalue())
        self.assertNotIn("100.0%", stream.getvalue())
        self.assertIn("\r", stream.getvalue())
        self.assertEqual(stream.getvalue().count("\n"), 1)

    def test_stats_separate_io_and_ack_wait_including_loss(self):
        clock = FakeClock()

        class TimedSource(io.BytesIO):
            def read(self, size):
                clock.advance(0.1)
                return super().read(size)

        class TimedSocket(FakeSocket):
            def sendto(self, data, peer):
                clock.advance(0.2)
                super().sendto(data, peer)

            def recvfrom(self, size):
                clock.advance(1.0 if self.replies[0] == "timeout" else 0.3)
                return super().recvfrom(size)

        stats = host.TransferStats()
        self.assertEqual(host.transfer(TimedSocket(), ("192.168.137.30", 49152),
                                       TimedSource(bytes(1024)), stats=stats, clock=clock), 1024)
        self.assertEqual((stats.bytes_acked, stats.data_packets, stats.acked_blocks,
                          stats.retransmits, stats.timeouts, stats.reply_packets,
                          stats.ignored_packets, stats.eof_acked),
                         (1024, 4, 3, 1, 1, 3, 0, True))
        self.assertAlmostEqual(stats.read_seconds, 0.3)
        self.assertAlmostEqual(stats.send_seconds, 0.8)
        self.assertAlmostEqual(stats.ack_wait_seconds, 1.9)
        self.assertAlmostEqual(stats.elapsed_seconds, 3.0)
        self.assertIn("other=0.000000s", stats.summary())
        self.assertIn("eof_acked=yes", stats.summary())

    def test_stats_failed_eof_preserves_partial_evidence(self):
        clock = FakeClock()

        class MissingEofAck(FakeSocket):
            def recvfrom(self, size):
                if len(self.sent[-1]) == 4:
                    clock.advance(1.0)
                    raise socket.timeout()
                clock.advance(0.1)
                return super().recvfrom(size)

        stats = host.TransferStats()
        with self.assertRaises(TimeoutError):
            host.transfer(MissingEofAck(), ("192.168.137.30", 49152), io.BytesIO(bytes(512)),
                          retries=2, stats=stats, clock=clock)
        self.assertEqual((stats.bytes_acked, stats.data_packets, stats.acked_blocks,
                          stats.retransmits, stats.timeouts, stats.eof_acked),
                         (512, 3, 1, 1, 2, False))
        self.assertAlmostEqual(stats.ack_wait_seconds, 2.1)
        self.assertAlmostEqual(stats.elapsed_seconds, 2.1)
        self.assertIn("eof_acked=no", stats.summary())

    def test_stats_count_ignored_packets_and_rejection(self):
        class Rejected(FakeSocket):
            def sendto(self, data, peer):
                self.replies = [(b"\x00\x04" + data[2:4], ("192.168.137.99", peer[1])),
                                (b"\x00\x04\x00\x09", peer),
                                (b"\x00\x05\x00\x00rejected\x00", peer)]

        stats = host.TransferStats()
        with self.assertRaisesRegex(RuntimeError, "board rejected"):
            host.transfer(Rejected(), ("192.168.137.30", 49152), io.BytesIO(b"data"), stats=stats)
        self.assertEqual((stats.reply_packets, stats.ignored_packets, stats.acked_blocks,
                          stats.bytes_acked, stats.eof_acked), (3, 2, 0, 0, False))

    def test_full_board_packed_length_rollover_and_lost_ack(self):
        # Independent count/sequence oracle for the measured board file size.
        # Stream the whole transfer without retaining a 66 MB packet history.
        length = 66_348_776
        clock = FakeClock()

        class Source:
            remaining = length
            reads = 0

            def read(self, size):
                if size != 512:
                    raise AssertionError("TFTP block size changed")
                self.reads += 1
                count = min(size, self.remaining)
                self.remaining -= count
                clock.advance(0.000001)
                return bytes(count)

        class Receiver:
            acked = 0
            sent = 0
            wire_bytes = 0
            dropped = False
            rollover = []
            last = None

            def settimeout(self, value):
                if value <= 0:
                    raise AssertionError("invalid timeout")

            def sendto(self, data, peer):
                opcode, number = struct.unpack("!HH", data[:4])
                logical = self.acked + 1
                if opcode != 3 or number != logical % 65536:
                    raise AssertionError("block advanced without its matching ACK")
                if self.last is not None and self.last[0] == logical and self.last[1] != data:
                    raise AssertionError("retry changed DATA bytes")
                self.last = (logical, data)
                self.peer = peer
                self.sent += 1
                self.wire_bytes += len(data)
                if 65534 <= logical <= 65538:
                    self.rollover.append(number)
                clock.advance(0.000001)

            def recvfrom(self, size):
                if self.acked == 65535 and not self.dropped:
                    self.dropped = True
                    clock.advance(1.0)
                    raise socket.timeout()
                self.acked += 1
                clock.advance(0.000001)
                return struct.pack("!HH", 4, self.acked % 65536), self.peer

        source, receiver, stats = Source(), Receiver(), host.TransferStats()
        result = host.transfer(receiver, ("192.168.137.30", 49152), source,
                               stats=stats, clock=clock)
        self.assertEqual(result, length)
        self.assertEqual(receiver.rollover, [65534, 65535, 0, 0, 1, 2])
        self.assertEqual((receiver.acked, receiver.sent, source.reads), (129588, 129589, 129588))
        self.assertEqual(receiver.wire_bytes, length + 4 * 129588 + 516)
        self.assertEqual(len(receiver.last[1]), 4 + 232)
        self.assertEqual((stats.bytes_acked, stats.acked_blocks, stats.data_packets,
                          stats.retransmits, stats.timeouts, stats.eof_acked),
                         (length, 129588, 129589, 1, 1, True))
        self.assertAlmostEqual(stats.read_seconds, 129588 * 0.000001)
        self.assertAlmostEqual(stats.send_seconds, 129589 * 0.000001)
        self.assertAlmostEqual(stats.ack_wait_seconds, 1.0 + 129588 * 0.000001)

    def test_serve_completion_is_transport_only_and_reports_stats(self):
        class ContextSocket(FakeSocket):
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def bind(self, address):
                pass

        with tempfile.TemporaryDirectory() as directory:
            source, packed = Path(directory) / "app.bin", Path(directory) / "valence.vld"
            source.write_bytes(b"data")
            host.pack(source, packed)
            listener, session = ContextSocket(), ContextSocket()
            listener.replies = [(b"\0\1valence.vld\0octet\0", ("192.168.137.30", 49152))]
            output = io.StringIO()
            with patch.object(host.socket, "socket", side_effect=[listener, session]), \
                    patch.object(host.sys, "stdout", output):
                host.serve(packed, "192.168.137.1", once=True, show_progress=False)
            self.assertIn("final EOF ACK received; RAM verification and RUN/boot are not confirmed",
                          output.getvalue())
            self.assertIn("TFTP STATS bytes_acked=40 data_packets=1 acked_blocks=1", output.getvalue())
            self.assertEqual(output.getvalue().count("TFTP STATS"), 1)

if __name__ == "__main__":
    unittest.main()
