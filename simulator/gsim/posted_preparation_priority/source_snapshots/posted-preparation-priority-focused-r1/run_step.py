#!/usr/bin/env python3
"""Single explicitly granted resource step; immutable per-step logs and receipts."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,signal,subprocess,sys,time
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
SOURCE=BASE/'posted-preparation-priority-implementation-r1/config-source'
sys.path.insert(0,str(BASE/'frontier-fetch-chain-cpu-prep-r1'))
from resource_monitor import samples

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def execute(name,argv,timeout,cwd=SOURCE,expect=0):
 log=HERE/(name+'.log');rec=HERE/(name+'.receipt.json');resource=HERE/(name+'.resources.jsonl')
 assert not log.exists() and not rec.exists(),'fresh per-step namespace required'
 assert shutil.disk_usage(HERE).free>740*1024**2,'740MiB initial disk floor'
 started=time.monotonic();reason=None;peak=0
 executable=Path(argv[0]);execution_sha=sha(executable)if executable.is_absolute()and executable.is_file()else None
 host_sha=sha(HERE/'posted_preparation_priority.cpp');wrapper_sha=sha(SOURCE/'src/test/scala/ooo/PostedPreparationPriorityGsim.scala')
 with log.open('x')as out,resource.open('x')as stats:
  p=subprocess.Popen(argv,cwd=cwd,stdout=out,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
  while p.poll()is None:
   row={'elapsed_seconds':time.monotonic()-started,**samples(p.pid)};peak=max(peak,row['observed_process_tree_RSS_KiB']);stats.write(json.dumps(row)+'\n');stats.flush()
   if time.monotonic()-started>timeout:reason='wall_timeout'
   elif shutil.disk_usage(HERE).free<700*1024**2:reason='700MiB_disk_floor'
   elif log.stat().st_size>32*1024**2:reason='32MiB_log_floor'
   if reason:os.killpg(p.pid,signal.SIGTERM);p.wait();break
   time.sleep(1)
 r={'schema':'posted-preparation-priority-step-v1','name':name,'argv':list(map(str,argv)),'cwd':str(cwd),'exit_code':p.returncode,'expected_exit':expect,'guard':reason,'seconds':time.monotonic()-started,'peak_sampled_process_tree_RSS_KiB':peak,'log':str(log),'log_sha256':sha(log),'resources':str(resource),'production_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip(),'wrapper_sha256':sha(SOURCE/'src/test/scala/ooo/PostedPreparationPriorityGsim.scala'),'host_sha256':host_sha,'binary_sha256':execution_sha,'binary_unchanged':execution_sha is None or sha(executable)==execution_sha,'host_unchanged':sha(HERE/'posted_preparation_priority.cpp')==host_sha,'tool_receipt_sha256':sha(BASE/'toolchain/tool-receipt.json')}
 rec.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r),flush=True)
 assert reason is None and p.returncode==expect and r['binary_unchanged']and r['host_unchanged'],'step failed, mutated or guard aborted'
 return r

def main():
 a=argparse.ArgumentParser();a.add_argument('phase',choices=['elab','generate','compile-model','host','run']);a.add_argument('--side',choices=['off','on'],required=True);a.add_argument('--attempt',default='r1');a.add_argument('--slot-granted',action='store_true');a.add_argument('--case',default='main');a.add_argument('--negative',choices=['data','token','timing']);x=a.parse_args();assert x.slot_granted,'coordinator resource slot required'
 out=HERE/('model-'+x.side+'-r1');out.mkdir(exist_ok=True);tool=json.loads((BASE/'toolchain/tool-receipt.json').read_text())['files'];cc=tool['clang']['path'];top='PostedPreparationPriorityGsim';prefix=x.phase+'-'+x.side+'-'+x.attempt
 flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(out)]
 if x.phase=='elab':argv=['bash','-lc',f'source {BASE}/toolchain/activate.sh\nexec mill -i IonSoC.test.runMain ooo.{top}Main {out} {x.side}'];execute(prefix,argv,900)
 elif x.phase=='generate':execute(prefix,[tool['gsim']['path'],'--threads=1','--dir='+str(out),str(out/(top+'.fir'))],900)
 elif x.phase=='compile-model':
  for index,src in enumerate(sorted(out.glob(top+'[0-9]*.cpp'))):execute(prefix+'-'+str(index),[cc,*flags,'-c',str(src),'-o',str(src.with_suffix('.o'))],1800)
 elif x.phase=='host':execute(prefix,[cc,*flags,'-DPREPARATION_PRIORITY_ON='+str(int(x.side=='on')),str(HERE/'posted_preparation_priority.cpp'),*[str(p)for p in sorted(out.glob(top+'[0-9]*.o'))],'-ldl','-o',str(out/('host-'+x.attempt))],180)
 else:
  name=prefix+'-'+x.case+('-negative-'+x.negative if x.negative else '');argv=[str(out/('host-'+x.attempt)),'--case',x.case,'--trace',str(HERE/(name+'.jsonl'))]+(['--inject-'+x.negative]if x.negative else[]);execute(name,argv,120,expect=1 if x.negative else 0)
if __name__=='__main__':main()
