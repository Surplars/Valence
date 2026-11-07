#!/usr/bin/env python3
"""Validate a source-pinned generated platform and run the final independent drivers.
The model must come from platform_acceptance.py. This records exact source,
class, dependency and model lineage; the C++ model is compiled once for both
finite VS interrupt/reset and VS physical-memory-attribute exception programs.
"""
import argparse, hashlib, json, os, pathlib, subprocess, time
ROOT=pathlib.Path(__file__).resolve().parents[2]
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--model',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--cxx',type=pathlib.Path,required=True);a=p.parse_args()
 m=a.model.resolve();o=a.output.resolve();o.mkdir(exist_ok=False);prior=json.loads((m/'receipt.json').read_text());assert prior['status']=='PASS_FINITE_HYPERVISOR_PLATFORM'
 inputs=['simulator/gsim/harness/hypervisor_platform.cpp','simulator/gsim/harness/platform_pma_exceptions.cpp','simulator/gsim/platform_final_acceptance.py']
 rec={'status':'RUNNING','prior_receipt':str(m/'receipt.json'),'prior_receipt_sha256':sha(m/'receipt.json'),'model_pins':{},'inputs':{x:sha(ROOT/x) for x in inputs},'cxx':str(a.cxx.resolve()),'cxx_sha256':sha(a.cxx),'commands':[]}
 def save(): (o/'receipt.json').write_text(json.dumps(rec,indent=2)+'\n')
 def validate():
  assert sha(m/'receipt.json')==rec['prior_receipt_sha256']
  for x,h in prior['core_source_pins'].items(): assert sha(x)==h,x
  for x,h in prior['inputs'].items():
   if x!='simulator/gsim/harness/hypervisor_platform.cpp': assert sha(ROOT/x)==h,x
  for x,h in prior['artifacts'].items(): assert sha(m/x)==h,x
  for x,h in rec['inputs'].items(): assert sha(ROOT/x)==h,x
  assert sha(a.cxx)==rec['cxx_sha256']
 def run(cmd,name,expected=0,marker=None):
  cmd=list(map(str,cmd));start=time.monotonic()
  with (o/name).open('w') as log:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=600,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0','UBSAN_OPTIONS':'halt_on_error=1'})
  rec['commands'].append({'argv':cmd,'exit':r.returncode,'seconds':time.monotonic()-start,'log':name});save();t=(o/name).read_text();assert r.returncode==expected,t[-15000:]
  if marker: assert marker in t,t[-15000:]
  return t
 try:
  validate()
  cpp=sorted(m.glob('HypervisorPlatformGsim[0-9]*.cpp'));assert len(cpp)==1
  rec['model_pins']={str(x):sha(x) for x in [*cpp,m/'HypervisorPlatformGsim.h',m/'HypervisorPlatformGsim.fir']}
  flags=[a.cxx,'-std=c++20','-O1','-fbracket-depth=4096','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(m)]
  run([*flags,'-c',cpp[0],'-o',o/'model.o'],'compile-model.log')
  for name,file,marker in [('chains','hypervisor_platform.cpp','HYPERVISOR_PLATFORM_PASS'),('pma','platform_pma_exceptions.cpp','PLATFORM_VS_PMA_EXCEPTIONS_PASS')]:
   run([*flags,ROOT/'simulator/gsim/harness'/file,o/'model.o','-ldl','-o',o/name],name+'-link.log')
   print(run([o/name],name+'.log',marker=marker),flush=True)
  run([o/'chains','--wrong-memory'],'negative.log',expected=1,marker='independent platform store value')
  validate();rec['status']='PASS_FINITE_PLATFORM_VS_IRQ_PMA_COLD_RESET';rec['scope']={'cdc_dynamic':False,'external_ddr_dynamic':False,'dma_drain':False,'misa_h':False,'restricted_m_origin_review':False}
 except BaseException as e:rec['status']='FAIL';rec['error']=repr(e);raise
 finally:rec['artifacts']={str(x.relative_to(o)):sha(x) for x in sorted(o.rglob('*')) if x.is_file() and x.name!='receipt.json'};save()
if __name__=='__main__':main()
