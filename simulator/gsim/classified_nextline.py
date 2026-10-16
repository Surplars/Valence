#!/usr/bin/env python3
"""Existing checked-register PMP decision split: bounded functional/formal/map gate."""
import argparse,collections,hashlib,json,os,re,subprocess,sys
from pathlib import Path
import run as common

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--tag',required=True)
 for n in ('gsim','firtool','yosys','sv2v'):ap.add_argument('--'+n,type=Path,required=True)
 a=ap.parse_args();out=common.BUILD/a.tag;out.mkdir(parents=True,exist_ok=False)
 files=sorted((common.ROOT/'src').rglob('*.scala'))+[Path(__file__),common.HERE/'analyze_classified_nextline.py',common.HERE/'run.py',common.HERE/'harness/classified_nextline_queue.cpp',common.HERE/'harness/virtual_load_precheck.cpp',common.HERE/'harness/virtual_load_test_memory.h']
 before={str(p.relative_to(common.ROOT)):sha(p) for p in files};r={'status':'RUNNING','source_sha256':before,'tools':{str(p):sha(p) for p in (a.gsim,a.firtool,a.yosys,a.sv2v)},'maps':{}}
 def save():(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
 def negative(model,arg,anchor):
  x=subprocess.run([str(model/'run'),arg],capture_output=True,text=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=120);(model/'negative.log').write_text(x.stdout+x.stderr)
  assert x.returncode!=0 and anchor in x.stdout+x.stderr,(arg,x.stdout,x.stderr)
 save()
 try:
  cxx,_=common.compiler()
  q=common.test(a.gsim,cxx,a.tag+'/queue','soc.core.ooo.ClassifiedNextLineQueueGsimMain','ClassifiedNextLineQueueGsim','classified_nextline_queue.cpp',timeout=120)
  assert 'CLASSIFIED_NATIVE_RECORD=431 CLASSIFIED=464 BASE=2149580800 BYTES=2147483648' in (q/'elaborate.log').read_text()
  assert 'CLASSIFIED_NEXTLINE_QUEUE_PASS' in (q/'test.log').read_text();negative(q,'--corrupt-summary','classified queue complete authority parity')
  r['queue']='PASS 20000 random cycles, exact431-bit record, independent byte-PMP/owner oracle, changing context while stalled, negative control';save()
  for variant,emitter in [('adapter','ClassifiedNextLineAdapterGsimMain'),('adapter-hit','ClassifiedNextLineHitAdapterGsimMain')]:
   ad=common.test(a.gsim,cxx,a.tag+'/'+variant,'ooo.'+emitter,'VirtualLoadPrecheckGsim','virtual_load_precheck.cpp',defines={'PRECHECK_ENABLED':1,'DTLB_ENTRIES':8},timeout=120)
   assert 'VIRTUAL_LOAD_PRECHECK_PASS' in (ad/'test.log').read_text();negative(ad,'--inject-address','mismatch')
   r[variant]='PASS exact-cycle adapter pair and independent memory/translation oracle, address negative';save()
  for mode in ('miter','0','1'):
   d=out/mode;d.mkdir();top='ClassifiedNextLineMiter' if mode=='miter' else 'ClassifiedNextLineQueue'
   main='soc.core.ooo.'+('ClassifiedNextLineMiterMain' if mode=='miter' else 'ClassifiedNextLineQueueMapMain')
   common.run(['mill','-i','IonSoC.test.runMain',main,d,*(() if mode=='miter' else (mode,))],log=d/'elaborate.log')
   common.run([a.firtool,d/(top+'.fir'),'--verilog','--disable-layers=Verification','-o',d/'dut.sv'],log=d/'firtool.log')
   with (d/'dut.v').open('w') as f:subprocess.run([str(a.sv2v),str(d/'dut.sv')],stdout=f,check=True)
   setup=f'read_verilog {d}/dut.v; hierarchy -top {top}; chformal -remove; '
   if mode=='miter':
    common.run([a.yosys,'-Q','-T','-p',setup+f'prep -top {top} -flatten; opt; sat -prove io_equal 1 -verify -timeout 120'],log=d/'proof.log');r['formal']='PASS arbitrary65-bit bounds/current request/privilege/fault decision equivalence';save();continue
   common.run([a.yosys,'-Q','-T','-p',setup+f'prep -top {top} -flatten; opt; sat -seq 2 -set-at 1 reset 1 -prove-skip 1 -prove io_count 0 -prove io_deq_valid 0 -prove io_enq_ready 1 -verify -timeout 120'],log=d/'reset-proof.log')
   r['maps'][mode]={}
   for policy,flag in [('default',''),('nowidelut','-nowidelut')]:
    target=d/(policy+'.json');common.run([a.yosys,'-Q','-T','-p',setup+f'synth_xilinx -family xcup -top {top} -flatten -noiopad -noclkbuf {flag}; check -assert; write_json {target}'],log=d/(policy+'.log'))
    common.run([sys.executable,common.HERE/'analyze_classified_nextline.py',target,'--classification-width','33' if mode=='1' else '0',*(('--no-wide',) if policy=='nowidelut' else ())],log=d/(policy+'.analysis.log'))
    m=json.loads(target.read_text())['modules'][top];counts=collections.Counter(c['type'] for c in m['cells'].values());r['maps'][mode][policy]={'cells':dict(counts),'LUT':sum(v for k,v in counts.items() if k.startswith('LUT')),'mapped_sha256':sha(target),'analysis':json.loads(target.with_suffix('.analysis.json').read_text())};save()
  assert before=={str(p.relative_to(common.ROOT)):sha(p) for p in files}
  for policy in ('default','nowidelut'):assert r['maps']['1'][policy]['analysis']['FF']-r['maps']['0'][policy]['analysis']['FF']==66
  r['status']='PASS_COMPONENT_AND_ADAPTER_NO_PHYSICAL_SIGNOFF';save();print(r['status'])
 except BaseException as e:r['status']='FAIL';r['error']=repr(e);save();raise
if __name__=='__main__':main()
