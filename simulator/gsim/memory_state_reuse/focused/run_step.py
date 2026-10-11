#!/usr/bin/env python3
"""Explicit one-slot focused stages, source/classpath/tool bound; no board build."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,shutil,signal,subprocess,sys,time
HERE=Path(__file__).resolve().parent;BASE=HERE.parent;SOURCE=BASE/'memory-state-reuse-implementation-20261011-r1/source'
NATIVE=BASE/'memory-state-reuse-native-20261011-r1';MODEL=HERE/'model-on-on-r1';TOP='PostedPreparationPriorityGsim'
sys.path.insert(0,str(BASE/'frontier-fetch-chain-cpu-prep-r1'))
from resource_monitor import samples
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_text())
def execute(name,argv,seconds,expected=0):
 log=HERE/(name+'.log');receipt=HERE/(name+'.receipt.json');res=HERE/(name+'.resources.jsonl')
 assert not log.exists() and not receipt.exists(),'fresh stage namespace required'
 assert shutil.disk_usage(HERE).free>740*1024**2,'740MiB initial disk floor'
 source=read(NATIVE/'source-freeze.json');assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip()==source['git_head']
 for file,value in source['files'].items():assert sha(SOURCE/file)==value,'source changed '+file
 runtime=read(NATIVE/'execution/runtime-binding.json')
 for file,value in runtime['files'].items():assert sha(file)==value,'compiled runtime changed'
 for path,files in runtime['directories'].items():
  assert {str(f.relative_to(path)):sha(f)for f in Path(path).rglob('*')if f.is_file()}==files,'compiled directory changed'
 tool=read(BASE/'toolchain/tool-receipt.json')['files']
 for entry in tool.values():assert sha(entry['path'])==entry['sha256'],'tool drift'
 start=time.monotonic();peak=0;guard=None
 bound_inputs = [Path(__file__), *MODEL.glob(TOP+'*.cpp'), MODEL/(TOP+'.h')] if name.startswith('compile-') else [p for p in HERE.iterdir() if p.suffix in('.py','.cpp','.h')]
 inputs={str(p):sha(p) for p in bound_inputs if p.is_file()}
 env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0','CHISEL_FIRTOOL_PATH':str(BASE/'toolchain/env/firtool-1.135.0')}
 with log.open('x')as out,res.open('x')as stats:
  p=subprocess.Popen(argv,cwd=SOURCE,stdout=out,stderr=subprocess.STDOUT,start_new_session=True,env=env)
  print(json.dumps({'started':name,'pid':p.pid,'executable':argv[0]}),flush=True)
  while p.poll()is None:
   row={'seconds':time.monotonic()-start,**samples(p.pid)};peak=max(peak,row['observed_process_tree_RSS_KiB']);stats.write(json.dumps(row)+'\n');stats.flush()
   if row['seconds']>seconds:guard='wall_timeout'
   elif shutil.disk_usage(HERE).free<700*1024**2:guard='700MiB_disk_floor'
   elif log.stat().st_size>32*1024**2:guard='32MiB_log_cap'
   if guard:os.killpg(p.pid,signal.SIGTERM);p.wait();break
   time.sleep(1)
 r={'schema':'memory-state-reuse-focused-step-v1','name':name,'argv':argv,'source_commit':source['git_head'],'source_tree':source['git_tree'],'source_freeze_sha256':sha(NATIVE/'source-freeze.json'),'runtime_binding_sha256':sha(NATIVE/'execution/runtime-binding.json'),'inputs':inputs,'inputs_unchanged':all(sha(f)==v for f,v in inputs.items()),'seconds':time.monotonic()-start,'peak_RSS_KiB':peak,'exit':p.returncode,'expected':expected,'guard':guard,'log_sha256':sha(log)}
 receipt.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({k:r[k] for k in ['name','seconds','peak_RSS_KiB','exit','guard','inputs_unchanged']}),flush=True)
 assert p.returncode==expected and guard is None and r['inputs_unchanged'],'stage failed or input drift'
 return r

def main():
 a=argparse.ArgumentParser();a.add_argument('phase',choices=['elab','generate','compile','host','run']);a.add_argument('--slot-granted',action='store_true');a.add_argument('--attempt',default='r1');a.add_argument('--case',default='main');a.add_argument('--negative');x=a.parse_args();assert x.slot_granted,'explicit coordinator slot required'
 tool=read(BASE/'toolchain/tool-receipt.json')['files'];MODEL.mkdir(exist_ok=True)
 runtime=read(NATIVE/'execution/runtime-binding.json');java=read(NATIVE/'plan.json')['java']
 flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(MODEL),'-I'+str(HERE)]
 if x.phase=='elab':execute('elab-'+x.attempt,[java,'-Xmx2g','-XX:ActiveProcessorCount=2','-Dchisel.project.root='+str(SOURCE),'-cp',':'.join(runtime['paths']),'ooo.MemoryStateReuseGsimMain',str(MODEL),'on','on'],900)
 elif x.phase=='generate':execute('generate-'+x.attempt,[tool['gsim']['path'],'--threads=1','--dir='+str(MODEL),str(MODEL/(TOP+'.fir'))],900)
 elif x.phase=='compile':
  for i,p in enumerate(sorted(MODEL.glob(TOP+'[0-9]*.cpp'))):execute('compile-'+x.attempt+'-'+str(i),[tool['clang']['path'],*flags,'-c',str(p),'-o',str(p.with_suffix('.o'))],1800)
 elif x.phase=='host':execute('host-'+x.attempt,[tool['clang']['path'],*flags,'-DPREPARATION_PRIORITY_ON=1',str(HERE/'memory_state_reuse.cpp'),*[str(p)for p in sorted(MODEL.glob(TOP+'[0-9]*.o'))],'-ldl','-o',str(MODEL/('host-'+x.attempt))],180)
 else:execute('run-'+x.attempt+'-'+x.case+('-negative-'+x.negative if x.negative else ''),[str(MODEL/('host-'+x.attempt)),'--case',x.case]+(['--inject-'+x.negative]if x.negative else []),120,1 if x.negative else 0)
if __name__=='__main__':main()
