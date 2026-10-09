#!/usr/bin/env python3
"""Deterministic host-only TFTP window tests; no board qualification claim.

Run: python3 -B -m unittest discover -s tests -p 'test_window_protocol.py' -v

The independent receiver below follows the relevant DATA/OACK/timeout paths in
the pinned U-Boot net/tftp.c, not the Valence BootROM receiver. In particular,
old duplicate DATA does not cause an immediate ACK or restart its timeout.
U-Boot sends a timeout ACK after five seconds without accepted DATA. On a short
DATA packet it ACKs and completes; this model does not invent a final-ACK dally.
The signed-short unexpected-block comparison is preserved, including around
wrap. This is a focused Python state-machine model, not execution of U-Boot C.

Clock.sleep and socket.recvfrom both advance the same simulated clock and run
the receiver timer. No real socket, sleeps, large fixture, or image is used.
The wrap stream is generated one block at a time and traces stay bounded.
"""

from collections import Counter, deque
import hashlib
import heapq
from pathlib import Path
import socket
import struct
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import netboot_host as tftp


PEER = ("192.0.2.30", 41000)
FOREIGN_IP = ("192.0.2.31", PEER[1])
FOREIGN_TID = (PEER[0], PEER[1] + 1)
PACE = 0.0001
LATENCY = 0.001


def ack(block):
    return struct.pack("!HH", 4, block & 0xffff)


def rrq(*options):
    fields = [b"Image", b"octet"]
    for key, value in options:
        fields.extend((str(key).encode("ascii"), str(value).encode("ascii")))
    return b"\0\1" + b"\0".join(fields) + b"\0"


class Clock:
    """One replaceable receiver timer, plus a bounded queue of wire events."""

    def __init__(self):
        self.now = 0.0
        self.events = []
        self.serial = 0
        self.receiver = None

    def __call__(self):
        return self.now

    def schedule(self, delay, callback):
        assert delay >= 0
        self.serial += 1
        heapq.heappush(self.events, (self.now + delay, self.serial, callback))

    def next_event(self):
        event = self.events[0][0] if self.events else float("inf")
        timer = self.receiver.deadline if self.receiver else None
        return min(event, timer if timer is not None else float("inf"))

    def advance(self, target):
        assert target >= self.now
        while self.next_event() <= target:
            self.now = self.next_event()
            if (self.receiver is not None and self.receiver.deadline is not None
                    and self.receiver.deadline <= self.now):
                self.receiver.timeout()
            while self.events and self.events[0][0] <= self.now:
                _, _, callback = heapq.heappop(self.events)
                callback()
        self.now = target

    def sleep(self, duration):
        self.advance(self.now + duration)


class GeneratedStream:
    """One-pass stream with a logical block stamp; retains at most one block."""

    def __init__(self, size, blksize):
        self.size = size
        self.blksize = blksize
        self.remaining = size
        self.reads = 0
        self.max_read = 0
        self.digest = hashlib.sha256()

    def read(self, requested):
        assert requested == self.blksize
        self.reads += 1
        self.max_read = max(self.max_read, requested)
        count = min(requested, self.remaining)
        self.remaining -= count
        stamp = self.reads.to_bytes(8, "little")
        result = (stamp * ((count + 7) // 8))[:count]
        self.digest.update(result)
        return result


class UBootReceiver:
    """Small independent model of the pinned U-Boot receive control flow."""

    def __init__(self, clock, size, blksize, windowsize, ack_policy=None):
        self.clock = clock
        clock.receiver = self
        self.size = size
        self.blksize = blksize
        self.windowsize = windowsize
        self.current = 0
        self.logical = 0
        self.next_ack = windowsize
        self.last_nack = 0  # tftp_start initializes this to zero.
        self.deadline = 5.0
        self.done = False
        self.bytes = 0
        self.digest = hashlib.sha256()
        self.old_duplicates = 0
        self.gaps = 0
        self.ack_reasons = Counter()
        self.ack_trace = deque(maxlen=96)
        self.wrap_trace = []
        self.ack_policy = ack_policy
        self.sock = None

    def emit_ack(self, reason):
        self.ack_reasons[reason] += 1
        self.ack_trace.append((self.logical, self.current, reason, self.clock()))
        self.sock.trace.append((self.clock(), "ACK " + reason, self.logical))
        deliveries = ([(LATENCY, ack(self.current), PEER)] if self.ack_policy is None
                      else self.ack_policy(self, reason))
        for delay, packet, peer in deliveries:
            self.sock.inject(packet, peer, delay)

    def timeout(self):
        assert not self.done
        self.deadline = self.clock() + 5.0
        self.emit_ack("timeout")

    def receive(self, packet):
        if self.done:
            return  # net_set_state(NETLOOP_SUCCESS), no invented dally.
        if packet[:2] == b"\0\6":
            fields = packet[2:].split(b"\0")
            options = dict(zip(fields[::2], fields[1::2]))
            assert int(options.get(b"blksize", b"512")) == self.blksize
            assert int(options.get(b"windowsize", b"1")) == self.windowsize
            self.next_ack = self.windowsize
            self.emit_ack("oack")
            return
        assert len(packet) >= 4 and packet[:2] == b"\0\3"
        wire = int.from_bytes(packet[2:4], "big")
        expected = (self.current + 1) & 0xffff
        if wire != expected:
            # Exactly the ushort(expected) - short(received) comparison used
            # in the pinned C, rather than a repaired modular comparison.
            signed_wire = wire if wire < 0x8000 else wire - 0x10000
            if expected - signed_wire > 0:
                self.old_duplicates += 1
                return
            self.gaps += 1
            if self.last_nack != self.current:
                self.emit_ack("gap")
                self.last_nack = self.current
                self.next_ack = (self.current + self.windowsize) & 0xffff
            return
        self.current = expected
        self.logical += 1
        payload = packet[4:]
        wanted = min(self.blksize, self.size - self.bytes)
        stamp = struct.pack("<Q", self.logical)
        assert payload == (stamp * ((wanted + 7) // 8))[:wanted], (
            "wrong, reordered or reread DATA", self.logical, len(payload), wanted)
        self.bytes += len(payload)
        self.digest.update(payload)
        self.deadline = self.clock() + 5.0
        if 65533 <= self.logical <= 65540:
            self.wrap_trace.append((self.logical, wire))
        if len(payload) < self.blksize:
            self.emit_ack("final")
            self.done = True
            self.deadline = None
        elif self.current == self.next_ack:
            self.emit_ack("window")
            self.next_ack = (self.next_ack + self.windowsize) & 0xffff


class FakeSocket:
    def __init__(self, clock, receiver=None, drop_data=None, on_send=None):
        self.clock = clock
        self.receiver = receiver
        if receiver:
            receiver.sock = self
        self.drop_data = dict(drop_data or {})
        self.on_send = on_send
        self.pending = deque()
        self.timeout_seconds = None
        self.trace = deque(maxlen=128)
        self.data_count = self.oack_count = 0
        self.first_data_time = None
        self.min_burst_spacing = float("inf")
        self.last_data_time = None
        self.recv_calls = 0

    def inject(self, packet, peer=PEER, delay=0):
        self.clock.schedule(delay, lambda: self.pending.append((packet, peer)))

    def settimeout(self, value):
        assert value > 0
        self.timeout_seconds = value

    def sendto(self, packet, peer):
        assert peer == PEER
        if packet[:2] == b"\0\6":
            self.oack_count += 1
            self.trace.append((self.clock(), "OACK", self.oack_count))
        else:
            assert len(packet) >= 4 and packet[:2] == b"\0\3"
            self.data_count += 1
            if self.first_data_time is None:
                self.first_data_time = self.clock()
            if self.last_data_time is not None:
                self.min_burst_spacing = min(self.min_burst_spacing,
                                             self.clock() - self.last_data_time)
            self.last_data_time = self.clock()
            wire = int.from_bytes(packet[2:4], "big")
            self.trace.append((self.clock(), "DATA", wire))
            if self.drop_data.get(wire, 0):
                self.drop_data[wire] -= 1
                self.trace.append((self.clock(), "DROP DATA", wire))
                return len(packet)
        if self.on_send:
            self.on_send(self, packet)
        if self.receiver:
            self.receiver.receive(packet)
        return len(packet)

    def recvfrom(self, size):
        assert self.timeout_seconds is not None
        # Receiving ACKs separates DATA send bursts. Pacing applies inside
        # each original/retransmitted burst, never across an ACK boundary.
        self.last_data_time = None
        self.recv_calls += 1
        assert self.recv_calls < 1_000_000, "non-progressing ACK loop"
        limit = self.clock() + self.timeout_seconds
        while not self.pending:
            next_event = self.clock.next_event()
            if next_event > limit:
                self.clock.advance(limit)
                raise socket.timeout()
            self.clock.advance(next_event)
        packet, peer = self.pending.popleft()
        return packet[:size], peer


class WindowProtocolTests(unittest.TestCase):
    def run_transfer(self, size, window, block=1024, *, drop_data=None,
                     ack_policy=None, on_send=None, oack=True, retries=10,
                     request=None):
        clock = Clock()
        source = GeneratedStream(size, block)
        receiver = UBootReceiver(clock, size, block, window, ack_policy)
        sock = FakeSocket(clock, receiver, drop_data, on_send)
        stats = tftp.TransferStats()
        updates = []

        def progress(total, complete):
            self.assertLessEqual(total, receiver.bytes)
            self.assertLessEqual(total, size)
            if updates:
                self.assertGreaterEqual(total, updates[-1][0])
            updates.append((total, complete))

        if request is None:
            request = tftp.parse_request(rrq(("blksize", block), ("windowsize", window)),
                                         max_windowsize=window)
        self.assertEqual((request.blksize, request.windowsize), (block, window))
        result = tftp.transfer(sock, PEER, source, stats=stats, progress=progress,
                               clock=clock, sleeper=clock.sleep, retry_seconds=1,
                               retries=retries, blksize=block, windowsize=window,
                               oack=request.oack if oack else None,
                               inter_packet_seconds=PACE)
        self.assertEqual(result, size)
        self.assertEqual(stats.bytes_acked, size)
        self.assertTrue(stats.eof_acked)
        self.assertEqual(receiver.bytes, size)
        self.assertTrue(receiver.done)
        self.assertEqual(receiver.digest.digest(), source.digest.digest())
        self.assertEqual(source.reads, size // block + 1)
        self.assertEqual(stats.acked_blocks, source.reads)
        self.assertLessEqual(stats.max_buffered_blocks, window)
        self.assertLessEqual(stats.max_buffered_bytes, window * (block + 4))
        self.assertEqual(updates[-1], (size, True))
        self.assertEqual(sum(complete for _, complete in updates), 1)
        if window > 1 and sock.data_count > 1:
            self.assertGreaterEqual(sock.min_burst_spacing + 1e-10, PACE)
        return clock, source, receiver, sock, stats, updates

    def test_cumulative_windows_two_and_four(self):
        for window in (2, 4):
            with self.subTest(window=window):
                size = 9 * 1024 + 23
                _, _, receiver, _, stats, updates = self.run_transfer(size, window)
                acknowledged = list(range(window, 10, window)) + [10]
                self.assertEqual([entry[0] for entry in receiver.ack_trace
                                  if entry[2] != "oack"], acknowledged)
                self.assertEqual([n for n, _ in updates],
                                 [min(n * 1024, size) for n in acknowledged])
                self.assertEqual(stats.data_packets, 10)
                self.assertEqual(stats.windows_sent, (10 + window - 1) // window)
                self.assertEqual(stats.retransmits, 0)
                self.assertEqual(stats.timeouts, 0)

    def test_lost_data_at_each_window_position(self):
        for window in (2, 4):
            for dropped in range(1, window + 1):
                with self.subTest(window=window, dropped=dropped):
                    _, _, receiver, sock, stats, _ = self.run_transfer(
                        3 * window * 1024 + 19, window, drop_data={dropped: 1})
                    self.assertEqual(sock.drop_data[dropped], 0)
                    self.assertGreater(stats.retransmits, 0)
                    if 1 < dropped < window:
                        self.assertGreater(receiver.ack_reasons["gap"], 0)
                        self.assertGreater(stats.window_restarts, 0)
                    else:
                        self.assertGreater(stats.timeouts, 0)

    def test_lost_window_ack_waits_for_uboot_timeout(self):
        for window in (2, 4):
            with self.subTest(window=window):
                dropped = []

                def policy(receiver, reason):
                    if reason == "window" and receiver.logical == window and not dropped:
                        dropped.append(receiver.clock())
                        return []
                    return [(LATENCY, ack(receiver.current), PEER)]

                clock, _, receiver, _, stats, _ = self.run_transfer(
                    3 * window * 1024 + 7, window, ack_policy=policy)
                self.assertEqual(len(dropped), 1)
                self.assertGreaterEqual(clock(), dropped[0] + 5.0)
                self.assertGreaterEqual(receiver.old_duplicates, 4 * window)
                self.assertEqual(receiver.ack_reasons["timeout"], 1)
                self.assertGreaterEqual(stats.timeouts, 4)
                self.assertGreaterEqual(stats.retransmits, 4 * window)
                first_timeout = next(row for row in receiver.ack_trace if row[2] == "timeout")
                self.assertAlmostEqual(first_timeout[3], dropped[0] + 5.0)

    def test_delayed_window_ack_does_not_imply_duplicate_data_ack(self):
        for window in (2, 4):
            with self.subTest(window=window):
                def policy(receiver, reason):
                    delay = 1.25 if reason == "window" and receiver.logical == window else LATENCY
                    return [(delay, ack(receiver.current), PEER)]

                clock, _, receiver, _, stats, _ = self.run_transfer(
                    3 * window * 1024 + 9, window, ack_policy=policy)
                self.assertGreaterEqual(clock(), 1.25)
                self.assertEqual(stats.timeouts, 1)
                self.assertEqual(stats.retransmits, window)
                self.assertEqual(receiver.old_duplicates, window)
                self.assertEqual(receiver.ack_reasons["timeout"], 0)

    def test_duplicate_and_stale_acks_cannot_double_credit(self):
        for window in (2, 4):
            with self.subTest(window=window):
                def policy(receiver, reason):
                    packets = [(LATENCY, ack(receiver.current), PEER)]
                    if reason == "window" and receiver.logical == window:
                        packets += [(LATENCY + i * 0.00001, ack(receiver.current), PEER)
                                    for i in range(1, 4)]
                        packets.append((LATENCY + 0.00004, ack(window - 1), PEER))
                    return packets

                _, _, _, _, stats, _ = self.run_transfer(
                    4 * window * 1024 + 11, window, ack_policy=policy)
                self.assertGreater(stats.ignored_packets, 0)
                self.assertLessEqual(stats.window_restarts, 1)
                self.assertLessEqual(stats.retransmits, window)

    def test_short_tail_and_exact_multiple_need_eof_ack(self):
        for window in (2, 4):
            for size in (0, 1, 511, 512, 513, window * 512, window * 512 + 17):
                with self.subTest(window=window, size=size):
                    _, _, receiver, _, stats, _ = self.run_transfer(size, window, block=512)
                    self.assertEqual(receiver.ack_reasons["final"], 1)
                    self.assertEqual(stats.data_packets, size // 512 + 1)

    def test_wrap_stream_retains_one_window(self):
        for window in (2, 4):
            with self.subTest(window=window):
                block = 1024
                size = (65536 + 7) * block + 17
                _, source, receiver, _, stats, _ = self.run_transfer(size, window, block=block)
                self.assertEqual(receiver.wrap_trace,
                                 [(n, n & 0xffff) for n in range(65533, 65541)])
                self.assertTrue(any(logical == 65536 and wire == 0 and reason == "window"
                                    for logical, wire, reason, _ in receiver.ack_trace))
                self.assertEqual(source.max_read, block)
                self.assertEqual(stats.data_packets, 65544)
                self.assertEqual(stats.retransmits, 0)

    def test_lost_data_at_wrap_recovers_without_invented_gap_ack(self):
        # U-Boot's actual signed-short comparison suppresses a gap ACK here.
        # Recovery must come from server timeout/retransmission, not a model
        # that silently replaces the comparison with ideal modular ordering.
        for dropped in (65535, 0):
            with self.subTest(dropped=dropped):
                _, _, receiver, sock, stats, _ = self.run_transfer(
                    (65536 + 3) * 512 + 19, 4, block=512, drop_data={dropped: 1})
                self.assertEqual(sock.drop_data[dropped], 0)
                self.assertGreater(stats.timeouts, 0)
                self.assertGreater(stats.retransmits, 0)
                self.assertEqual(receiver.ack_reasons["gap"], 0)

    def test_negotiation_never_increases_requested_window(self):
        for cap in (2, 4):
            for requested in (1, 2, 4, 16):
                with self.subTest(cap=cap, requested=requested):
                    parsed = tftp.parse_request(rrq(("blksize", 1024),
                                                     ("windowsize", requested)),
                                                max_windowsize=cap)
                    self.assertEqual(parsed.windowsize, min(cap, requested))
                    self.assertEqual(dict(parsed.options)["windowsize"], min(cap, requested))

    def test_foreign_peer_tid_and_malformed_acks_are_ignored(self):
        injected = []

        def policy(receiver, reason):
            if reason == "window" and not injected:
                invalid = [(ack(receiver.current), FOREIGN_IP),
                           (ack(receiver.current), FOREIGN_TID),
                           (b"\0\5\0\1foreign error\0", FOREIGN_TID),
                           (b"\0\4", PEER), (ack(receiver.current) + b"x", PEER),
                           (b"\0\3\0\1", PEER), (ack(60000), PEER)]
                injected.extend(invalid)
                return [(i * 0.00001, packet, peer) for i, (packet, peer) in enumerate(invalid)] + [
                    (LATENCY, ack(receiver.current), PEER)]
            return [(LATENCY, ack(receiver.current), PEER)]

        _, _, _, _, stats, _ = self.run_transfer(8 * 1024 + 3, 4, ack_policy=policy)
        self.assertEqual(stats.ignored_packets, len(injected))
        self.assertEqual(stats.timeouts, 0)
        self.assertEqual(stats.retransmits, 0)

    def test_oack_retries_before_any_source_read_or_data(self):
        clock = Clock()
        source = GeneratedStream(1025, 1024)
        receiver = UBootReceiver(clock, source.size, 1024, 4)

        def policy(receiver, reason):
            if reason == "oack" and receiver.sock.oack_count == 1:
                self.assertEqual(source.reads, 0)
                return [(0.1, ack(1), PEER), (0.2, ack(0), FOREIGN_TID),
                        (0.3, ack(0) + b"junk", PEER)]
            return [(LATENCY, ack(receiver.current), PEER)]

        receiver.ack_policy = policy

        def on_send(sock, packet):
            if packet[:2] == b"\0\6":
                self.assertEqual(source.reads, 0)
                self.assertEqual(sock.data_count, 0)

        sock = FakeSocket(clock, receiver, on_send=on_send)
        stats = tftp.TransferStats()
        options = tftp.parse_request(rrq(("blksize", 1024), ("windowsize", 4))).oack
        result = tftp.transfer(sock, PEER, source, clock=clock, sleeper=clock.sleep,
                               stats=stats, blksize=1024, windowsize=4, oack=options)
        self.assertEqual(result, source.size)
        self.assertEqual(stats.oack_packets, 2)
        self.assertEqual(stats.oack_retransmits, 1)
        self.assertEqual(stats.timeouts, 1)
        self.assertEqual(stats.ignored_packets, 3)
        self.assertGreaterEqual(sock.first_data_time, 1.0 + LATENCY)

    def test_oack_exhaustion_never_reads_or_sends_data(self):
        clock = Clock()
        source = GeneratedStream(1025, 1024)
        sock = FakeSocket(clock)
        stats = tftp.TransferStats()
        options = tftp.parse_request(rrq(("blksize", 1024), ("windowsize", 4))).oack
        with self.assertRaisesRegex(TimeoutError, "ACK0"):
            tftp.transfer(sock, PEER, source, clock=clock, sleeper=clock.sleep,
                          stats=stats, blksize=1024, windowsize=4,
                          oack=options, retries=3)
        self.assertEqual(source.reads, 0)
        self.assertEqual(sock.data_count, 0)
        self.assertEqual(stats.oack_packets, 3)
        self.assertEqual(stats.oack_retransmits, 2)
        self.assertEqual(stats.timeouts, 3)
        self.assertAlmostEqual(clock(), 3.0)

    def test_no_windowsize_rrq_falls_back_to_one(self):
        for options in ((), (("blksize", 1024), ("timeout", 5), ("tsize", 0))):
            with self.subTest(options=options):
                request = tftp.parse_request(rrq(*options), max_windowsize=4)
                self.assertEqual(request.windowsize, 1)
                self.assertNotIn("windowsize", dict(request.options))
                self.assertEqual(request.oack is None, not options)
                _, _, receiver, _, stats, _ = self.run_transfer(
                    5 * request.blksize + 7, request.windowsize,
                    block=request.blksize, oack=bool(options), request=request)
                self.assertEqual(stats.max_buffered_blocks, 1)
                self.assertEqual([row[0] for row in receiver.ack_trace if row[2] != "oack"],
                                 list(range(1, 7)))

    def test_noise_does_not_extend_receive_deadline(self):
        clock = Clock()
        source = GeneratedStream(10 * 512, 512)
        sock = FakeSocket(clock)
        for i in range(1, 41):
            sock.inject(b"\0\4bad length", delay=i * 0.1)
        stats = tftp.TransferStats()
        with self.assertRaises(TimeoutError):
            tftp.transfer(sock, PEER, source, clock=clock, sleeper=clock.sleep,
                          stats=stats, windowsize=4, retries=2)
        self.assertEqual(stats.timeouts, 2)
        self.assertEqual(stats.data_packets, 8)
        self.assertEqual(stats.bytes_acked, 0)
        self.assertGreater(stats.ignored_packets, 0)
        self.assertGreaterEqual(clock(), 2.0)
        self.assertLess(clock(), 2.01)

    def test_duplicate_base_ack_can_fast_restart_only_once(self):
        clock = Clock()
        source = GeneratedStream(10 * 512, 512)
        sock = FakeSocket(clock)
        for i in range(1, 31):
            sock.inject(ack(0), delay=i * 0.01)
        stats = tftp.TransferStats()
        with self.assertRaises(TimeoutError):
            tftp.transfer(sock, PEER, source, clock=clock, sleeper=clock.sleep,
                          stats=stats, windowsize=4, retries=2)
        self.assertEqual(stats.window_restarts, 1)
        self.assertEqual(stats.windows_sent, 2)
        self.assertEqual(stats.bytes_acked, 0)
        self.assertGreater(stats.ignored_packets, 0)
        self.assertGreaterEqual(clock(), 1.0)
        self.assertLess(clock(), 1.02)

    def test_lost_final_ack_is_not_falsely_reported_as_success(self):
        clock = Clock()
        source = GeneratedStream(1025, 1024)

        def policy(receiver, reason):
            return [] if reason == "final" else [(LATENCY, ack(receiver.current), PEER)]

        receiver = UBootReceiver(clock, source.size, 1024, 4, policy)
        sock = FakeSocket(clock, receiver)
        stats = tftp.TransferStats()
        with self.assertRaises(TimeoutError):
            tftp.transfer(sock, PEER, source, clock=clock, sleeper=clock.sleep,
                          stats=stats, blksize=1024, windowsize=4, retries=3)
        self.assertTrue(receiver.done)
        self.assertEqual(receiver.bytes, source.size)
        self.assertFalse(stats.eof_acked)
        self.assertEqual(stats.bytes_acked, 0)
        self.assertEqual(receiver.ack_reasons["final"], 1)
        self.assertEqual(receiver.ack_reasons["timeout"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
