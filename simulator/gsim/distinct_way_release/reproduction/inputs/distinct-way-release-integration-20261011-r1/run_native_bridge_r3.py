#!/usr/bin/env python3
"""Bound direct-scalac/native equivalence bridge; no GSIM generation or DUT execution."""
from pathlib import Path
import argparse, copy, gzip, hashlib, json, os, shutil, signal, subprocess, threading, time
HERE=Path(__file__).resolve().parent; BASE=HERE.parent; SOURCE=HERE/'source'; OUT=HERE/'native-bridge-r3'
CANDIDATE=BASE/'distinct-way-release-implementation-20261011-r1/source'
NATIVE=BASE/'distinct-way-release-native-20261011-r1'; CPU=BASE/'distinct-way-release-cpu-20261011-r1'
MIB=1024**2; CAP=80*MIB; FLOOR=700*MIB
FLAGS=['reconstructIssueTokenIndex','sharedMemoryAddressState']
FIRTOOL=['--format=fir','--split-verilog','--strip-debug-info','--disable-all-randomization','--default-layer-specialization=disable']
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(b):return hashlib.sha256(b).hexdigest()
def save(p,j):Path(p).write_text(json.dumps(j,indent=2,sort_keys=True)+'\n')
def need(ok,msg):
 if not ok:raise RuntimeError(msg)
def inventory(d):return {str(p.resolve()):sha(p) for p in sorted(Path(d).rglob('*')) if p.is_file()}
def relative_inventory(d):return {str(p.relative_to(d)):sha(p) for p in sorted(Path(d).rglob('*')) if p.is_file()}
def size(d):return sum(p.stat().st_size for p in Path(d).rglob('*') if p.is_file()) if Path(d).exists() else 0
def git(*args):return subprocess.check_output(['git',*args],cwd=SOURCE)
def reserve21():
 d=CPU/'case21'; c=read(CPU/'case21-contract.json')
 return 0 if (d/'qualification.json').exists() else max(0,c['output_cap_bytes']-size(d))
def budget():
 used=size(OUT); free=shutil.disk_usage(HERE).free; remaining21=reserve21()
 return {'used':used,'free':free,'remaining_case21':remaining21,'remaining_bridge':max(0,CAP-used),'available_after_reservations':free-FLOOR-remaining21-max(0,CAP-used)}
def freeze():
 need(not OUT.exists(),'fresh bridge directory required');need(not git('status','--porcelain'),'dirty integration')
 old=read(NATIVE/'pins.json'); cp=[]; inputs={str(Path(__file__)):sha(__file__),str(HERE/'bridge-test-source-list.json'):sha(HERE/'bridge-test-source-list.json')}
 for name in old['runtime']['paths']:
  p=Path(name)
  if p.suffix=='.jar':cp.append(name);inputs[name]=sha(p);need(inputs[name]==old['runtime']['files'][name],'pinned jar drift')
  elif p.is_dir() and 'HardFloatLib/compile.dest/classes' in name:
   need(inventory(p)==old['runtime']['directories'][name],'HardFloat runtime drift');cp.append(name);inputs.update(inventory(p))
 for part in ['src/main/resources','src/test/resources']:
  p=SOURCE/part
  if p.exists():cp.append(str(p));inputs.update(inventory(p))
 reused=HERE/'native-bridge-r2/classes';old_compile=read(HERE/'native-bridge-r2/receipt.json');old_pins=read(HERE/'native-bridge-r2/pins.json')
 need(inventory(reused)==old_compile['classes'],'r2 classes changed')
 need([(x['label'],x['exit'],x['guard']) for x in old_compile['steps'][:2]]==[('direct-scalac',0,None),('config',0,None)],'r2 source compile/config unavailable')
 cp.insert(0,str(reused));inputs.update(inventory(reused))
 for x in ['pins.json','receipt.json','direct-scalac.log','config.log']:
  q=HERE/'native-bridge-r2'/x;inputs[str(q)]=sha(q)
 repaired=['src/test/scala/ooo/CanonicalVirtualStoreActualParamsMain.scala','src/test/scala/ooo/DistinctWayReleaseNativeMain.scala']
 for name in old_pins['source_paths']:
  if name not in repaired:need(sha(SOURCE/name)==old_pins['inputs'][str(SOURCE/name)],'reused source/class binding changed '+name)
 compiler=old['compiler'];java=old['java']['path'];firtool=old['tools']['firtool']['path']
 option_file=CANDIDATE/'out/IonSoC/allScalacOptions.json';opts=read(option_file)['value'];inputs[str(option_file)]=sha(option_file)
 need(opts[0].startswith('-Xplugin:'),'missing Chisel plugin');plugin=Path(opts[0].split(':',1)[1])
 for p in [Path(java),Path(compiler),Path(firtool),plugin]:inputs[str(p)]=sha(p)
 need(sha(java)==old['java']['sha256'],'java drift')
 need(sha(firtool)==old['bound_files'][firtool],'firtool drift')
 need(sha(compiler)==old['bound_files'][compiler],'compiler drift')
 sources=sorted(str(p.relative_to(SOURCE)) for p in (SOURCE/'src/main/scala').rglob('*.scala'))+read(HERE/'bridge-test-source-list.json')
 inputs.update({str(SOURCE/n):sha(SOURCE/n) for n in sources})
 for mode in ['off','on']:
  for name in ['profile.json','actual-parameters.json','receipt.json','FpgaNextSocTop.fir.gz']:
   p=NATIVE/'execution'/mode/name;inputs[str(p)]=sha(p)
  inputs.update(inventory(NATIVE/'execution'/mode/'rtl'))
 b=budget();need(b['available_after_reservations']>=0,'admission reservation fails: '+str(b))
 p={'schema':'distinct-way-integration-direct-native-bridge-v3','prior_failures':{k:sha(HERE/k/'receipt.json') for k in ['native-bridge-r1','native-bridge-r2']},'head':git('rev-parse','HEAD').decode().strip(),'tree':git('rev-parse','HEAD^{tree}').decode().strip(),'main_tree':git('rev-parse','HEAD:src/main').decode().strip(),'source_paths':sources,'inputs':inputs,'java':java,'compiler':compiler,'classpath':cp,'scalac_options':opts,'firtool':firtool,'canonical_flags':old['canonical_flags'],'output_cap_bytes':CAP,'disk_floor_bytes':FLOOR,'admission_budget':b,'reused_classes_source_head':old_pins['head'],'reused_classes_receipt_sha256':sha(HERE/'native-bridge-r2/receipt.json'),'recompiled_test_sources':repaired,'direct_scalac_not_mill':True,'hardware_execution':False,'resource_flags':dict.fromkeys(FLAGS,False)}
 OUT.mkdir();save(OUT/'pins.json',p);return p

def guard(p):
 need(git('rev-parse','HEAD').decode().strip()==p['head'],'integration HEAD drift');need(not git('status','--porcelain'),'dirty integration')
 for n,h in p['inputs'].items():need(sha(n)==h,'bound input drift '+n)

def run():
 p=freeze();guard(p);state={'status':'RUNNING','pins_sha256':sha(OUT/'pins.json'),'steps':[],'direct_scalac_not_mill':True,'hardware_execution':False,'output_cap_bytes':CAP,'disk_floor_bytes':FLOOR};save(OUT/'receipt.json',state)
 env={k:v for k,v in os.environ.items() if k not in ['JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','LD_PRELOAD','LD_LIBRARY_PATH','PYTHONPATH']};env.update(JAVA_TOOL_OPTIONS='-Dfile.encoding=UTF-8',LD_LIBRARY_PATH=str(BASE/'toolchain/env/sysroot/usr/lib/x86_64-linux-gnu'),LC_ALL='C.UTF-8',TMPDIR=str(OUT/'tmp'))
 (OUT/'tmp').mkdir();classes=OUT/'classes';classes.mkdir()
 def stage(label,cmd,input_gzip=None):
  guard(p);log=OUT/(label+'.log');start=time.monotonic();reason=None;peak=0;feed_error=[];thread=None
  print('RUN '+label,flush=True)
  with log.open('x') as stream:
   proc=subprocess.Popen(list(map(str,cmd)),cwd=SOURCE,env=env,stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.PIPE if input_gzip else None,start_new_session=True)
   if input_gzip:
    def feed():
     try:
      with gzip.open(input_gzip,'rb') as src:shutil.copyfileobj(src,proc.stdin,MIB)
     except BaseException as e:feed_error.append(repr(e))
     finally:proc.stdin.close()
    thread=threading.Thread(target=feed,daemon=True);thread.start()
   while proc.poll() is None:
    b=budget();peak=max(peak,b['used'])
    if b['used']>CAP:reason='80 MiB output cap'
    elif b['free']<FLOOR:reason='700 MiB disk floor'
    elif b['available_after_reservations']<0:reason='case21 plus bridge reservation'
    elif time.monotonic()-start>300:reason='300 second stage wall cap'
    if reason:os.killpg(proc.pid,signal.SIGTERM);break
    time.sleep(.25)
   try:proc.wait(timeout=10)
   except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
   if thread:thread.join(timeout=10)
  item={'label':label,'argv':list(map(str,cmd)),'cwd':str(SOURCE),'environment':{k:env[k] for k in ['JAVA_TOOL_OPTIONS','LD_LIBRARY_PATH','LC_ALL','TMPDIR']},'exit':proc.returncode,'guard':reason,'seconds':time.monotonic()-start,'peak_output_bytes':peak,'log_sha256':sha(log),'stdin_gzip_sha256':sha(input_gzip) if input_gzip else None,'feed_errors':feed_error}
  state['steps'].append(item);save(OUT/'receipt.json',state);need(proc.returncode==0 and not reason and not feed_error,'stage failed '+label);guard(p);print('PASS '+label,flush=True)
 try:
  cp=':'.join(p['classpath']);java=[p['java'],'-Xmx2g','-XX:ActiveProcessorCount=2']
  stage('repaired-test-scalac',[*java,'-cp',':'.join([p['compiler'],*p['classpath']]),'scala.tools.nsc.Main',*p['scalac_options'],'-classpath',cp,'-d',classes,*[SOURCE/x for x in p['recompiled_test_sources']]])
  state['classes']=inventory(classes);state['classes_bytes']=size(classes);save(OUT/'receipt.json',state)
  runtime=':'.join([str(classes),*p['classpath']])
  state['configuration_tests']={'status':'PASS_SOURCE_IDENTICAL_REUSE','tests':16,'receipt_sha256':sha(HERE/'native-bridge-r2/receipt.json'),'log_sha256':sha(HERE/'native-bridge-r2/config.log')}
  state['modes']={}
  for mode in ['off','on']:
   need(inventory(classes)==state['classes'],'fresh classes drift');dest=OUT/mode;flags=sorted(p['canonical_flags']+(['--distinct-way-release'] if mode=='on' else []))
   stage(mode+'-constructors',[*java,'-Dchisel.project.root='+str(SOURCE),'-cp',runtime,'ooo.DistinctWayReleaseNativeMain',dest,mode,*flags])
   profile=read(dest/'profile.json');actual=read(dest/'actual-parameters.json');old_profile=read(NATIVE/'execution'/mode/'profile.json');old_actual=read(NATIVE/'execution'/mode/'actual-parameters.json')
   stripped=copy.deepcopy(profile)
   for part in ['profile','core','storage']:
    for key in FLAGS:need(stripped[part].pop(key) is False,'resource flag not explicit false')
   need(stripped==old_profile,'full native profile differs beyond two false resource fields')
   stripped_actual=copy.deepcopy(actual)
   for item in [stripped_actual['entryProfile'],stripped_actual['expectedCore'],*[x['values'] for x in stripped_actual['coreParameters']]]:
    for key in FLAGS:need(item.pop(key) is False,'actual resource flag not false')
   need(stripped_actual==old_actual,'complete actual constructor audit differs beyond two false resource fields')
   raw_path=dest/'FpgaNextSocTop.fir';raw=raw_path.read_bytes();fir_hash=digest(raw);fir_bytes=len(raw)
   fir=dest/'FpgaNextSocTop.fir.gz';fir.write_bytes(gzip.compress(raw,mtime=0));need(gzip.decompress(fir.read_bytes())==raw,'FIR lossless compression failed');raw_path.unlink()
   old_raw=gzip.decompress((NATIVE/'execution'/mode/'FpgaNextSocTop.fir.gz').read_bytes());fir_equal=raw==old_raw
   need(not list(dest.glob('*.fir')),'unexpected raw FIR at rest')
   rtl=dest/'rtl';rtl.mkdir();stage(mode+'-native',[p['firtool'],'-',*FIRTOOL,'-o',rtl],fir)
   fresh=relative_inventory(rtl);old=relative_inventory(NATIVE/'execution'/mode/'rtl');differences=sorted(k for k in fresh.keys()|old.keys() if fresh.get(k)!=old.get(k))
   info={'profile_sha256':sha(dest/'profile.json'),'actual_sha256':sha(dest/'actual-parameters.json'),'fir_sha256':fir_hash,'fir_bytes':fir_bytes,'fir_gzip_sha256':sha(fir),'candidate_fir_sha256':digest(old_raw),'raw_fir_identical':fir_equal,'raw_native_files':fresh,'raw_native_file_count':len(fresh),'raw_native_differences':differences,'native_normalization_rules':[],'all_actual_constructor_fields_correspond':True,'only_added_metadata':dict.fromkeys(FLAGS,False)}
   save(dest/'comparison.json',info);state['modes'][mode]=info;save(OUT/'receipt.json',state);need(not differences,'native raw modules differ: '+str(differences))
  off=read(OUT/'off/profile.json');on=read(OUT/'on/profile.json')
  need(on['profile']['distinctWayRelease'] is True and on['cache']['distinctWayRelease'] is True,'ON flag absent')
  on['profile']['distinctWayRelease']=False;on['cache']['distinctWayRelease']=False
  need(on==off,'OFF/ON final profiles differ beyond distinctWayRelease')
  guard(p);state['status']='PASS_DIRECT_SCALAC_CONFIG_AND_EXACT_NATIVE_PAIR_BRIDGE';state['retained_bytes']=size(OUT);state['budget']=budget();need(state['retained_bytes']<=CAP,'final output cap');state['scope']='Direct scalac and actual native constructor/raw-module bridge only; no new hardware runtime, no joint resource-ON CPU, no mapped PPA/STA.'
 except BaseException as e:state['status']='FAIL';state['error']=str(e);raise
 finally:save(OUT/'receipt.json',state)
 print(state['status'],flush=True)
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--slot-granted',action='store_true');args=parser.parse_args();need(args.slot_granted,'coordinator slot required');run()
