#!/usr/bin/env python3
"""Build one fresh actual Board; no setup/install, no runtime, no historical pass reuse."""
import argparse,signal,time,resource
from resource_monitor import samples
from contract import *
def cumulative_model_bytes():
 seen=set();total=0
 for d in HERE.iterdir():
  if d.is_dir() and d.name.startswith(('generated-','model-')):
   for f in d.rglob('*'):
    if f.is_file():
     st=f.stat();key=(st.st_dev,st.st_ino)
     if key not in seen:seen.add(key);total+=st.st_size
 return total

def execute(cmd,log,seconds,cwd=ROOT,expected=0,extra_env=None,artifact_limit_bytes=None):
 log=Path(log);require(not log.exists(),'fresh log required');require(shutil.disk_usage(log.parent).free>740*1024**2,'740MiB starting disk floor')
 started=time.monotonic();reason=None;next_sample=started;peak=0;observations=0;hwm={};before=resource.getrusage(resource.RUSAGE_CHILDREN)
 samplelog=log.with_suffix(log.suffix+'.resources.jsonl')
 with log.open('x')as f,samplelog.open('x')as raw:
  p=subprocess.Popen(list(map(str,cmd)),cwd=cwd,stdout=f,stderr=subprocess.STDOUT,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0',**(extra_env or {})},start_new_session=True)
  while p.poll()is None:
   if time.monotonic()>=next_sample:
    row=dict(elapsed_seconds=time.monotonic()-started,**samples(p.pid));raw.write(json.dumps(row)+'\n');raw.flush();observations+=1;next_sample=time.monotonic()+1;peak=max(peak,row['observed_process_tree_RSS_KiB'])
    for x in row['processes']:
     if x['VmHWM_KiB'] is not None:hwm[str(x['pid'])]=max(hwm.get(str(x['pid']),0),x['VmHWM_KiB'])
   if time.monotonic()-started>seconds:reason='wall_timeout'
   elif shutil.disk_usage(log.parent).free<700*1024**2:reason='700MiB_disk_floor'
   elif log.stat().st_size>32*1024**2:reason='32MiB_log_cap'
   elif cumulative_model_bytes()>360*1024**2:reason='360MiB_pair_unique_inode_budget'
   elif (ROOT/'out').exists() and sum(f.stat().st_size for f in (ROOT/'out').rglob('*') if f.is_file())>45*1024**2:reason='45MiB_Mill_out_budget'
   elif artifact_limit_bytes is not None and sum(f.stat().st_size for f in log.parent.rglob('*')if f.is_file())>artifact_limit_bytes:reason='model_artifact_budget'
   if reason:os.killpg(p.pid,signal.SIGTERM);p.wait();break
   time.sleep(.25)
 if artifact_limit_bytes is not None and sum(f.stat().st_size for f in log.parent.rglob('*')if f.is_file())>artifact_limit_bytes:reason='model_artifact_budget'
 after=resource.getrusage(resource.RUSAGE_CHILDREN)
 r=dict(resource_log=str(samplelog),resource_log_sha256=sha(samplelog),resource_samples=observations,observed_peak_process_tree_RSS_KiB=peak,observed_process_HWM_KiB=hwm,cumulative_waited_child_maxRSS_KiB_before=before.ru_maxrss,cumulative_waited_child_maxRSS_KiB_after=after.ru_maxrss,waited_child_user_seconds=after.ru_utime-before.ru_utime,waited_child_system_seconds=after.ru_stime-before.ru_stime,resource_scope='Per-stage sampled process tree; cumulative waited-child maxRSS separately labeled. Sampling may miss transient peaks.',argv=list(map(str,cmd)),cwd=str(cwd),environment=extra_env or {},exit=p.returncode,expected=expected,seconds=time.monotonic()-started,guard=reason,log=str(log),log_sha256=sha(log))
 require(not reason and p.returncode==expected and not re.search(SANITIZERS,log.read_text()),'command failure '+str(r));return r
def closure():
 # Existing immutable cached dependency artifacts, not newly fetched source or guessed package versions.
 cache=Path(os.environ['COURSIER_CACHE']);files=sorted(cache.rglob('*.jar'))
 require(files,'no existing Scala dependency jars')
 return {str(p):sha(p)for p in files}
def bind(out):
 t=tools();d=dict(schema='posted-preparation-priority-board-binding-v1',source=source(),tools=t,tool_receipt_sha256=TOOL_SHA,activate_sha256=sha(BASE/'toolchain/activate.sh'),environment=environment(),environment_normalization=ENVIRONMENT_NORMALIZATION,inputs=model_inputs(),canonical_flags=read(HERE/'canonical-flags.json'),expected_profiles={s:expected_profile(s)for s in PROFILES},dependency_jars=closure(),python={'path':str(Path(sys.executable).resolve()),'sha256':sha(sys.executable),'version':sys.version},historical_pass_inherited=False)
 pair_profiles(d['expected_profiles']['off'],d['expected_profiles']['on']);save(out,d,True);return {'status':'BOUND_NOT_ELABORATED','path':str(out),'sha256':sha(out)}
def check_binding(path,digest):
 require(sha(path)==digest,'binding pin mismatch');b=read(path)
 require(b['schema']=='posted-preparation-priority-board-binding-v1'and exact(b['source'],source())and exact(b['tools'],tools())and b['tool_receipt_sha256']==TOOL_SHA,'source/tool drift')
 require(b['environment_normalization']==ENVIRONMENT_NORMALIZATION and exact(b['environment'],environment())and exact(b['inputs'],model_inputs()),'environment or model runner drift')
 require(b['activate_sha256']==sha(BASE/'toolchain/activate.sh'),'activation script drift')
 require(exact(b['dependency_jars'],closure()),'Scala dependency closure changed')
 require(b['python']=={'path':str(Path(sys.executable).resolve()),'sha256':sha(sys.executable),'version':sys.version},'python changed')
 return b
def plan(side,out,binding):
 d=Path(out).resolve();ts=binding['tools']['files']
 return [[ts['mill_wrapper']['path'],'-i','-j','1','IonSoC.test.runMain','ooo.PostedPreparationPriorityCpuGsimMain',str(d),side,*binding['canonical_flags'][side]], [ts['gsim']['path'],'--threads=1','--dir='+str(d),str(d/'BoardSocGsim.fir')], [ts['clang']['path'],*FLAGS,'-I'+str(d),'-c',str(d/'BoardSocGsim0.cpp'),'-o',str(d/'BoardSocGsim0.o')]]
def build(path,digest,side,out,slot):
 require(slot,'coordinator heavy slot required');b=check_binding(path,digest);out=Path(out).resolve();require(not out.exists(),'fresh model output required');out.mkdir(parents=True)
 r=dict(schema='posted-preparation-priority-board-model-v1',status='RUNNING',side=side,binding_path=str(Path(path).resolve()),binding_sha256=digest,steps=[],historical_pass_inherited=False,model_rebuilt=True,actual_runtime=False,compiler_flags=FLAGS,artifact_limit_bytes=180*1024**2)
 try:
  cmds=plan(side,out,b)
  for i,cmd in enumerate(cmds):
   r['steps'].append(execute(cmd,out/('step'+str(i)+'.log'),1800,artifact_limit_bytes=r['artifact_limit_bytes']));save(out/'receipt.json',r)
   if i==0:profile(read(out/'profile.json'),side);audit(read(out/'actual-parameters.json'),read(out/'profile.json'),side)
   if i==1:
    require({p.name for p in out.glob('BoardSocGsim[0-9]*.cpp')}=={'BoardSocGsim0.cpp'},'unexpected generated translation units');r['actual_contract']=header_and_fir(out,side)
  check_binding(path,digest);r['status']='PASS_FRESH_ACTUAL_BOARD_MODEL_ONLY'
 except BaseException as e:r['status']='FAIL';r['error']=str(e);raise
 finally:r['artifacts']={p.name:sha(p)for p in out.iterdir()if p.is_file()and p.name!='receipt.json'};save(out/'receipt.json',r)
 return {'status':r['status'],'receipt':str(out/'receipt.json'),'sha256':sha(out/'receipt.json')}
def verify(path,digest):
 path=Path(path).resolve();require(sha(path)==digest,'model terminal pin mismatch');r=read(path);b=check_binding(r['binding_path'],r['binding_sha256']);d=path.parent
 require(r['schema']=='posted-preparation-priority-board-model-v1'and r['status']=='PASS_FRESH_ACTUAL_BOARD_MODEL_ONLY'and r['historical_pass_inherited']is False and r['actual_runtime']is False and r['model_rebuilt']is True,'model not fresh terminal')
 require(r['compiler_flags']==FLAGS and len(r['steps'])==3 and r['artifact_limit_bytes']==180*1024**2,'model steps/flags/budget')
 require(sum(f.stat().st_size for f in d.rglob('*')if f.is_file())<=r['artifact_limit_bytes'],'model budget exceeded')
 for n,h in r['artifacts'].items():require((d/n).resolve().parent==d and sha(d/n)==h,'model artifact drift '+n)
 require({p.name for p in d.glob('BoardSocGsim*.o')}=={'BoardSocGsim0.o'},'object inventory drift')
 for s,cmd in zip(r['steps'],plan(r['side'],d,b)):
  require(s['argv']==cmd and s['cwd']==str(ROOT)and s['environment']=={} and s['exit']==s['expected']==0 and s['guard']is None and sha(s['log'])==s['log_sha256'],'model command/terminal drift')
 require(exact(r['actual_contract'],header_and_fir(d,r['side'])),'actual model profile/header/parameters drift');return r
def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='action',required=True)
 q=s.add_parser('bind');q.add_argument('--out',type=Path,required=True)
 for name in ('check','plan','build'):
  q=s.add_parser(name);q.add_argument('--binding',type=Path,required=True);q.add_argument('--sha256',required=True)
  if name!='check':q.add_argument('--side',choices=PROFILES,required=True);q.add_argument('--out',type=Path,required=True)
  if name=='build':q.add_argument('--slot-granted',action='store_true')
 q=s.add_parser('verify');q.add_argument('--receipt',type=Path,required=True);q.add_argument('--sha256',required=True)
 a=p.parse_args()
 if a.action=='bind':r=bind(a.out)
 elif a.action=='check':check_binding(a.binding,a.sha256);r={'status':'PASS_BINDING_ONLY'}
 elif a.action=='plan':r=plan(a.side,a.out,check_binding(a.binding,a.sha256))
 elif a.action=='build':r=build(a.binding,a.sha256,a.side,a.out,a.slot_granted)
 else:r=verify(a.receipt,a.sha256)
 print(json.dumps(r,indent=2))
if __name__=='__main__':main()
