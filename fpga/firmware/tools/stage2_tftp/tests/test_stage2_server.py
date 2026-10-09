"""Small-file server/manifest checks; no real board or large fixture required."""
import contextlib
import hashlib
import importlib.util
import io
import json
import pathlib
import socket
import struct
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import stage2_tftp as stage2
import netboot_host as engine


def rrq(name='Image', window=None, blksize=1024):
    fields = [name.encode(), b'octet']
    if blksize is not None:
        fields += [b'blksize', str(blksize).encode()]
    if window is not None:
        fields += [b'windowsize', str(window).encode()]
    return b'\0\1' + b'\0'.join(fields) + b'\0'


class PairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = pathlib.Path(self.temp.name)
        self.image, self.dtb = self.folder/'Image', self.folder/'valence-vl100.dtb'
        self.image.write_bytes(bytes(range(251)) * 21)
        self.dtb.write_bytes(b'synthetic-dtb-for-protocol-test')
        self.data = {'schema': 1, 'label': 'Synthetic host-test pair only', 'files': {
            path.name: {'size': path.stat().st_size,
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in (self.image, self.dtb)}}
        self.manifest = self.folder/'pair.json'
        self.write_manifest()

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.data), encoding='utf-8')

    def prepare(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return stage2.prepare(self.image, self.dtb, self.manifest)

    def test_explicit_pair_requires_both_exact_hashes(self):
        self.assertEqual(set(self.prepare()), {'Image', 'valence-vl100.dtb'})
        self.dtb.write_bytes(b'X' * self.dtb.stat().st_size)
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            self.prepare()

    def test_default_still_rejects_non_v3_pair(self):
        with self.assertRaisesRegex(ValueError, 'size'):
            stage2.prepare(self.image, self.dtb)
        label, expected = stage2.load_pair()
        self.assertEqual(expected, stage2.EXPECTED)
        self.assertIn('V3', label)
        self.assertEqual(stage2.load_pair(ROOT/'stage2-pair-v3.json')[1], expected)

    def test_manifest_cannot_add_files_paths_or_fields(self):
        mutations = [
            lambda d: d['files'].update({'secret.txt': d['files']['Image']}),
            lambda d: d['files'].__setitem__('../Image', d['files'].pop('Image')),
            lambda d: d['files']['Image'].update(path='/etc/passwd'),
            lambda d: d['files']['Image'].update(size=True),
            lambda d: d['files']['Image'].update(size=0),
            lambda d: d['files']['Image'].update(sha256='0'*63),
            lambda d: d.update(schema=True),
            lambda d: d.update(schema=2),
            lambda d: d.update(label='bad\nlabel'),
            lambda d: d.pop('files'),
        ]
        original = json.dumps(self.data)
        for mutate in mutations:
            self.data = json.loads(original)
            mutate(self.data)
            self.write_manifest()
            with self.subTest(data=self.data), self.assertRaises(ValueError):
                stage2.load_pair(self.manifest)

    def test_manifest_duplicate_and_oversized_rejected(self):
        self.manifest.write_text('{"schema":1,"schema":1}')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            stage2.load_pair(self.manifest)
        self.manifest.write_text(' ' * 16385)
        with self.assertRaisesRegex(ValueError, '16 KiB'):
            stage2.load_pair(self.manifest)

    def test_rrq_paths_and_non_pair_names_not_accepted(self):
        self.assertIsNone(engine.parse_request(rrq('../Image')))
        self.assertIsNone(engine.parse_request(rrq('/Image')))
        self.assertNotIn(engine.parse_request(rrq('secret.txt')).name, self.prepare())

    def test_limits_invalid_before_bind(self):
        for settings in ({'max_windowsize': 0}, {'max_windowsize': 17}, {'max_blksize': 2048},
                         {'packet_delay_us': -1}, {'packet_delay_us': float('nan')},
                         {'packet_delay_us': float('inf')}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                stage2.serve(self.prepare(), '127.0.0.1', '127.0.0.1', 0, **settings)

    def test_server_uses_negotiated_window_and_prints_stats_on_failure_interrupt(self):
        peer = ('127.0.0.1', 34567)
        class FakeSocket:
            def __init__(self, request=None): self.request = request
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def bind(self, address): self.address = address
            def getsockname(self): return self.address
            def recvfrom(self, size):
                if self.request is None: raise KeyboardInterrupt()
                request, self.request = self.request, None
                return request, peer
        for requested, cap, actual in ((4, 1, 1), (4, 2, 2), (2, 4, 2), (None, 4, 1)):
            for failure in (OSError('synthetic failure'), KeyboardInterrupt()):
                output = io.StringIO()
                sockets = [FakeSocket(rrq(window=requested)), FakeSocket()]
                with self.subTest(requested=requested, cap=cap, failure=type(failure).__name__), \
                     mock.patch.object(stage2.socket, 'socket', side_effect=sockets), \
                     mock.patch.object(engine, 'transfer', side_effect=failure) as transfer, \
                     contextlib.redirect_stdout(output), self.assertRaises(KeyboardInterrupt):
                    stage2.serve(self.prepare(), peer[0], peer[0], 0, max_windowsize=cap)
                kwargs = transfer.call_args.kwargs
                self.assertEqual(kwargs['windowsize'], actual)
                self.assertEqual(kwargs['oack'], engine.parse_request(rrq(window=requested), max_windowsize=cap).oack)
                text = output.getvalue()
                self.assertIn('TFTP STATS', text)
                self.assertIn('SERVER_TOTALS', text)
                self.assertIn('REQUEST_RECEIVED', text)
                self.assertIn('REQUEST_ACCEPTED', text)
                self.assertIn('windowsize=' + str(actual), text)

    def test_foreign_rrq_silent_and_invalid_filename_error(self):
        output, sent = io.StringIO(), []
        replies = [(rrq(), ('127.0.0.2', 4)), (rrq('secret.txt'), ('127.0.0.1', 4)),
                   (rrq('../Image'), ('127.0.0.1', 4))]
        class Listener:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def bind(self, address): self.address = address
            def getsockname(self): return self.address
            def recvfrom(self, size):
                if replies: return replies.pop(0)
                raise KeyboardInterrupt()
            def sendto(self, packet, peer): sent.append((packet, peer))
        with mock.patch.object(stage2.socket, 'socket', return_value=Listener()), \
             contextlib.redirect_stdout(output), self.assertRaises(KeyboardInterrupt):
            stage2.serve(self.prepare(), '127.0.0.1', '127.0.0.1', 0)
        self.assertEqual(len(sent), 2)
        self.assertTrue(all(p == b'\0\5\0\1file unavailable\0' for p, _ in sent))
        self.assertIn('transfers_started=0', output.getvalue())

    def test_disappeared_input_still_records_failed_stats(self):
        files = self.prepare()
        self.image.unlink()
        output = io.StringIO()
        replies = [(rrq(window=4), ('127.0.0.1', 4))]
        class Listener:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def bind(self, address): self.address = address
            def getsockname(self): return self.address
            def recvfrom(self, size):
                if replies: return replies.pop(0)
                raise KeyboardInterrupt()
        with mock.patch.object(stage2.socket, 'socket', return_value=Listener()), \
             contextlib.redirect_stdout(output), self.assertRaises(KeyboardInterrupt):
            stage2.serve(files, '127.0.0.1', '127.0.0.1', 0, max_windowsize=4)
        self.assertIn('FAILED', output.getvalue())
        self.assertIn('TFTP STATS', output.getvalue())
        self.assertIn('transfers_failed=1', output.getvalue())
        self.assertIn('windowsize=4', output.getvalue())

    def test_real_localhost_window_1_2_4_and_legacy_fallback(self):
        files = self.prepare()
        payload = self.image.read_bytes()
        for requested, cap, actual, blocksize in ((1, 1, 1, 1024), (2, 4, 2, 1024),
                                                 (4, 4, 4, 1024), (None, 4, 1, 1024),
                                                 (None, 4, 1, None)):
            output = io.StringIO()
            # Bind ownership is retained until the server asks for its listener.
            listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            ready, errors = threading.Event(), []
            original_socket = socket.socket
            class Prebound:
                def __init__(self, sock): self.sock = sock
                def __getattr__(self, name): return getattr(self.sock, name)
                def __enter__(self): return self
                def __exit__(self, *args): self.sock.close()
                def bind(self, address): ready.set()
            count = 0
            def factory(*args, **kwargs):
                nonlocal count
                count += 1
                return Prebound(listener) if count == 1 else original_socket(*args, **kwargs)
            def run():
                try: stage2.serve(files, '127.0.0.1', '127.0.0.1', port, once=True, max_windowsize=cap)
                except BaseException as error: errors.append(error)
            client = original_socket(socket.AF_INET, socket.SOCK_DGRAM)
            client.settimeout(3)
            with self.subTest(requested=requested, blocksize=blocksize), \
                 client, contextlib.redirect_stdout(output), \
                 mock.patch.object(stage2.socket, 'socket', side_effect=factory):
                worker = threading.Thread(target=run, daemon=True)
                worker.start()
                self.assertTrue(ready.wait(3))
                client.sendto(rrq(window=requested, blksize=blocksize), ('127.0.0.1', port))
                got, expected, since_ack, saw_oack = bytearray(), 1, 0, False
                while True:
                    packet, peer = client.recvfrom(2048)
                    op = int.from_bytes(packet[:2], 'big')
                    if op == 6:
                        saw_oack = True
                        expected_oack = engine.parse_request(rrq(window=requested, blksize=blocksize), max_windowsize=cap).oack
                        self.assertEqual(packet, expected_oack)
                        client.sendto(struct.pack('!HH', 4, 0), peer)
                        continue
                    self.assertEqual(op, 3)
                    self.assertEqual(int.from_bytes(packet[2:4], 'big'), expected)
                    got.extend(packet[4:]); since_ack += 1
                    eof = len(packet[4:]) < (blocksize or 512)
                    if since_ack == actual or eof:
                        client.sendto(struct.pack('!HH', 4, expected), peer); since_ack = 0
                    expected += 1
                    if eof: break
                worker.join(3)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(bytes(got), payload)
                self.assertEqual(saw_oack, blocksize is not None or requested is not None)
            self.assertIn('eof_acked=yes', output.getvalue())
            self.assertIn('windowsize=' + str(actual), output.getvalue())


if __name__ == '__main__':
    unittest.main(verbosity=2)
