#!/usr/bin/env python3
"""Exact-profile real backend lifecycle A/B; original independent decoded oracle."""
import argparse,hashlib,json,os,re,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BASE_COMMIT='22bbd0dbd833b976315d2b5c485db659bddc8d69'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--baseline-root',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
 ap.add_argument('--gsim',type=Path,required=True);a=ap.parse_args()
 o=a.output.resolve();o.mkdir(parents=True,exist_ok=False);os.nice(10)
 roots={'baseline':a.baseline_root.resolve(),'candidate':ROOT}
 extra=['simulator/gsim/harness/preselected_redirect_lifecycle.cpp',
 'simulator/gsim/ready_store_query77/ready_store_query77_backend.cpp',
 'simulator/gsim/ready_store_query77/ready_store_query77_reference.h']
 def inputs(root):return {str(p.relative_to(root)):sha(p) for p in [*root.glob('src/**/*.scala'),*[root/n for n in extra]]}
 frozen={arm:inputs(root) for arm,root in roots.items()}
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=roots['baseline'],text=True).strip()==BASE_COMMIT
 assert subprocess.check_output(['git','status','--short'],cwd=roots['baseline'],text=True)==''
 changed=sorted(n for n in set(frozen['baseline'])|set(frozen['candidate']) if n.startswith('src/main/') and frozen['baseline'].get(n)!=frozen['candidate'].get(n))
 assert changed==['src/main/scala/core/ooo/IntegerBackend.scala','src/main/scala/core/ooo/RegisteredRequestQueue.scala'],changed
 assert all(frozen['baseline'][n]==frozen['candidate'][n] for n in extra)
 receipt=dict(status='RUNNING',base_commit=BASE_COMMIT,source_inputs=frozen,production_changed=changed,
  runner_sha256=sha(Path(__file__)),gsim_sha256=sha(a.gsim),commands=[],arms={})
 env={**os.environ,'JAVA_TOOL_OPTIONS':'-XX:ActiveProcessorCount=2','ASAN_OPTIONS':'detect_leaks=0','UBSAN_OPTIONS':'halt_on_error=1'}
 def save():(o/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
 def run(label,cmd,cwd=ROOT,negative=None):
  assert all(inputs(root)==frozen[arm] for arm,root in roots.items()),'source drift'
  log=o/(label+'.log');t=time.monotonic()
  with log.open('x') as f:p=subprocess.run(list(map(str,cmd)),cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=1800)
  text=log.read_text(errors='replace');receipt['commands'].append(dict(label=label,exit=p.returncode,seconds=round(time.monotonic()-t,3),sha256=sha(log)));save()
  assert p.returncode==(1 if negative else 0) and (not negative or negative in text),label+'\n'+text[-6000:]
  print(label,'PASS',flush=True);return text
 save()
 try:
  for arm,root in roots.items():
   d=o/arm;top='ReadyStoreQuery77BackendGsim'
   run(arm+'-emit',['mill','-i','-j','2','IonSoC.test.runMain','ooo.ProofControlBackendMain',d,'cleanup'],cwd=root)
   run(arm+'-generate',[a.gsim,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(d),d/(top+'.fir')])
   flags=['clang++-19','-std=c++20','-O1','-g0','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(d),'-I'+str(root/'simulator/gsim/ready_store_query77')]
   objs=[]
   for i,p in enumerate(sorted(d.glob(top+'[0-9]*.cpp'))):
    obj=p.with_suffix('.o');run(arm+'-compile-'+str(i),[*flags,'-c',p,'-o',obj]);objs.append(obj)
   assert objs;binary=d/'run'
   run(arm+'-link',[*flags,root/extra[0],*objs,'-ldl','-o',binary])
   log=run(arm+'-positive',[binary])
   receipt['arms'][arm]=dict(metrics=re.findall(r'^C0_LIFECYCLE_METRICS .*$',log,re.M),actual_core=json.loads((d/'actual-core.json').read_text()),fir_sha256=sha(d/(top+'.fir')))
   assert len(receipt['arms'][arm]['metrics'])==4
   run(arm+'-retirement-negative',[binary,'--mutate-retirement'],negative='fault/killed/duplicate retirement')
   save()
  assert receipt['arms']['baseline']['metrics']==receipt['arms']['candidate']['metrics'],'cycles/accepted/physical/response/credit duty changed'
  assert receipt['arms']['baseline']['actual_core']==receipt['arms']['candidate']['actual_core']
  receipt['status']='PASS_EXACT_PROFILE_BACKEND_LIFECYCLE_AB';save()
 except BaseException as e:
  receipt.update(status='FAILED_PRESERVE_EVIDENCE',failure=str(e));save();raise
if __name__=='__main__':main()
