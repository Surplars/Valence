#!/usr/bin/env python3
"""Source/runtime-bound serial native export only; no model compilation or simulation."""
from pathlib import Path
import argparse,gzip,hashlib,importlib.util,json,os,shutil,signal,subprocess,time
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
SOURCE=BASE/'distinct-way-release-implementation-20261011-r1/source';CPU=BASE/'distinct-way-release-cpu-20261011-r1'
OUT=HERE/'execution';MIB=1024**2
read=lambda p:json.loads(Path(p).read_text())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):Path(p).write_text(json.dumps(v,indent=2,sort_keys=True)+'\n')
def need(ok,msg):
 if not ok:raise RuntimeError(msg)
def inv(p):return {str(x.resolve()):sha(x) for x in sorted(Path(p).rglob('*')) if x.is_file()}
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def guard(p):
 need(subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip()==p['head'],'source head drift')
 need(not subprocess.check_output(['git','status','--porcelain'],cwd=SOURCE,text=True).strip(),'dirty source')
 for n,h in p['production_files'].items():need(sha(SOURCE/n)==h,'source bytes drift '+n)
 for n,h in p['runtime']['files'].items():need(sha(n)==h,'jar drift '+n)
 for n,v in p['runtime']['directories'].items():need(inv(n)==v,'runtime classes/resources drift '+n)
 for n in p['runtime']['absent']:need(not Path(n).exists(),'resource appeared '+n)
 for n,h in p['bound_files'].items():need(sha(n)==h,'bound input drift '+n)
def run():
 need(not OUT.exists(),'fresh native output required');need(shutil.disk_usage(HERE).free>=950*MIB,'start free floor')
 p=read(CPU/'pins.json');p={k:p[k] for k in ['head','tree','production_files','runtime','java','compiler','tools','canonical_flags']}
 p['bound_files']={str(x.resolve()):sha(x) for x in [Path(__file__),*sorted((HERE/'fixture').glob('*.scala')),*sorted((HERE/'helpers').glob('*.py')),CPU/'pins.json',CPU/'expected-profile-off.json',CPU/'expected-profile-on.json']}
 for x in [p['java']['path'],p['compiler'],p['tools']['firtool']['path']]:p['bound_files'][x]=sha(x)
 save(HERE/'pins.json',p);guard(p);OUT.mkdir();state={'status':'RUNNING','pins_sha256':sha(HERE/'pins.json'),'steps':[],'output_cap_bytes':80*MIB,'disk_floor_bytes':700*MIB,'simulation':False,'mapped_PPA_STA':False};save(OUT/'receipt.json',state)
 env={k:v for k,v in os.environ.items() if k not in ['JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','LD_PRELOAD','LD_LIBRARY_PATH','PYTHONPATH']}
 env.update(JAVA_TOOL_OPTIONS='-Dfile.encoding=UTF-8',LD_LIBRARY_PATH=str(BASE/'toolchain/env/sysroot/usr/lib/x86_64-linux-gnu'),LC_ALL='C.UTF-8')
 def stage(label,cmd):
  guard(p);log=OUT/(label+'.log');started=time.monotonic();reason=None
  print('RUN '+label,flush=True)
  with log.open('x') as stream:
   proc=subprocess.Popen(list(map(str,cmd)),cwd=SOURCE,env=env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
   while proc.poll() is None:
    if shutil.disk_usage(HERE).free<700*MIB:reason='disk floor'
    if sum(x.stat().st_size for x in HERE.rglob('*') if x.is_file())>80*MIB:reason='output cap'
    if time.monotonic()-started>300:reason='wall timeout'
    if reason:os.killpg(proc.pid,signal.SIGTERM);break
    time.sleep(0.5)
   proc.wait(timeout=10)
  state['steps'].append({'label':label,'command':list(map(str,cmd)),'cwd':str(SOURCE),'seconds':time.monotonic()-started,'exit':proc.returncode,'guard':reason,'log_sha256':sha(log)})
  save(OUT/'receipt.json',state);need(proc.returncode==0 and not reason,'stage failed '+label);print('PASS '+label,flush=True)
 java=p['java']['path'];cp=p['runtime']['paths'];classes=OUT/'fixture-classes';classes.mkdir()
 try:
  stage('wrapper-compile',[java,'-Xmx2g','-XX:ActiveProcessorCount=2','-cp',':'.join([p['compiler'],*cp]),'scala.tools.nsc.Main','-classpath',':'.join(cp),'-d',classes,HERE/'fixture/DistinctWayReleaseNativeMain.scala'])
  state['fixture_classes']=inv(classes);save(OUT/'receipt.json',state)
  for mode in ['off','on']:
   need(inv(classes)==state['fixture_classes'],'wrapper changed')
   dest=OUT/mode;flags=sorted(p['canonical_flags']+(['--distinct-way-release'] if mode=='on' else []))
   stage(mode+'-constructors',[java,'-Xmx2g','-XX:ActiveProcessorCount=2','-Dchisel.project.root='+str(SOURCE),'-cp',':'.join([str(classes),*cp]),'ooo.DistinctWayReleaseNativeMain',dest,mode,*flags])
   profile=read(dest/'profile.json');actual=read(dest/'actual-parameters.json')
   need(profile==read(CPU/('expected-profile-'+mode+'.json')),'CPU/native full profile differs')
   need(actual['entryProfile']==profile['profile'] and actual['expectedCore']==profile['core'] and actual['canonicalOptions']==flags,'native actual entry differs')
   for key,part,n in [('coreParameters','core',6),('cacheConcurrency','cache',3),('ddrParameters','ddr',2)]:need(len(actual[key])==n and all(x['values']==profile[part] for x in actual[key]),'native constructor mismatch '+key)
   fir=dest/'FpgaNextSocTop.fir';firhash=sha(fir);firbytes=fir.stat().st_size
   rtl=dest/'rtl';rtl.mkdir()
   stage(mode+'-native',[p['tools']['firtool']['path'],fir,'--format=fir','--split-verilog','--strip-debug-info','--disable-all-randomization','--default-layer-specialization=disable','-o',rtl])
   compressed=gzip.compress(fir.read_bytes(),mtime=0);need(hashlib.sha256(gzip.decompress(compressed)).hexdigest()==firhash,'FIR lossless check');(dest/'FpgaNextSocTop.fir.gz').write_bytes(compressed);fir.unlink()
   save(dest/'receipt.json',{'status':'PASS_NATIVE_EXPORT_ONLY','head':p['head'],'tree':p['tree'],'fir_sha256':firhash,'fir_bytes':firbytes,'actual_sha256':sha(dest/'actual-parameters.json'),'profile_sha256':sha(dest/'profile.json'),'artifacts':inv(dest),'pins_sha256':sha(HERE/'pins.json')})
  guard(p);state['status']='PASS_TWO_FRESH_NATIVE_EXPORTS_ONLY'
 except BaseException as e:state['status']='FAIL';state['error']=str(e);raise
 finally:save(OUT/'receipt.json',state)
 print(state['status'],flush=True)
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--slot-granted',action='store_true');a=ap.parse_args();need(a.slot_granted,'coordinator slot required');run()
