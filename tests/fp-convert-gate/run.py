#!/usr/bin/env python3
"""Focused FIR -> GSIM -> independent C++ FP gates; no CPU build or RTL simulator."""
import argparse,hashlib,json,os,shutil,subprocess,sys,time
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('gate',choices=['convert','misc','tag64']);p.add_argument('--out',type=Path,required=True);p.add_argument('--classpath',required=True,help='Pinned Scala/compiler/Chisel, current production and HardFloat classpath');p.add_argument('--plugin',type=Path,required=True);p.add_argument('--java',default='java');p.add_argument('--gsim',default='gsim');p.add_argument('--cxx',default='clang++');p.add_argument('--vectors',type=Path);p.add_argument('--negative',action='store_true');p.add_argument('--shared-source',type=Path,help='Same-checkout FloatingPointToIntegerShared.scala for source negatives');a=p.parse_args();here=Path(__file__).resolve().parent;out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();R={'status':'RUNNING','simulator':'GSIM','full_cpu':False,'synthesis':False,'gate':a.gate,'commands':[]}
def run(cmd,log,negative=False,marker=''):
 t=time.time();r=subprocess.run(list(map(str,cmd)),capture_output=True,text=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=300);s=r.stdout+r.stderr;log.write_text(s);R['commands'].append({'argv':list(map(str,cmd)),'returncode':r.returncode,'seconds':time.time()-t,'log':str(log.relative_to(out)),'sha256':sha(log)})
 assert not any(x in s for x in ['ERROR: AddressSanitizer','UndefinedBehaviorSanitizer','runtime error:']),s
 if negative:assert r.returncode!=0 and marker in s and 'ORACLE_BASELINE_MISMATCH' not in s,s
 else:assert r.returncode==0,s
 return s
try:
 vectors=None
 if a.gate!='tag64':
  vectors=a.vectors.resolve() if a.vectors else out/'vectors/tests/vectors.txt'
  if not a.vectors:run([sys.executable,here/'make_vectors.py',out/'vectors'],out/'vectors.log')
  assert vectors.is_file();R['vectors_sha256']=sha(vectors)
 top='FpConvertGsim' if a.gate=='convert' else 'FpMiscGsim';sources=[here/(top+'.scala')]
 if a.gate!='convert':sources+=[here/'FloatingPointMiscBaseline.scala']
 R['test_sources']={x.name:sha(x) for x in [*sources,here/('convert.cpp' if a.gate=='convert' else 'misc.cpp'),here/'make_vectors.py']}
 kinds=['positive']
 if a.negative:
  assert a.gate!='misc','Negatives are convert and tag64 only'
  kinds+=['truncate_without_clip','nx_not_suppressed'] if a.gate=='convert' else ['truncate_tag64']
 for kind in kinds:
  d=out/kind;d.mkdir();classes=d/'classes';classes.mkdir();src=list(sources)
  if kind!='positive':
   if a.gate=='convert':
    original=(a.shared_source or here.parents[1]/'src/main/scala/core/ooo/FloatingPointToIntegerShared.scala').resolve();s=original.read_text()
    old,new=('io.out32 := Mux(invalid32,clipped32,wide.io.out(31,0))','io.out32 := wide.io.out(31,0)') if kind=='truncate_without_clip' else ('!invalid32 && wide.io.intExceptionFlags(0)','wide.io.intExceptionFlags(0)');assert s.count(old)==1
    mutant=d/'FloatingPointToIntegerShared.scala';mutant.write_text(s.replace(old,new));src.append(mutant)
   else:
    original=here/'FpMiscGsim.scala';s=original.read_text();old='u.request.bits.command.token.tag:=io.token';new='u.request.bits.command.token.tag:=(if(isCandidate) io.token(15,0) else io.token)';assert s.count(old)==1
    mutant=d/'FpMiscGsim.scala';mutant.write_text(s.replace(old,new));src[0]=mutant
   (d/'mutation.json').write_text(json.dumps({'original_sha256':sha(original),'mutant_sha256':sha(mutant),'old':old,'new':new,'replacement_count':1,'original_oracle_unchanged':True},indent=2))
  run([a.java,'-Xmx3g','-XX:ActiveProcessorCount=2','-cp',a.classpath,'scala.tools.nsc.Main','-language:reflectiveCalls','-Xplugin:'+str(a.plugin.resolve()),'-classpath',a.classpath,'-d',classes,*src],d/'scala.log')
  run([a.java,'-Xmx3g','-XX:ActiveProcessorCount=2','-cp',str(classes)+os.pathsep+a.classpath,'soc.core.ooo.'+top+'Main',d]+([] if a.gate=='convert' else ['64' if a.gate=='tag64' else '16']),d/'emit.log')
  run([a.gsim,'--threads=1','--dir='+str(d),d/(top+'.fir')],d/'generate.log')
  run([a.cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-DTAG_BITS='+('64' if a.gate=='tag64' else '16'),'-I'+str(d),*sorted(d.glob(top+'[0-9]*.cpp')),here/('convert.cpp' if a.gate=='convert' else 'misc.cpp'),'-ldl','-o',d/'run'],d/'cxx.log')
  s=run([d/'run']+([vectors] if vectors else []),d/'result.log',kind!='positive','CANDIDATE_MISMATCH' if a.gate=='convert' else 'MISC_BASELINE_MISMATCH');print(kind,s.strip(),flush=True)
 R['status']='PASS_GSIM_COMPONENT_ONLY'
except Exception as e:R.update(status='FAIL',error=str(e));raise
finally:
 R['artifacts']={str(x.relative_to(out)):sha(x) for x in out.rglob('*') if x.is_file() and x.name!='run' and x.suffix!='.class'};(out/'receipt.json').write_text(json.dumps(R,indent=2)+'\n')
