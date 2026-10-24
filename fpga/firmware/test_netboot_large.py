"""Bounded-memory logical transfers beyond three16-bit wraps, no sockets/disk payload."""
import unittest
import struct
import netboot_host as host
from test_netboot_host import FakeClock, WindowSocket

PEER=('192.0.2.30',41000)
class Source:
    def __init__(self,size):self.remaining=size;self.reads=0
    def read(self,size):
        if size!=1024:raise AssertionError('block changed')
        n=min(size,self.remaining);self.remaining-=n;self.reads+=1
        return b'\x5a'*n

class Tests(unittest.TestCase):
    def test_three_wraps_zero_eof_and_lost_acks(self):
        size=208*1024*1024
        clock=FakeClock()
        receiver=WindowSocket(drop_data=(65535,),drop_acks=(65536,131072,196608),clock=clock)
        source=Source(size);stats=host.TransferStats()
        result=host.transfer(receiver,PEER,source,blksize=1024,windowsize=4,
                             stats=stats,clock=clock,sleeper=clock.advance,inter_packet_seconds=0)
        self.assertEqual(result,size)
        self.assertEqual(receiver.bytes_received,size)
        self.assertEqual(receiver.accepted,size//1024+1)
        self.assertTrue(receiver.eof and stats.eof_acked)
        self.assertEqual(source.reads,size//1024+1)
        self.assertEqual(stats.max_buffered_blocks,4)
        self.assertGreater(stats.retransmits,0)
        self.assertEqual(stats.bytes_acked,size)
    def test_corrupted_wrap_ack_rejected_by_normal_timeout(self):
        class BadWrap(WindowSocket):
            def recvfrom(self,size):
                packet,peer=super().recvfrom(size)
                if self.accepted>=65536 and struct.unpack('!HH',packet)[1]==0:
                    return struct.pack('!HH',4,9),peer
                return packet,peer
        clock=FakeClock();receiver=BadWrap(clock=clock);stats=host.TransferStats()
        with self.assertRaises(TimeoutError):
            host.transfer(receiver,PEER,Source(65536*1024),blksize=1024,windowsize=4,
                          retries=3,stats=stats,clock=clock,sleeper=clock.advance,inter_packet_seconds=0)
        self.assertFalse(stats.eof_acked)
if __name__=='__main__':unittest.main()
