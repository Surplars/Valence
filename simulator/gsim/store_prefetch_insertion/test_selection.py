#!/usr/bin/env python3
import ast,json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
def call(script,args,ok=True):
 p=subprocess.run([sys.executable,'-B',str(ROOT/script),*args],text=True,capture_output=True)
 assert (p.returncode==0)==ok,(args,p.stdout,p.stderr)
 if not ok:
  assert '--store-prefetch-mru-insertion requires --store-next-line-prefetch' in p.stderr
  return None
 return json.loads(p.stdout)
def main():
 for name in ['fpga/next/export.py','simulator/gsim/fpga_next_board.py']:
  ast.parse((ROOT/name).read_text())
 with tempfile.TemporaryDirectory(prefix='store-mru-selection-') as d:
  out=Path(d)/'uncreated'
  for extra in [[],['--store-next-line-prefetch'],['--store-next-line-prefetch','--store-prefetch-mru-insertion']]:
   q=call('simulator/gsim/fpga_next_board.py',['--tag','store-mru-preflight-only','--preflight-only','--variant','selected',*extra])
   assert q['status']=='PREFLIGHT_ONLY';plan=q['plan'];assert plan['store_prefetch_mru_insertion']==('--store-prefetch-mru-insertion' in extra)
   assert plan['store_next_line_prefetch']==('--store-next-line-prefetch' in extra)
   assert plan['parameters'].count('--store-prefetch-mru-insertion')==int(plan['store_prefetch_mru_insertion'])
   x=call('fpga/next/export.py',['--output',str(out),*extra]);assert x['status']=='PREFLIGHT_ONLY' and not out.exists()
  call('simulator/gsim/fpga_next_board.py',['--tag','store-mru-preflight-only','--preflight-only','--store-prefetch-mru-insertion'],False)
  call('fpga/next/export.py',['--output',str(out),'--store-prefetch-mru-insertion'],False)
 print('STORE_PREFETCH_INSERTION_SELECTION_PASS cases=8 no_output_created=1')
if __name__=='__main__':main()
