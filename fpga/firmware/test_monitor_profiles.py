"""Cross-check menu memory bounds without allocating multi-GiB images."""
import json, pathlib, subprocess, tempfile, unittest
import netboot_host as net
import uart_load as uart
from memory_layout import MemoryLayout
class Profiles(unittest.TestCase):
 def test_profiles(self):
  root=pathlib.Path(__file__).resolve().parent
  with tempfile.TemporaryDirectory() as tmp:
   for name,size in [('ddr',0x20000000),('ddr1g',0x40000000),('ddr2g',0x80000000)]:
    limit=MemoryLayout(size).image_limit-0x80000
    self.assertEqual(net.LIMITS[name+'-menu'],limit)
    self.assertEqual(uart.IMAGE_LIMITS[name+'-menu'],limit)
    self.assertEqual(len(net.header(limit,0,limit=limit)),36)
    with self.assertRaises(ValueError):net.header(limit+1,0,limit=limit)
    p=pathlib.Path(tmp)/'layout.c';p.write_text('#include "board_memory.h"\n_Static_assert(IMAGE_LIMIT == '+str(limit)+'UL,"host/board drift");\n_Static_assert(DIAG_BASE+0x80000UL==BOARD_MONITOR_BASE,"scratch/monitor overlap");\nint main(void){return 0;}\n')
    subprocess.run(['clang-19','-std=c11','-Werror','-DBOOT_MENU=1',f'-DBOARD_RAM_BYTES={size}UL',f'-DBOARD_MONITOR_BASE={MemoryLayout(size).monitor}UL','-I'+str(root),str(p),'-o',str(pathlib.Path(tmp)/'check')],check=True)
 def test_current_payload(self):
  for name in ['ddr-menu','ddr1g-menu','ddr2g-menu']:
   self.assertEqual(len(net.header(76564168,0,limit=net.LIMITS[name])),36)
if __name__=='__main__':unittest.main()
