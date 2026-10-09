#!/usr/bin/env python3
"""New source/tool-bound PF gates. Never inherits the lost workspace's PASS."""
import argparse,hashlib,importlib.util,json,os,re,shutil,signal,subprocess,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
RECOVERY=ROOT.parent
TOOLS=RECOVERY/'toolchain-recovery/tool-files.json'
MIB=1024**2
SANITIZER=r'AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|LeakSanitizer'
def require(ok,why):
 if not ok:raise RuntimeError(why)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def inputs():
 names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
 return {n:sha(ROOT/n) for n in names if n and (ROOT/n).is_file()}
def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--stage',choices=['cache'],default='cache');ap.add_argument('--output',type=Path,required=True);ap.add_argument('--slot-granted',action='store_true');ap.add_argument('--tool-files',type=Path,default=TOOLS,help='receipt for already installed tools; no installation');a=ap.parse_args()
 require(a.slot_granted,'explicit one serial heavy slot required')
 require(not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT),'freeze and commit source first')
 out=a.output.resolve();require(not out.exists(),'fresh attempt output required');require(shutil.disk_usage(ROOT).free>=780*MIB,'80MiB budget plus700MiB floor')
 tool_receipt=a.tool_files.resolve();require(tool_receipt.is_file(),'missing installed-tool receipt')
 bound=inputs();t=json.loads(tool_receipt.read_text());tool=t['files'];
 for x in tool.values():require(sha(x['path'])==x['sha256'],'restored tool drift')
 cxx=tool['clang']['path'];gsim=tool['gsim']['path'];mill=tool['mill_wrapper']['path']
 require(os.environ.get('COURSIER_CACHE') and os.environ.get('JAVA_TOOL_OPTIONS') and os.environ.get('CHISEL_FIRTOOL_PATH'),'source restored activate.sh')
 require(shutil.which('mill')==mill,'activated Mill path mismatch')
 out.mkdir(parents=True);r={'schema':'valence-store-prefetch-insertion-cache-gate-v1','status':'RUNNING','stage':a.stage,'source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'inputs':bound,'tool_files':t,'tool_files_sha256':sha(tool_receipt),'tool_files_receipt_path':str(tool_receipt),'steps':[],'models':{},'historical_pass_inherited':False}
 def save():(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
 def step(name,cmd,anchor=None,code=0,timeout=600):
  require(inputs()==bound,'source changed before step');log=out/(name+'.log');now=time.monotonic();reason=None
  with log.open('x') as stream:
   p=subprocess.Popen(list(map(str,cmd)),cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0','PYTHONDONTWRITEBYTECODE':'1'})
   while p.poll() is None:
    if shutil.disk_usage(ROOT).free<700*MIB:reason='disk-floor'
    if sum(f.stat().st_size for f in out.rglob('*') if f.is_file())>80*MIB:reason='output-budget'
    if time.monotonic()-now>timeout:reason='bounded-timeout'
    if reason:
     os.killpg(p.pid,signal.SIGTERM)
     try:p.wait(timeout=8)
     except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
     break
    time.sleep(.5)
  text=log.read_text();r['steps'].append({'name':name,'command':list(map(str,cmd)),'actual_exit':p.returncode,'expected_exit':code,'guard':reason,'seconds':time.monotonic()-now,'log_sha256':sha(log)});save()
  require(not reason and p.returncode==code and (anchor is None or anchor in text),'step failed '+name)
  require(not re.search(SANITIZER,text),'sanitizer failure '+name);require(inputs()==bound,'source changed during step');return text
 def model(name,main,top,driver,params=(),defs=(),negatives=()):
  d=out/name;d.mkdir();step(name+'-emit',[mill,'-i','-j','1','IonSoC.test.runMain',main,d,*params])
  step(name+'-generate',[gsim,'--threads=1','--dir='+str(d),d/(top+'.fir')])
  if top=='CoherentCacheHomeGsim':
   spec=importlib.util.spec_from_file_location('occupancy',ROOT/'simulator/gsim/mshr_occupancy.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
   header=d/(top+'.h');bad=mod.validate(ROOT,header,2,'cache$');caught=False
   try:mod.validate(ROOT,bad,2,'cache$')
   except AssertionError:caught=True
   require(caught,'corrupt generated schema escaped');r['models'][name]={'schema_positive':True,'schema_negative':True};save()
  flags=['-std=c++20','-O1','-g','-gz=zlib','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(d),'-I'+str(ROOT/'simulator/gsim/harness'),'-I'+str(HERE),*['-D'+x for x in defs]]
  objects=[]
  for src in sorted(d.glob(top+'[0-9]*.cpp')):
   obj=src.with_suffix('.o');step(name+'-compile-'+src.stem,[cxx,*flags,'-c',src,'-o',obj]);objects.append(obj)
  require(objects,'generated no actual model')
  step(name+'-link',[cxx,*flags,HERE/driver,*objects,'-ldl','-o',d/'run'])
  result=step(name+'-positive',[d/'run'],timeout=180)
  for option,anchor in negatives:
   neg=step(name+'-'+option[2:],[d/'run',option],anchor,code=1,timeout=180)
   if option=='--inject-wb-prefetch-aba':require('STORE_PREFETCH_INSERTION_MUTATION_TRIGGER wb-prefetch-aba' in neg,'ABA negative did not trigger')
   if option in ('--inject-insertion-expectation','--inject-read-origin-mru'):require('STORE_PREFETCH_INSERTION_MUTATION_TRIGGER insertion-expectation' in neg,'insertion negative did not trigger')
  r['models'].setdefault(name,{})['artifacts']={p.relative_to(out).as_posix():sha(p) for p in d.iterdir() if p.is_file()};save();return result
 try:
  save()
  step('config',[mill,'-i','-j','1','IonSoC.test.testOnly','ooo.StorePrefetchInsertionSpec'],'All tests passed',timeout=900)
  step('host-policy',[os.sys.executable,HERE/'test_selection.py'],'PASS')
  host=out/'replacement-oracle'
  step('host-oracle-compile',[cxx,'-std=c++20','-O1','-g','-gz=zlib','-fsanitize=address,undefined','-fno-sanitize-recover=all',HERE/'replacement_oracle.cpp','-o',host])
  step('host-oracle-positive',[host],'HOST_ORACLE_PASS checks=472')
  for mutation,reason in {'store-lru':'store PF A/B conflict selected wrong victim','read-mru':'read-origin prefetch must remain oldest with both policies','live-origin':'out-of-order fill changed owner origin','stale-demand':'demand inherited freed PF origin','error-touches':'error changed replacement metadata'}.items():
   step('host-oracle-'+mutation,[host,'--mutate-'+mutation],reason,code=1)

  for on in (0,1):
   neg=[('--inject-mismatch','CPU independent byte oracle mismatch'),('--inject-wb-prefetch-aba','WB capture stale-PF ABA origin mismatch'),('--inject-insertion-expectation','A-next full-PA victim disagrees with authored insertion expectation'),('--inject-read-origin-mru','A-next full-PA victim disagrees with authored insertion expectation')]
   text=model('cache-'+str(on),'ooo.StorePrefetchInsertionGsimMain','CoherentCacheHomeGsim','cache.cpp',[on],['CHECKED_STORE_PREFETCH=1','STORE_PF_MRU_ON='+str(on),'READ_MSHRS=2','CACHE_LINES=512','RESPONSE_ENTRIES=2','AXI_SLOTS=4','MIXED_MODEL=1','MIXED_RTL=1'],negatives=neg)
   require('STORE_PREFETCH_INSERTION_PASS store_pf=1 store_pf_mru='+str(on)+' cases=6 read_origin_stays_lru=1' in text,'cache marker')
   marker='STORE_PREFETCH_INSERTION_TWO_CONFLICT_PASS store_pf=1 store_pf_mru='+str(on)+' store_origin=1 read_origin=1 full_pa_victim=1 later_store_admission=1 dirty_probe_dma=1 reacquire=1 full_flush=1 performance_qualification=0'
   require(text.splitlines().count(marker)==1,'new actual conflicts missing/duplicated')
   require(len([x for x in text.splitlines() if x.startswith('STORE_PREFETCH_INSERTION_CONFLICT ')])==2,'actual conflict records missing/duplicated')
  require(inputs()==bound,'final source drift')
  for x in tool.values():require(sha(x['path'])==x['sha256'],'final tool drift')
  r['status']='PASS_STORE_PREFETCH_INSERTION_CACHE'
 except BaseException as e:r['status']='FAIL';r['error']=str(e);raise
 finally:save()
 print(r['status'],out/'receipt.json')
if __name__=='__main__':main()
