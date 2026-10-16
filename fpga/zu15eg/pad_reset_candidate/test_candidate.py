import json,tempfile,unittest
from pathlib import Path
from export_board import ROOT,export
class Candidate(unittest.TestCase):
 def test_off_exact(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d)/'off';r=export(out)
   self.assertEqual((out/'soc_top_fpga_next_ddr.sv').read_bytes(),(ROOT/'fpga/next/soc_top_fpga_next_ddr.sv').read_bytes())
   self.assertFalse(r['enabled']);self.assertFalse(r['physicalQualification'])
   self.assertFalse((out/'native_gmac_pad_reset_clock.sv').exists())
 def test_explicit_on(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d)/'on';r=export(out,True,"t1-selected")
   self.assertEqual((out/'soc_top_fpga_next_ddr.sv').read_text().count('ENABLE_PAD_DOMAIN_RESET(1)'),1)
   self.assertIn('parameter NATIVE_MAC_LOCAL_PAD_RESET_RELEASE = 1',(out/'soc_top_fpga_next_ddr.sv').read_text())
   self.assertIn('requires t1-selected serializer 1/1',(out/'soc_top_fpga_next_ddr.sv').read_text())
   self.assertTrue(r['requiresNewClockResetAudit']);self.assertTrue(r['rxSourceUnchanged'])
   self.assertFalse(r['completeNativeExport'])
 def test_on_requires_profile(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):export(Path(d)/'bad',True)
 def test_reuse_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(FileExistsError):export(d)
if __name__=='__main__':unittest.main()
