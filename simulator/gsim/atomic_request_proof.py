#!/usr/bin/env python3
"""Focused atomic FIFO A/B transport, independent host oracle and negative controls."""
import argparse,hashlib,json,os,re,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--output',type=Path,required=True);ap.add_argument('--gsim',type=Path,required=True)
 a=ap.parse_args();o=a.output.resolve();o.mkdir(parents=True,exist_ok=False);os.nice(10)
 inputs={str(p.relative_to(ROOT)):sha(p) for p in ROOT.glob('src/**/*.scala')}
 for p in [Path(__file__),ROOT/'simulator/gsim/harness/atomic_request_proof.cpp']:inputs[str(p.relative_to(ROOT))]=sha(p)
 env={**os.environ,'JAVA_TOOL_OPTIONS':os.environ.get('JAVA_TOOL_OPTIONS','')+' -XX:ActiveProcessorCount=2','ASAN_OPTIONS':'detect_leaks=0','UBSAN_OPTIONS':'halt_on_error=1'}
 receipt=dict(status='RUNNING',source_inputs=inputs,gsim_sha256=sha(a.gsim),commands=[])
 def save():(o/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
 def run(label,cmd,negative=None):
  assert all(sha(ROOT/n)==h for n,h in inputs.items()),'source drift'
  log=o/(label+'.log');start=time.monotonic()
  with log.open('x') as f:p=subprocess.run(list(map(str,cmd)),cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=1800)
  text=log.read_text(errors='replace');receipt['commands'].append(dict(label=label,exit=p.returncode,seconds=round(time.monotonic()-start,3),sha256=sha(log)));save()
  assert p.returncode==(1 if negative else 0) and (not negative or negative in text),label+'\n'+text[-6000:]
  print(label,'PASS',flush=True);return text
 save()
 try:
  d=o/'fifo';top='AtomicRequestProofGsim'
  run('emit',['mill','-i','-j','2','IonSoC.test.runMain','ooo.AtomicRequestProofGsimMain',d])
  fir=(d/(top+'.fir')).read_text();m=re.search(r'outHandle : UInt<(\d+)>',fir);assert m
  receipt['return_handle_bits']=int(m[1])
  run('generate',[a.gsim,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(d),d/(top+'.fir')])
  flags=['clang++-19','-std=c++20','-O1','-g0','-fsanitize=address,undefined','-fno-sanitize-recover=all','-DHANDLE_MASK='+str((1<<int(m[1]))-1),'-I'+str(d)]
  objs=[]
  for i,p in enumerate(sorted(d.glob(top+'[0-9]*.cpp'))):
   obj=p.with_suffix('.o');run('compile-'+str(i),[*flags,'-c',p,'-o',obj]);objs.append(obj)
  assert objs;binary=d/'run'
  run('link',[*flags,ROOT/'simulator/gsim/harness/atomic_request_proof.cpp',*objs,'-ldl','-o',binary])
  receipt['positive']=run('positive',[binary])
  run('stale-token-negative',[binary,'stale-token'],'independent stale token oracle mismatch')
  run('permission-negative',[binary,'permission'],'independent permission oracle mismatch')
  run('canonical-negative',[binary,'canonical'],'independent canonical oracle mismatch')
  run('frozen-negative',[binary,'frozen'],'independent frozen oracle mismatch')
  receipt['status']='PASS_ATOMIC_FIFO_AB_HOST_ORACLE';save()
 except BaseException as e:
  receipt.update(status='FAILED_PRESERVE_EVIDENCE',failure=str(e));save();raise
if __name__=='__main__':main()
