import io
import struct
import unittest
from unittest.mock import patch
from memory_layout import PROFILES, RAM_BASE
import netboot_host as net
import uart_load as uart
from build_linux import board_dts

class LayoutTest(unittest.TestCase):
    def test_full_2g_and_monitor(self):
        layout = PROFILES["ddr2g"]
        self.assertEqual(layout.end, 0x100200000)
        self.assertEqual(layout.monitor, 0xffff8000)
        self.assertEqual(layout.image_limit, 0x7fdf8000)
        self.assertLessEqual(layout.monitor + 0x4000 - 0x80000000, 0x7ffff000)
        self.assertEqual(net.LIMITS["ddr2g"], layout.image_limit)
        self.assertEqual(uart.IMAGE_LIMITS["ddr2g"], layout.image_limit)
        dt = board_dts("rv64gc",100000000,460800,layout.ram_bytes)
        self.assertIn("0x0 0x80000000",dt)
        self.assertIn("monitor@ffff8000",dt)
        self.assertIn("0x0 0xffff8000 0x0 0x4000",dt)

    def test_explicit_profile_header(self):
        size = net.LIMIT + 8
        with self.assertRaises(ValueError):
            net.header(size,0)
        self.assertEqual(len(net.header(size,0,limit=net.LIMITS["ddr2g"])),36)
        for size in (0, net.LIMITS["ddr2g"]+1):
            with self.assertRaises(ValueError):
                net.header(size,0,limit=net.LIMITS["ddr2g"])
        with self.assertRaises(ValueError):
            net.header(1024,0,entry=0x100000000,limit=net.LIMITS["ddr2g"])

    def test_tftp_block_wrap_without_network(self):
        class AckSocket:
            def __init__(self): self.blocks=[];self.reply=None
            def sendto(self,p,peer):
                opcode, block=struct.unpack("!HH",p[:4])
                self.blocks.append(block)
                self.reply=(struct.pack("!HH",4,block),peer)
            def recvfrom(self,n): return self.reply
            def settimeout(self,n): pass
        class Payload:
            remaining = 65536
            def read(self,n):
                if not self.remaining: return b""
                self.remaining-=1
                return b"X"*n
        sock=AckSocket()
        self.assertEqual(net.transfer(sock,("192.0.2.1",49152),Payload()),33554432)
        self.assertEqual(sock.blocks[-3:],[65535,0,1])

if __name__ == "__main__":
    unittest.main()
