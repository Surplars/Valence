import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import socket
import struct
import netboot_host as host

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

if __name__ == "__main__":
    unittest.main()
