#!/usr/bin/env python3
"""Two direct AXI AW/W independence models, plus the existing mixed-memory oracle."""
import hashlib,json,os,subprocess
from pathlib import Path
import run as common
out=common.BUILD/'bridge-write-channels-20261007-r1';out.mkdir(parents=True,exist_ok=False)
paths=sorted((common.ROOT/'src').rglob('*.scala'))+[Path(__file__),common.HERE/'harness/tilelink_axi4_write_channels.cpp',common.HERE/'harness/tilelink_axi4_outstanding.cpp']
def hashes():return {str(p.relative_to(common.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
r={'status':'RUNNING','source_sha256':hashes(),'cases':{}}
try:
 gsim,cxx=common.setup(False)
 for slots in (1,4):
  name=f's{slots}-b16';target=common.test(gsim,cxx,str(out.relative_to(common.BUILD)/name),'ooo.TileLinkAxi4OutstandingGsimMain','TileLinkAxi4Bridge','tilelink_axi4_write_channels.cpp',parameters=(slots,16,3),defines={'AXI_SLOTS':slots},timeout=120)
  log=(target/'test.log').read_text();assert 'WRITE_CHANNELS_ALL_PASS' in log
  neg=subprocess.run([target/'run','--inject-data'],capture_output=True,text=True,timeout=120,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'});(target/'negative.log').write_text(neg.stdout+neg.stderr)
  assert neg.returncode!=0 and 'W independent payload/strobe/last mismatch' in neg.stdout+neg.stderr
  # Reuse the generated hardware; this links the prior independent read/write
  # memory oracle, including source, error, denial, reset and FIFO D checks.
  common.run([cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-DMAX_BURST_BEATS=16','-DTL_SIZE_BITS=3',f'-I{target}',*sorted(target.glob('TileLinkAxi4Bridge[0-9]*.cpp')),common.HERE/'harness/tilelink_axi4_outstanding.cpp','-ldl','-o',target/'memory-run'],log=target/'memory-compile.log')
  common.run([target/'memory-run'],log=target/'memory.log',env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=120)
  memory=(target/'memory.log').read_text();assert 'OUTSTANDING_ALL_PASS' in memory
  r['cases'][name]={'log':log,'negative':'PASS','memory':memory};assert hashes()==r['source_sha256'],'source drift'
  (out/'progress.json').write_text(json.dumps(r,indent=2)+'\n')
 r['status']='PASS'
except BaseException as e:r['status']='FAIL';r['error']=str(e);raise
finally:(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
