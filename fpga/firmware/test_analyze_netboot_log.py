import unittest
from analyze_netboot_log import analyze
class Tests(unittest.TestCase):
    def test_timebase_not_cpu_hz(self):
        r=analyze('NB totals timebase_hz=250000000 transfer_ticks=250000000 length=1048576 rx_wait_ticks=125000000 copy_ticks=62500000 stream_crc_ticks=50000000 tx_ack_ticks=12500000 ram_crc_ticks=0')
        b=r['board_runs'][0]
        self.assertEqual(b['payload_mib_per_second'],1)
        self.assertEqual(b['phases_seconds']['copy_ticks'],.25)
        self.assertEqual(b['largest_recorded_receive_service'],'rx_wait_ticks')
    def test_host_pacing(self):
        h=analyze('TFTP STATS bytes_acked=1048576 read=0.1s send=0.2s ack_wait=0.3s other=0.4s elapsed=2.000000s pacing=1.000000s')['host_runs'][0]
        self.assertEqual(h['mean_acked_payload_mib_s'],.5)
        self.assertEqual(h['pacing_share'],.5)
    def test_multiple_runs_not_silently_paired(self):
        line='NB totals timebase_hz=1 transfer_ticks=1 length=1'
        self.assertEqual(len(analyze(line+'\n'+line)['board_runs']),2)
    def test_completion_and_missing_pacing(self):
        h=analyze('TFTP STATS bytes_acked=4 elapsed=1s eof_acked=yes')['host_runs'][0]
        self.assertTrue(h['eof_acked'])
        self.assertIsNone(h['pacing_share'])
    def test_bad_inputs(self):
        for text in ('', 'NB totals length=1', 'NB totals timebase_hz=0 transfer_ticks=1 length=1',
                     'NB totals timebase_hz=1 transfer_ticks=NaN length=1',
                     'NB totals timebase_hz=1 transfer_ticks=1 length=1 copy_ticks=Inf',
                     'TFTP STATS bytes_acked=1 elapsed=-1s',
                     'TFTP STATS bytes_acked=1 elapsed=1s pacing=Inf',
                     'TFTP STATS bytes_acked=1 elapsed=1s elapsed=2s',
                     'TFTP STATS bytes_acked=1 elapsed=1s eof_acked=perhaps'):
            with self.subTest(text=text), self.assertRaises(ValueError): analyze(text)
if __name__=='__main__':unittest.main()
