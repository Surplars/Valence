import tempfile,unittest
from pathlib import Path
from export_board import ROOT,export,replace_once
class Candidate(unittest.TestCase):
 def test_off_exact(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d)/'off';r=export(out)
   self.assertEqual((out/'soc_top_fpga_next_ddr.sv').read_bytes(),(ROOT/'fpga/next/soc_top_fpga_next_ddr.sv').read_bytes())
   self.assertFalse(r['physicalQualification'])
 def test_on_atomic(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d)/'on';r=export(out,True);s=(out/'soc_top_fpga_next_ddr.sv').read_text()
   self.assertIn('.rx_clock(clk_rx_capture)',s)
   self.assertIn('.io_nativeGmac_rawRxClock(clk_rx)',s)
   self.assertIn('posedge clk_rx_capture or posedge rx_reset_request',s)
   self.assertIn('.rx_rise(capture_rx_rise), .rx_fall(capture_rx_fall)',s)
   self.assertEqual(r['extraPairBits'],10)
 def test_wrong_marker(self):
  with self.assertRaises(ValueError):replace_once(b'x x',b'x',b'y')
 def test_fresh_output(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(FileExistsError):export(d)
if __name__=='__main__':unittest.main()
