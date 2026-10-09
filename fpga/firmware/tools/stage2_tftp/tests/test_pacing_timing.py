"""Small host-only pacing/timer regressions; no Windows or board speed claim.

The deterministic peer ACKs a complete send burst or raises a scheduled
timeout. Existing test_window_protocol.py independently models U-Boot's
recovery behavior. Real UDP below checks both pacing modes with a tiny file.
"""
import contextlib
import inspect
import io
import json
import math
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import netboot_host as engine
import stage2_tftp as stage2

PEER = ('192.0.2.30', 41000)
PACE = 0.0001


class Clock:
    def __init__(self):
        self.now = 0.0
        self.calls = 0
        self.sleeps = []
        self.sleep_step = None

    def __call__(self):
        self.calls += 1
        assert self.calls <= 2000, 'clock polling/busy wait must be bounded'
        return self.now

    def sleep(self, duration):
        assert duration > 0
        self.sleeps.append((self.now, duration))
        self.now += duration if self.sleep_step is None else self.sleep_step


class Source(io.BytesIO):
    def __init__(self, payload):
        super().__init__(payload)
        self.reads = 0

    def read(self, size):
        self.reads += 1
        return super().read(size)


class PeerSocket:
    """Records DATA byte-for-byte; every recv marks an explicit burst boundary."""
    def __init__(self, clock, *, ack_delay=0, first_timeout=False):
        self.clock = clock
        self.ack_delay = ack_delay
        self.first_timeout = first_timeout
        self.timeout = None
        self.sent = []
        self.received_at = []
        self.receives = 0

    def settimeout(self, duration):
        assert duration > 0
        self.timeout = duration

    def sendto(self, packet, peer):
        assert peer == PEER
        self.sent.append((self.clock.now, bytes(packet)))
        return len(packet)

    def recvfrom(self, size):
        self.receives += 1
        assert self.receives <= 100, 'non-progressing ACK loop'
        if self.first_timeout and self.receives == 1:
            self.clock.now += self.timeout
            self.received_at.append(self.clock.now)
            raise socket.timeout()
        self.clock.now += self.ack_delay
        self.received_at.append(self.clock.now)
        packet = self.sent[-1][1]
        block = 0 if packet[:2] == b'\0\6' else int.from_bytes(packet[2:4], 'big')
        return struct.pack('!HH', 4, block), PEER


class PacingTests(unittest.TestCase):
    def run_transfer(self, packets=9, window=4, delay=PACE, *, ack_delay=0,
                     first_timeout=False, sleep_step=None, forbid_sleep=False):
        payload = bytes((index % 251 for index in range((packets - 1) * 512 + 17)))
        source, clock = Source(payload), Clock()
        clock.sleep_step = sleep_step
        sock = PeerSocket(clock, ack_delay=ack_delay, first_timeout=first_timeout)
        stats = engine.TransferStats()
        sleeper = mock.Mock(side_effect=AssertionError('unexpected sleep')) if forbid_sleep else clock.sleep
        result = engine.transfer(sock, PEER, source, clock=clock, sleeper=sleeper,
                                 stats=stats, windowsize=window,
                                 inter_packet_seconds=delay, retries=3)
        self.assertEqual(result, len(payload))
        self.assertEqual(stats.bytes_acked, len(payload))
        self.assertEqual(stats.acked_blocks, packets)
        self.assertTrue(stats.eof_acked)
        self.assertEqual(source.reads, packets)
        self.assertLessEqual(stats.max_buffered_blocks, window)
        self.assertLessEqual(stats.max_buffered_bytes, window * 516)
        if forbid_sleep:
            sleeper.assert_not_called()
        return clock, source, sock, stats

    def test_zero_delay_never_sleeps_for_any_window(self):
        for window in (1, 2, 4, 16):
            with self.subTest(window=window):
                clock, _, sock, stats = self.run_transfer(window=window, delay=0, forbid_sleep=True)
                self.assertEqual(stats.pacing_seconds, 0)
                self.assertEqual(stats.data_packets, 9)
                self.assertEqual(stats.windows_sent, math.ceil(9 / window))
                self.assertEqual([when for when, _ in sock.sent], [0] * 9)
                self.assertLess(clock.calls, 200)

    def test_window_one_never_sleeps_with_positive_default_delay(self):
        _, _, _, stats = self.run_transfer(window=1, forbid_sleep=True)
        self.assertEqual(stats.pacing_seconds, 0)
        self.assertEqual(stats.windows_sent, 9)

    def test_exact_positive_sleep_count_and_no_initial_trailing_or_cross_window_delay(self):
        for window in (2, 4, 16):
            for packets in (1, 2, 4, 5, 8, 9, 11):
                with self.subTest(window=window, packets=packets):
                    clock, _, sock, stats = self.run_transfer(packets, window)
                    pauses = packets - math.ceil(packets / window)
                    self.assertEqual(len(clock.sleeps), pauses)
                    for _, duration in clock.sleeps:
                        self.assertAlmostEqual(duration, PACE, places=12)
                    for index, (when, _) in enumerate(sock.sent):
                        # Each full window consumes window-1 delays. Its next
                        # first packet follows the zero-latency ACK immediately.
                        expected = (index - index // window) * PACE
                        self.assertAlmostEqual(when, expected, places=12)
                    self.assertEqual(sock.sent[0][0], 0)
                    self.assertAlmostEqual(clock.now, sock.sent[-1][0], places=12)
                    self.assertAlmostEqual(stats.pacing_seconds, pauses * PACE, places=12)
                    self.assertAlmostEqual(stats.elapsed_seconds, pauses * PACE, places=12)

    def test_ack_wait_longer_than_spacing_does_not_add_boundary_sleep(self):
        clock, _, sock, stats = self.run_transfer(9, 4, ack_delay=0.002)
        self.assertEqual(len(clock.sleeps), 6)
        for sent_index, ack_index in ((4, 0), (8, 1)):
            self.assertAlmostEqual(sock.sent[sent_index][0], sock.received_at[ack_index], places=12)
        self.assertAlmostEqual(stats.ack_wait_seconds, 0.006, places=12)
        self.assertAlmostEqual(stats.elapsed_seconds, 0.0066, places=12)

    def test_retransmitted_window_is_retained_and_first_packet_has_no_delay(self):
        for delay in (0, PACE):
            with self.subTest(delay=delay):
                clock, _, sock, stats = self.run_transfer(9, 4, delay=delay,
                                                        first_timeout=True,
                                                        forbid_sleep=delay == 0)
                self.assertEqual([packet for _, packet in sock.sent[:4]],
                                 [packet for _, packet in sock.sent[4:8]])
                self.assertEqual([int.from_bytes(packet[2:4], 'big') for _, packet in sock.sent],
                                 [1, 2, 3, 4, 1, 2, 3, 4, 5, 6, 7, 8, 9])
                self.assertAlmostEqual(sock.sent[4][0], sock.received_at[0], places=12)
                self.assertEqual(stats.retransmits, 4)
                self.assertEqual(stats.timeouts, 1)
                self.assertEqual(stats.windows_sent, 4)
                self.assertEqual(len(clock.sleeps), 9 if delay else 0)

    def test_coarse_oversleep_is_measured_once_per_gap_without_busy_wait(self):
        clock, _, sock, stats = self.run_transfer(9, 4, sleep_step=0.015625)
        self.assertEqual(len(clock.sleeps), 6)
        self.assertLess(clock.calls, 200)
        self.assertAlmostEqual(stats.pacing_seconds, 6 * 0.015625, places=12)
        self.assertAlmostEqual(stats.elapsed_seconds, 6 * 0.015625, places=12)
        self.assertEqual(sock.sent[4][0], sock.sent[3][0])
        self.assertEqual(sock.sent[8][0], sock.sent[7][0])

    def test_sleep_return_without_clock_progress_does_not_spin(self):
        # A deliberately pathological injected sleeper must not trigger a
        # high-CPU busy wait; accurate spacing relies on the sleeper/clock pair.
        clock, _, _, stats = self.run_transfer(9, 4, sleep_step=0)
        self.assertEqual(len(clock.sleeps), 6)
        self.assertLess(clock.calls, 200)
        self.assertEqual(stats.pacing_seconds, 0)

    def test_invalid_delay_rejected_before_any_read_send_or_sleep(self):
        for delay in (-1, -1e-12, float('nan'), float('inf'), -float('inf')):
            source, sock, sleeper = mock.Mock(), mock.Mock(), mock.Mock()
            with self.subTest(delay=delay), self.assertRaises(ValueError):
                engine.transfer(sock, PEER, source, inter_packet_seconds=delay, sleeper=sleeper)
            source.read.assert_not_called()
            sock.sendto.assert_not_called()
            sleeper.assert_not_called()

    def test_default_window_and_delay_remain_conservative(self):
        self.assertEqual(inspect.signature(stage2.serve).parameters['max_windowsize'].default, 1)
        self.assertEqual(inspect.signature(stage2.serve).parameters['packet_delay_us'].default, 100)
        self.assertEqual(inspect.signature(engine.transfer).parameters['windowsize'].default, 1)
        self.assertEqual(inspect.signature(engine.transfer).parameters['inter_packet_seconds'].default, PACE)


class HighResolutionTimingTests(unittest.TestCase):
    def test_counter_nanoseconds_convert_to_seconds(self):
        with mock.patch.object(engine.time, 'perf_counter_ns', return_value=1234567890123) as counter, \
             mock.patch.object(engine.time, 'monotonic', return_value=0) as coarse:
            self.assertEqual(engine.high_resolution_time(), 1234.567890123)
        counter.assert_called_once_with()
        coarse.assert_not_called()

    def test_default_transfer_measures_sub_tick_read_send_wait_and_elapsed(self):
        now = [0]
        class TimedSource(Source):
            def read(self, size):
                now[0] += 17000
                return super().read(size)
        class TimedSocket:
            def sendto(self, packet, peer):
                now[0] += 23000
                self.last = int.from_bytes(packet[2:4], 'big')
                return len(packet)
            def settimeout(self, duration): pass
            def recvfrom(self, size):
                now[0] += 31000
                return struct.pack('!HH', 4, self.last), PEER
        stats = engine.TransferStats()
        with mock.patch.object(engine.time, 'perf_counter_ns', side_effect=lambda: now[0]), \
             mock.patch.object(engine.time, 'monotonic', return_value=0) as coarse, \
             mock.patch.object(engine.time, 'sleep', side_effect=AssertionError('unexpected sleep')):
            self.assertEqual(engine.transfer(TimedSocket(), PEER, TimedSource(b'x' * 1025),
                                             windowsize=2, inter_packet_seconds=0, stats=stats), 1025)
        coarse.assert_not_called()
        self.assertAlmostEqual(stats.read_seconds, 3 * 17e-6, places=12)
        self.assertAlmostEqual(stats.send_seconds, 3 * 23e-6, places=12)
        self.assertAlmostEqual(stats.ack_wait_seconds, 2 * 31e-6, places=12)
        self.assertAlmostEqual(stats.elapsed_seconds, 182e-6, places=12)
        self.assertEqual(stats.pacing_seconds, 0)

    def test_default_progress_uses_sub_tick_counter(self):
        now, output = [0], io.StringIO()
        with mock.patch.object(engine.time, 'perf_counter_ns', side_effect=lambda: now[0]), \
             mock.patch.object(engine.time, 'monotonic', return_value=0) as coarse:
            progress = engine.TransferProgress(1024, stream=output)
            now[0] = 1000000
            progress.update(1024, complete=True)
        coarse.assert_not_called()
        self.assertIn('0.977 MiB/s', output.getvalue())
        self.assertTrue(progress.closed)

    def test_default_deadlines_expire_with_coarse_monotonic_frozen(self):
        for use_oack in (False, True):
            now, calls = [0], [0]
            class NoisySocket:
                def settimeout(self, duration): pass
                def sendto(self, packet, peer): return len(packet)
                def recvfrom(self, size):
                    calls[0] += 1
                    assert calls[0] <= 4, 'deadline failed to advance'
                    now[0] += 200000000
                    return b'malformed', PEER
            stats, source = engine.TransferStats(), Source(b'x')
            with self.subTest(oack=use_oack), \
                 mock.patch.object(engine.time, 'perf_counter_ns', side_effect=lambda: now[0]), \
                 mock.patch.object(engine.time, 'monotonic', return_value=0) as coarse, \
                 self.assertRaises(TimeoutError):
                engine.transfer(NoisySocket(), PEER, source, retry_seconds=0.5, retries=1,
                                inter_packet_seconds=0, stats=stats,
                                oack=b'\x00\x06blksize\x00512\x00' if use_oack else None)
            coarse.assert_not_called()
            self.assertEqual(calls[0], 3)
            self.assertEqual(stats.ignored_packets, 3)
            self.assertEqual(stats.timeouts, 1)
            self.assertEqual(source.reads, 0 if use_oack else 1)
            self.assertAlmostEqual(stats.elapsed_seconds, 0.6, places=12)


class RealUdpPacingTests(unittest.TestCase):
    def test_small_stage2_localhost_transfer_zero_and_positive_pacing(self):
        payload = bytes(range(251)) * 21
        comparison = []
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            files = {'Image': folder / 'Image', 'valence-vl100.dtb': folder / 'valence-vl100.dtb'}
            files['Image'].write_bytes(payload)
            files['valence-vl100.dtb'].write_bytes(b'synthetic test DTB')
            for delay in (0, 100):
                output, errors, ready = io.StringIO(), [], threading.Event()
                original_socket, original_transfer = socket.socket, engine.transfer
                listener = original_socket(socket.AF_INET, socket.SOCK_DGRAM)
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
                client = original_socket(socket.AF_INET, socket.SOCK_DGRAM)
                client.settimeout(3)
                count = [0]
                class Prebound:
                    def __init__(self, sock): self.sock = sock
                    def __getattr__(self, name): return getattr(self.sock, name)
                    def __enter__(self): return self
                    def __exit__(self, *args): self.sock.close()
                    def bind(self, address): ready.set()
                def factory(*args, **kwargs):
                    count[0] += 1
                    return Prebound(listener) if count[0] == 1 else original_socket(*args, **kwargs)
                def run():
                    try:
                        stage2.serve(files, '127.0.0.1', '127.0.0.1', port, once=True,
                                     max_windowsize=4, packet_delay_us=delay)
                    except BaseException as error:
                        errors.append(error)
                with self.subTest(packet_delay_us=delay), client, \
                     contextlib.redirect_stdout(output), \
                     mock.patch.object(stage2.socket, 'socket', side_effect=factory), \
                     mock.patch.object(engine, 'transfer', wraps=original_transfer) as transfer:
                    worker = threading.Thread(target=run, daemon=True)
                    worker.start()
                    self.assertTrue(ready.wait(3), repr(errors))
                    client.sendto(b'\x00\x01Image\x00octet\x00blksize\x00512\x00windowsize\x004\x00',
                                  ('127.0.0.1', port))
                    got, expected, since_ack, oacks = bytearray(), 1, 0, 0
                    while True:
                        packet, peer = client.recvfrom(2048)
                        if packet[:2] == b'\0\6':
                            oacks += 1
                            self.assertEqual(packet, b'\x00\x06blksize\x00512\x00windowsize\x004\x00')
                            client.sendto(struct.pack('!HH', 4, 0), peer)
                            continue
                        self.assertEqual(packet[:2], b'\0\3')
                        self.assertEqual(int.from_bytes(packet[2:4], 'big'), expected)
                        got.extend(packet[4:])
                        since_ack += 1
                        eof = len(packet) < 516
                        if since_ack == 4 or eof:
                            client.sendto(struct.pack('!HH', 4, expected), peer)
                            since_ack = 0
                        expected += 1
                        if eof:
                            break
                    worker.join(3)
                    self.assertFalse(worker.is_alive())
                    self.assertEqual(errors, [])
                    self.assertEqual(bytes(got), payload)
                    self.assertEqual(oacks, 1)
                    self.assertEqual(transfer.call_args.kwargs['inter_packet_seconds'], delay / 1e6)
                    stats = transfer.call_args.kwargs['stats']
                    self.assertEqual(stats.bytes_acked, len(payload))
                    self.assertEqual(stats.data_packets, 11)
                    self.assertEqual(stats.windows_sent, 3)
                    self.assertEqual(stats.retransmits, 0)
                    self.assertEqual(stats.timeouts, 0)
                    self.assertTrue(stats.eof_acked)
                    if delay == 0:
                        self.assertEqual(stats.pacing_seconds, 0)
                    else:
                        self.assertGreater(stats.pacing_seconds, 0)
                    comparison.append({'packet_delay_us': delay, 'bytes_acked': stats.bytes_acked,
                                       'data_packets': stats.data_packets, 'windows_sent': stats.windows_sent,
                                       'retransmits': stats.retransmits, 'timeouts': stats.timeouts,
                                       'eof_acked': stats.eof_acked, 'pacing_seconds': stats.pacing_seconds,
                                       'elapsed_seconds': stats.elapsed_seconds})
                self.assertIn('transfers_succeeded=1', output.getvalue())
        # Observed Linux localhost timings are diagnostic, never an assertion
        # that Windows or the physical board improved by the same amount.
        print('LOCALHOST PACING COMPARISON ' + json.dumps(comparison, sort_keys=True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
