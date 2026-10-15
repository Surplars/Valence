#!/usr/bin/env python3
"""Stage the hash-bound76 host from repository sources; optionally run pure host tests.
Never emits a CPU, starts GSIM, publishes, or changes defaults.
"""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess
HERE=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser(allow_abbrev=False)
 ap.add_argument('--repository',type=Path,default=HERE.parents[2])
 ap.add_argument('--output',type=Path,required=True)
 ap.add_argument('--host-tests',action='store_true')
 ap.add_argument('--cxx',default='clang++-19')
 a=ap.parse_args();root=a.repository.resolve();out=a.output.resolve()
 if out.exists():raise SystemExit('fresh output directory required')
 m=json.loads((HERE/'inputs.json').read_text())
 profile=json.loads((root/'fpga/next/shared-lru76-profile.json').read_text())
 if not (len(profile['on_options'])==76 and profile['on_profile']['cache']['storePrefetchLruVictim'] is True):
  raise SystemExit('exact76 profile/LRU flag required')
 out.mkdir(parents=True);records={}
 def copy(src,dst,digest):
  if sha(src)!=digest:raise RuntimeError('input hash mismatch: '+str(src))
  dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst);records[str(dst.relative_to(out))]=digest
 for n,v in m['inputs'].items():copy(root/v['source'],out/'host'/n,v['sha256'])
 for n,v in m['guest_inputs'].items():copy(root/v['source'],out/'guest'/n,v['sha256'])
 for n,h in m['policy_sources'].items():copy(HERE/n,out/n,h)
 original=out/'original/host/supply_ledger.h';v=m['original_supply_ledger'];copy(root/v['source'],original,v['sha256'])
 (out/'policy_test_original.cpp').write_text((out/'policy_test.cpp').read_text().replace('#include "host/supply_ledger.h"','#include "original/host/supply_ledger.h"'))
 (out/'host-flags.json').write_text(json.dumps(m['host_flags'],indent=2)+'\n')
 result={'status':'PASS_SOURCE_HOST_STAGED','inputs':records,'model_built':False,'cpu_executed':False,'tests':[]}
 if a.host_tests:
  env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'}
  flags=[x for x in m['host_flags'] if not x.startswith('-DSTORE_PREFETCH_LRU_VICTIM=')]
  for variant,lru in [('original',0),('off',0),('on',1)]:
   source=out/('policy_test_original.cpp' if variant=='original' else 'policy_test.cpp');binary=out/(variant+'-test')
   subprocess.run([a.cxx,*flags,'-DSTORE_PREFETCH_LRU_VICTIM='+str(lru),'-I'+str(out/'host'),'-I'+str(out),str(source),'-o',str(binary)],check=True)
   for mode,reason in [('',None)]+([] if variant=='original' else [('--wrong-lru','victim identity mismatch'),('--wrong-pa','full PA mismatch'),('--wrong-protection','victim identity mismatch')]):
    work=out/(variant+(mode or '-positive'));work.mkdir()
    p=subprocess.run([str(binary)]+([mode] if mode else []),cwd=work,env=env,text=True,capture_output=True)
    text=p.stdout+p.stderr;(work/'result.log').write_text(text)
    if p.returncode!=(1 if mode else 0):raise RuntimeError(text)
    if any(x in text for x in ['AddressSanitizer','runtime error:','UndefinedBehaviorSanitizer','LeakSanitizer']):raise RuntimeError(text)
    expected='POLICY_GUARD_FAIL '+reason if mode else 'POLICY_GUARD_PASS lru='+str(lru)+' cases=4096'
    if expected not in text or (mode and 'POLICY_INJECTION_REACHED '+mode not in text):raise RuntimeError(text)
    result['tests'].append({'variant':variant,'mode':mode,'exit':p.returncode,'log_sha256':sha(work/'result.log')})
  bodies=[]
  for source in [out/'policy_test_original.cpp',out/'policy_test.cpp']:
   text=subprocess.check_output([a.cxx,*flags,'-DSTORE_PREFETCH_LRU_VICTIM=0','-I'+str(out/'host'),'-I'+str(out),'-E','-P',str(source)],text=True)
   start=text.index('template<class D> Guard guard(');end=text.index('template<class D> void snapshot(',start);bodies.append(text[start:end])
  if bodies[0]!=bodies[1]:raise RuntimeError('default-OFF guard changed')
  result['off_preprocessed_guard_equal']=True
  result['status']='PASS_SOURCE_HOST_STAGED_3_POSITIVE_6_NEGATIVE'
 (out/'receipt.json').write_text(json.dumps(result,indent=2)+'\n');print(result['status'])
if __name__=='__main__':main()
