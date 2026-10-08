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

class WindowSocket:
    """Independent receiver oracle: cumulative ACKs only at a window or EOF.

    Tests can drop DATA/ACK once, and inject unrelated/duplicate traffic. It
    stores only test-sized data and selected boundary packets, not an image.
    """
    def __init__(self, blksize=1024, windowsize=4, drop_data=(), drop_acks=(), clock=None):
        self.blksize, self.windowsize = blksize, windowsize
        self.drop_data, self.drop_acks = set(drop_data), set(drop_acks)
        self.clock = FakeClock() if clock is None else clock
        self.accepted = self.last_ack = self.data_packets = self.bytes_received = 0
        self.replies, self.boundary, self.bursts = [], [], []
        self.burst = []
        self.eof = False
        self.gap_acks = 0

    def settimeout(self, value):
        self.timeout = value

    def sendto(self, data, peer):
        opcode, number = struct.unpack("!HH", data[:4])
        if opcode != 3 or len(data) > self.blksize + 4:
            raise AssertionError("invalid DATA")
        self.data_packets += 1
        self.burst.append(number)
        expected = self.accepted + 1
        if 65533 <= expected <= 65538:
            self.boundary.append(number)
        if number in self.drop_data:
            self.drop_data.remove(number)
            return
        if number == expected % 65536:
            if self.eof:
                raise AssertionError("new DATA after EOF")
            self.accepted += 1
            self.bytes_received += len(data) - 4
            self.eof = len(data) < self.blksize + 4
            if self.accepted - self.last_ack < self.windowsize and not self.eof:
                return
        else:
            self.gap_acks += 1
        self.last_ack = self.accepted
        if self.accepted in self.drop_acks:
            self.drop_acks.remove(self.accepted)
            return
        self.replies.append((struct.pack("!HH", 4, self.accepted % 65536), peer))

    def recvfrom(self, size):
        if self.burst:
            self.bursts.append(self.burst)
            self.burst = []
        self.clock.advance(0.001)
        if not self.replies:
            self.clock.advance(self.timeout)
            raise socket.timeout()
        return self.replies.pop(0)

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
    def test_rrq_negotiates_bounded_options_and_keeps_filename_api(self):
        packet = b"\0\1valence.vld\0OCTET\0blksize\x001024\0windowsize\x004\0"
        parsed = host.parse_request(packet)
        self.assertEqual((parsed.name, parsed.blksize, parsed.windowsize), ("valence.vld", 1024, 4))
        self.assertEqual(parsed.oack, b"\0\6blksize\x001024\0windowsize\x004\0")
        self.assertEqual(host.request(packet), "valence.vld")
        capped = host.parse_request(packet, max_blksize=512, max_windowsize=2)
        self.assertEqual((capped.blksize, capped.windowsize), (512, 2))
        self.assertEqual(capped.oack, b"\0\6blksize\x00512\0windowsize\x002\0")
        large = host.parse_request(b"\0\1x\0octet\0blksize\x0065464\0windowsize\x0065535\0")
        self.assertEqual((large.blksize, large.windowsize), (1024, 4))
        for requested, expected in ((512, 512), (768, 512), (1024, 1024)):
            parsed = host.parse_request(b"\0\1x\0octet\0blksize\0" + str(requested).encode() + b"\0")
            self.assertEqual((parsed.blksize, parsed.windowsize), (expected, 1))
        for window in range(1, 5):
            parsed = host.parse_request(b"\0\1x\0octet\0WINDOWSIZE\0" + str(window).encode() + b"\0")
            self.assertEqual((parsed.blksize, parsed.windowsize), (512, window))
        for window in (8, 16):
            parsed = host.parse_request(b"\0\1x\0octet\0windowsize\0" + str(window).encode() + b"\0",
                                        max_windowsize=window)
            self.assertEqual(parsed.windowsize, window)
        legacy = host.parse_request(b"\0\1x\0octet\0")
        self.assertEqual((legacy.blksize, legacy.windowsize, legacy.oack), (512, 1, None))
        unknown = host.parse_request(b"\0\1x\0octet\0tsize\x000\0")
        self.assertEqual((unknown.blksize, unknown.windowsize, unknown.oack), (512, 1, None))

    def test_rrq_rejects_malformed_or_unbounded_options(self):
        prefix = b"\0\1x\0octet\0"
        bad_options = (b"blksize\0", b"blksize\x001024", b"blksize\0\0", b"\x001024\0",
                       b"blksize\x001024\0BLKSIZE\x00512\0", b"windowsize\x000\0",
                       b"windowsize\x0065536\0", b"windowsize\0-1\0", b"windowsize\0+4\0",
                       b"windowsize\0 4\0", b"windowsize\x004.0\0", b"blksize\x0065465\0",
                       b"blksize\x00256\0", b"windowsize\x00\xff\0", b"unknown\x00\xff\0",
                       b"a\0b\0" * 128)
        for suffix in bad_options:
            with self.subTest(suffix=suffix):
                self.assertIsNone(host.parse_request(prefix + suffix))

    def test_oack_retries_until_matching_ack0_before_reading(self):
        clock, stats, sent = FakeClock(), host.TransferStats(), []
        peer = ("192.168.137.30", 49152)
        oack = host.parse_request(b"\0\1x\0octet\0blksize\x001024\0windowsize\x004\0").oack

        class Socket:
            replies = []
            oacks = 0
            ack0 = False
            def settimeout(self, value):
                self.timeout = value
            def sendto(self, data, who):
                sent.append(data)
                if data == oack:
                    self.oacks += 1
                    if self.oacks == 1:
                        self.replies = [(b"\0\4\0\0", (peer[0], peer[1] + 1)),
                                        (b"\0\4\0\1", peer), (b"\0\4\0\0extra", peer)]
                    else:
                        self.replies = [(b"\0\4\0\0", peer)]
                else:
                    if not self.ack0:
                        raise AssertionError("DATA before ACK0")
                    self.replies = [(b"\0\4" + data[2:4], peer)]
            def recvfrom(self, size):
                clock.advance(0.01)
                if not self.replies:
                    clock.advance(self.timeout)
                    raise socket.timeout()
                reply = self.replies.pop(0)
                if reply == (b"\0\4\0\0", peer):
                    self.ack0 = True
                return reply

        sock = Socket()
        class Source(io.BytesIO):
            def read(self, size):
                if not sock.ack0:
                    raise AssertionError("file read before ACK0")
                return super().read(size)
        self.assertEqual(host.transfer(sock, peer, Source(b"data"), stats=stats, clock=clock, sleeper=clock.advance,
                                       blksize=1024, windowsize=4, oack=oack), 4)
        self.assertEqual(sent[:2], [oack, oack])
        self.assertEqual((stats.oack_packets, stats.oack_retransmits, stats.timeouts,
                          stats.ignored_packets, stats.data_packets), (2, 1, 1, 3, 1))

    def test_oack_failure_is_bounded_and_never_sends_data(self):
        class NoAck:
            sent = []
            def settimeout(self, value):
                pass
            def sendto(self, data, peer):
                self.sent.append(data)
            def recvfrom(self, size):
                raise socket.timeout()
        sock, stats = NoAck(), host.TransferStats()
        source = io.BytesIO(b"data")
        with self.assertRaisesRegex(TimeoutError, "ACK0"):
            host.transfer(sock, ("192.168.137.30", 49152), source, retries=2, stats=stats,
                          blksize=1024, windowsize=4, oack=b"\0\6windowsize\x004\0")
        self.assertEqual(len(sock.sent), 2)
        self.assertEqual(source.tell(), 0)
        self.assertEqual((stats.oack_packets, stats.data_packets, stats.timeouts), (2, 0, 2))

    def test_oack_peer_rejection_stops_without_data(self):
        class Rejected:
            sent = []
            def settimeout(self, value):
                pass
            def sendto(self, data, peer):
                self.sent.append(data)
                self.peer = peer
            def recvfrom(self, size):
                return b"\0\5\0\x08bad options\0", self.peer
        sock, stats, source = Rejected(), host.TransferStats(), io.BytesIO(b"data")
        with self.assertRaisesRegex(RuntimeError, "board rejected"):
            host.transfer(sock, ("192.168.137.30", 49152), source, stats=stats,
                          blksize=1024, windowsize=4, oack=b"\0\6windowsize\x004\0")
        self.assertEqual((len(sock.sent), stats.data_packets, source.tell()), (1, 0, 0))

    def test_recovery_keeps_unacked_payload_and_does_not_reread(self):
        payload = bytes(range(251)) * 30
        class Source(io.BytesIO):
            sizes = []
            def read(self, size):
                self.sizes.append(size)
                return super().read(size)
        class Recorder(WindowSocket):
            packets = {}
            def sendto(self, data, peer):
                number = struct.unpack("!H", data[2:4])[0]
                if number in self.packets and self.packets[number] != data:
                    raise AssertionError("retransmit changed bytes")
                self.packets[number] = data
                super().sendto(data, peer)
        source, sock = Source(payload), Recorder(drop_data=(2,))
        self.assertEqual(host.transfer(sock, ("192.168.137.30", 49152), source,
                                       blksize=1024, windowsize=4, clock=sock.clock, sleeper=sock.clock.advance), len(payload))
        self.assertEqual(len(source.sizes), len(payload) // 1024 + 1)
        self.assertEqual(b"".join(sock.packets[n][4:] for n in sorted(sock.packets)), payload)

    def test_cumulative_windows_and_zero_eof(self):
        for blksize in (512, 1024):
            for windowsize in (1, 2, 3, 4, 8, 16):
                for size in (0, 1, blksize, blksize * windowsize - 1,
                             blksize * windowsize, blksize * windowsize + 1, blksize * 10):
                    with self.subTest(blksize=blksize, windowsize=windowsize, size=size):
                        sock = WindowSocket(blksize, windowsize)
                        stats, updates = host.TransferStats(), []
                        result = host.transfer(sock, ("192.168.137.30", 49152), io.BytesIO(bytes(size)),
                                               blksize=blksize, windowsize=windowsize,
                                               stats=stats, clock=sock.clock, sleeper=sock.clock.advance,
                                               progress=lambda *args: updates.append(args))
                        blocks = size // blksize + 1
                        self.assertEqual(result, size)
                        self.assertEqual((stats.acked_blocks, stats.data_packets), (blocks, blocks))
                        self.assertEqual(updates[-1], (size, True))
                        self.assertTrue(all(not complete for total, complete in updates[:-1]))
                        self.assertEqual(len(updates), (blocks + windowsize - 1) // windowsize)
                        self.assertLessEqual(stats.max_buffered_blocks, windowsize)
                        self.assertLessEqual(stats.max_buffered_bytes, windowsize * (blksize + 4))
                        self.assertTrue(all(len(burst) <= windowsize for burst in sock.bursts))
                        self.assertTrue(sock.eof)

    def test_gap_restarts_full_window_after_cumulative_prefix(self):
        for dropped in (1, 2, 3, 4, 5):
            sock = WindowSocket(drop_data=(dropped,))
            stats, updates = host.TransferStats(), []
            source = io.BytesIO(bytes(9 * 1024 + 7))
            self.assertEqual(host.transfer(sock, ("192.168.137.30", 49152), source,
                                           blksize=1024, windowsize=4, stats=stats, clock=sock.clock, sleeper=sock.clock.advance,
                                           progress=lambda *args: updates.append(args)), 9 * 1024 + 7)
            if dropped < 4:
                self.assertEqual(sock.bursts[1], list(range(dropped, dropped + 4)))
            self.assertGreater(stats.retransmits, 0)
            self.assertEqual(stats.bytes_acked, sock.bytes_received)
            self.assertEqual(stats.acked_blocks, 10)
            self.assertEqual(updates[-1], (9 * 1024 + 7, True))
            self.assertEqual([count for count, _ in updates], sorted(set(count for count, _ in updates)))
            self.assertLessEqual(stats.max_buffered_blocks, 4)

    def test_window_timeout_replays_packets_and_ack_loss_does_not_double_count(self):
        sock = WindowSocket(drop_acks=(4, 8))
        stats = host.TransferStats()
        host.transfer(sock, ("192.168.137.30", 49152), io.BytesIO(bytes(8 * 1024)),
                      blksize=1024, windowsize=4, stats=stats, clock=sock.clock, sleeper=sock.clock.advance)
        self.assertEqual(sock.bursts[:2], [[1, 2, 3, 4], [1, 2, 3, 4]])
        self.assertEqual((stats.acked_blocks, stats.bytes_acked, stats.eof_acked), (9, 8192, True))
        self.assertGreaterEqual(stats.timeouts, 1)
        self.assertGreaterEqual(stats.retransmits, 8)

    def test_window_ignores_foreign_stale_future_and_malformed_acks(self):
        class NoisySocket(WindowSocket):
            injected = False
            def recvfrom(self, size):
                if not self.injected:
                    self.injected = True
                    peer = self.replies[0][1]
                    self.replies[0:0] = [(b"\0\4\0\4", (peer[0], peer[1] + 1)),
                                         (b"\0\4\xff\xff", peer), (b"\0\4\0\5", peer),
                                         (b"\0\4\0\4extra", peer)]
                return super().recvfrom(size)
        sock, stats = NoisySocket(), host.TransferStats()
        host.transfer(sock, ("192.168.137.30", 49152), io.BytesIO(bytes(4096)),
                      blksize=1024, windowsize=4, stats=stats, clock=sock.clock, sleeper=sock.clock.advance)
        self.assertEqual((stats.ignored_packets, stats.retransmits, stats.bytes_acked), (4, 0, 4096))

    def test_duplicate_gap_ack_storm_has_bounded_retransmission(self):
        clock = FakeClock()
        class Storm:
            sent = []
            def settimeout(self, value):
                pass
            def sendto(self, data, peer):
                self.sent.append(data)
                self.peer = peer
            def recvfrom(self, size):
                clock.advance(0.1)
                return b"\0\4\0\0", self.peer
        sock, stats = Storm(), host.TransferStats()
        with self.assertRaises(TimeoutError):
            host.transfer(sock, ("192.168.137.30", 49152), io.BytesIO(bytes(8192)),
                          retries=3, blksize=1024, windowsize=4, stats=stats, clock=clock, sleeper=clock.advance)
        self.assertEqual((stats.data_packets, stats.retransmits, stats.window_restarts), (12, 8, 1))
        self.assertEqual((stats.bytes_acked, stats.acked_blocks), (0, 0))
        self.assertEqual(sock.sent[:4], sock.sent[4:8])
        self.assertEqual(sock.sent[:4], sock.sent[8:12])

    def test_multi_packet_windows_pace_initial_and_retransmitted_data(self):
        clock = FakeClock()
        sent_at, sleeps = [], []
        class TimedWindow(WindowSocket):
            def sendto(self, data, peer):
                sent_at.append(clock())
                super().sendto(data, peer)
        def sleep(seconds):
            sleeps.append(seconds)
            clock.advance(seconds)
        sock, stats = TimedWindow(drop_data=(2,), clock=clock), host.TransferStats()
        host.transfer(sock, ("192.168.137.30", 49152), io.BytesIO(bytes(8192)),
                      blksize=1024, windowsize=4, stats=stats, clock=clock,
                      inter_packet_seconds=0.0001, sleeper=sleep)
        self.assertTrue(sleeps)
        self.assertGreater(stats.retransmits, 0)
        self.assertTrue(all(right - left >= 0.0001 - 1e-12
                            for left, right in zip(sent_at, sent_at[1:])))
        self.assertAlmostEqual(stats.pacing_seconds, sum(sleeps))
        self.assertIn("pacing=", stats.summary())
        self.assertIn("other=0.000000s", stats.summary())
        for delay in (0, -1, float("nan"), float("inf")):
            with self.subTest(delay=delay), self.assertRaises(ValueError):
                host.transfer(sock, ("192.168.137.30", 49152), io.BytesIO(b"data"),
                              blksize=1024, windowsize=4, inter_packet_seconds=delay)

    def test_window_rollover_with_gap_zero_ack_and_short_eof(self):
        length = 65536 * 1024 + 37
        class Source:
            remaining = length
            reads = 0
            def read(self, size):
                self.reads += 1
                amount = min(self.remaining, size)
                self.remaining -= amount
                return bytes(amount)
        sock = WindowSocket(drop_data=(65535,))
        stats, source = host.TransferStats(), Source()
        self.assertEqual(host.transfer(sock, ("192.168.137.30", 49152), source,
                                       blksize=1024, windowsize=4, stats=stats, clock=sock.clock, sleeper=sock.clock.advance), length)
        self.assertEqual(sock.boundary, [65533, 65534, 65535, 0, 65535, 0, 1])
        self.assertEqual((stats.bytes_acked, stats.acked_blocks, source.reads), (length, 65537, 65537))
        self.assertEqual((stats.retransmits, stats.eof_acked), (2, True))
        self.assertEqual((stats.max_buffered_blocks, stats.max_buffered_bytes), (4, 4 * 1028))

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
                                       TimedSource(bytes(1024)), stats=stats, clock=clock, sleeper=clock.advance), 1024)
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
                          retries=2, stats=stats, clock=clock, sleeper=clock.advance)
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
                               stats=stats, clock=clock, sleeper=clock.advance)
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

    def test_serve_negotiates_requested_options_with_configured_caps(self):
        class ContextSocket(FakeSocket):
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def bind(self, address):
                self.bound = address

        class NegotiatedSession(WindowSocket):
            oack = None
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def bind(self, address):
                self.bound = address
            def sendto(self, data, peer):
                if data.startswith(b"\0\6"):
                    self.oack = data
                    self.replies.append((b"\0\4\0\0", peer))
                else:
                    if self.oack is None:
                        raise AssertionError("DATA before option negotiation")
                    super().sendto(data, peer)

        with tempfile.TemporaryDirectory() as directory:
            source, packed = Path(directory) / "app.bin", Path(directory) / "valence.vld"
            source.write_bytes(bytes(4096))
            host.pack(source, packed)
            listener, session = ContextSocket(), NegotiatedSession(blksize=512, windowsize=2)
            listener.replies = [(b"\0\1valence.vld\0octet\0blksize\x001024\0windowsize\x004\0",
                                 ("192.168.137.30", 49152))]
            output = io.StringIO()
            with patch.object(host.socket, "socket", side_effect=[listener, session]), \
                    patch.object(host.sys, "stdout", output):
                host.serve(packed, "192.168.137.1", once=True, show_progress=False,
                           max_blksize=512, max_windowsize=2)
            self.assertEqual(session.oack, b"\0\6blksize\x00512\0windowsize\x002\0")
            self.assertEqual(session.bound, ("192.168.137.1", 0))
            self.assertEqual((session.bytes_received, session.accepted), (4132, 9))
            self.assertIn("blksize=512 windowsize=2 oack=yes", output.getvalue())
            self.assertIn("eof_acked=yes blksize=512 windowsize=2", output.getvalue())
            self.assertIn("oack_packets=1 oack_retransmits=0", output.getvalue())

if __name__ == "__main__":
    unittest.main()
