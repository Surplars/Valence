import importlib.util
from pathlib import Path
import tempfile
import unittest
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
def load(name):
 s=importlib.util.spec_from_file_location(name,HERE/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=load('diagnostic_mac_contract');e=load('export_board')
class ContractTests(unittest.TestCase):
 def fixture(self,root):
  (root/'board').mkdir();(root/'rtl').mkdir()
  for name,data in e.build(True,True,'t1-selected').items(): (root/'board'/name).write_bytes(data)
  (root/'rtl/mock.sv').write_text('module mock; endmodule\n')
  (root/'synthesis-files.f').write_text('rtl/mock.sv\n')
  (root/'board-synthesis-files.f').write_text(''.join('board/'+n+'\n' for n in e.build(True,True,'t1-selected')))
  m.stage(ROOT,root)
 def test_mock_identity_and_changed_source(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);self.fixture(r);self.assertEqual(len(m.verify(r)),64)
   (r/'rtl/mock.sv').write_text('module changed; endmodule')
   with self.assertRaises(ValueError):m.verify(r)
 def test_missing_override_guard(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);self.fixture(r);p=r/'board/soc_top_fpga_next_ddr.sv';p.write_text(p.read_text().replace('initial if (NATIVE_MAC_LOCAL_PAD_RESET_RELEASE','initial if (0 && NATIVE_MAC_LOCAL_PAD_RESET_RELEASE'))
   with self.assertRaises(ValueError):m.verify(r)
 def test_changed_list_extra_tcl(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);self.fixture(r);(r/'board/extra.tcl').write_text('error extra')
   with self.assertRaises(ValueError):m.verify(r)
 def test_omitted_wrapper_and_checkpoint_disabled(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);self.fixture(r)
   script=(r/'board/native-mac-mode.tcl').read_text()
   self.assertTrue(script.rstrip().endswith('proc valence_native_mac_checkpoint {args} {error {Diagnostic flow requires external stage receipts; no legacy checkpoint writes permitted}}'))
   p=r/'board-synthesis-files.f';p.write_text('\n'.join(n for n in p.read_text().splitlines() if 'soc_top_fpga_next_ddr.sv' not in n)+'\n')
   with self.assertRaises(ValueError):m.sources(r)
 def test_unsafe_paths(self):
  with tempfile.TemporaryDirectory() as t:
   for n in ('../escape','C:/escape','x\\escape','/escape'):
    with self.assertRaises(ValueError):m.safe(Path(t),n)
if __name__=='__main__':unittest.main()
