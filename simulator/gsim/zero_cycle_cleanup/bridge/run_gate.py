#!/usr/bin/env python3
"""Bounded serial real-manager paired gate. Requires coordinator heavy-slot grant."""
import argparse,hashlib,json,os,re,shutil,signal,subprocess,time
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--freeze',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
 ap.add_argument('--reuse-emits',type=Path);ap.add_argument('--toolchain',type=Path,required=True);ap.add_argument('--stop-after',choices=['config','emit','generate','sanitized','native'],default='native')
 a=ap.parse_args();root=Path(__file__).resolve().parent;source=a.source.resolve();out=a.output.resolve();tool=a.toolchain.resolve()
 freeze=json.loads(a.freeze.read_text())
 for name,digest in freeze['files'].items():assert sha(source/name)==digest,('frozen source drift',name)
 for name,digest in freeze['verification_inputs'].items():assert sha(root/name)==digest,('verification input drift',name)
 out.mkdir(parents=True,exist_ok=False)
 activate=tool/'activate.sh';mill=tool/'bin/mill';gsim=tool/'gsim-src/build/gsim/gsim';cxx=tool/'sysroot/usr/bin/clang++-19';firtool=tool/'firtool-1.135.0/firtool'
 state={'status':'RUNNING','freeze':str(a.freeze.resolve()),'freeze_sha256':sha(a.freeze),'source_files':freeze['files'],
  'tools':{n:{'path':str(p),'sha256':sha(p)} for n,p in [('activate',activate),('mill',mill),('gsim',gsim),('cxx',cxx),('firtool',firtool)]},
  'runner_sha256':sha(Path(__file__)),'verification_inputs':freeze['verification_inputs'],'commands':[],'completed':[],
  'scope':'Two paired real-manager component geometries plus standalone native OFF/ON; no whole SoC.'}
 receipt=out/'receipt.json'
 def save():receipt.write_text(json.dumps(state,indent=2)+'\n')
 def run(label,argv,timeout=600,expected=0,anchor=None):
  log=out/(label+'.log');assert not log.exists();begin=time.monotonic();print('START',label,flush=True)
  with log.open('x') as stream:
   env=dict(os.environ);env['ASAN_OPTIONS']='detect_leaks=0'
   process=subprocess.Popen(['/bin/bash','--noprofile','--norc','-c','source "$1"; shift; exec "$@"','bridge-gate',str(activate),*map(str,argv)],cwd=source,stdout=stream,stderr=subprocess.STDOUT,env=env,start_new_session=True)
   print('PID',label,process.pid,flush=True)
   try:
    # Resource usage is collected without polling a live shell process.
    def expired(signum,frame):raise TimeoutError(label+' exceeded '+str(timeout)+' seconds')
    previous=signal.signal(signal.SIGALRM,expired);signal.alarm(timeout)
    _,status,usage=os.wait4(process.pid,0);process.returncode=os.waitstatus_to_exitcode(status)
   except BaseException:
    os.killpg(process.pid,signal.SIGKILL);process.wait();raise
   finally:signal.alarm(0);signal.signal(signal.SIGALRM,previous)
  text=log.read_text();item={'label':label,'argv':list(map(str,argv)),'exit':process.returncode,'seconds':round(time.monotonic()-begin,3),'max_rss_KiB':usage.ru_maxrss,'log_sha256':sha(log),'expected':expected,'anchor':anchor};state['commands'].append(item);save()
  if expected=='nonzero':
   assert process.returncode!=0,(label,'negative did not fail')
   assert re.search(r'ACTUAL_CORRUPTION count=[1-9][0-9]*',text),(label,'positive mutation marker absent')
   assert 'ERROR: AddressSanitizer' not in text and 'runtime error:' not in text,(label,'sanitizer failed instead of oracle')
  else:assert process.returncode==expected,(label,'failed',str(log))
  if anchor:assert (any(item in text for item in anchor) if isinstance(anchor,list) else anchor in text),(label,'expected anchor missing',anchor)
  print('PASS',label,'seconds',item['seconds'],flush=True)
 def done(stage):
  state['completed'].append(stage);state['status']=stage.upper()+'_PASS';save()
  return a.stop_after==stage
 try:
  reuse=a.reuse_emits.resolve() if a.reuse_emits else None
  if reuse:
   previous=json.loads((reuse/'receipt.json').read_text())
   assert 'emit' in previous['completed'], 'reuse source did not complete emission'
   assert previous['source_files'].keys()==freeze['files'].keys(),'reuse source file set mismatch'
   differences={n for n in freeze['files'] if freeze['files'][n]!=previous['source_files'][n]}
   assert differences<={'simulator/gsim/harness/bridge_payload_enable.cpp','simulator/gsim/harness/bridge_payload_memory.h'}, ('reused emission input mismatch',differences)
   state['host_only_reuse_changes']={n:{'before':previous['source_files'][n],'after':freeze['files'][n]} for n in sorted(differences)}
   assert previous['tools']==state['tools'],'reused emission tool mismatch'
   state['reused_emit_receipt']={'path':str(reuse/'receipt.json'),'sha256':sha(reuse/'receipt.json'),'artifacts':{}}
   state['completed'].append('config')
   def reuse_file(p,dest):
    assert p.is_file();dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    state['reused_emit_receipt']['artifacts'][str(p.relative_to(reuse))]=sha(p)
  else:
   run('focused-config',[mill,'-i','-j','1','IonSoC.test.testOnly','ooo.LocalPayloadWriteEnableConfigSpec'],timeout=600)
   if done('config'):return
  for name,bits in [('primary',3),('oversize',4)]:
   raw=out/name/'raw';raw.mkdir(parents=True)
   if reuse:reuse_file(reuse/name/'raw/BridgePayloadEnablePairGsim.fir',raw/'BridgePayloadEnablePairGsim.fir')
   else:run(name+'-emit',[mill,'-i','-j','1','IonSoC.test.runMain','ooo.BridgePayloadEnablePairGsimMain',raw,str(bits)],timeout=240)
   model=out/name/'model';model.mkdir()
   run(name+'-instrument',['python3',root/'fixture/instrument_pair_state.py',raw/'BridgePayloadEnablePairGsim.fir',model/'BridgePayloadEnablePairGsim.fir','--manifest',out/name/'state-manifest.json'],timeout=30)
  for side,value in [('off',0),('on',1)]:
   native=out/'native'/side;native.mkdir(parents=True)
   if reuse:
    for f in ('TileLinkAxi4OutstandingBridge.fir','actual-constructors.json'):reuse_file(reuse/'native'/side/f,native/f)
   else:run(side+'-native-emit',[mill,'-i','-j','1','IonSoC.test.runMain','ooo.BridgePayloadEnableNativeMain',native,str(value)],timeout=240)
  if done('emit'):return
  for name in ('primary','oversize'):
   model=out/name/'model'
   run(name+'-generate',[gsim,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(model),model/'BridgePayloadEnablePairGsim.fir'],timeout=240)
   run(name+'-header-syntax',[cxx,'-std=c++20','-fsyntax-only','-I'+str(model),'-DTL_SIZE_BITS='+('3' if name=='primary' else '4'),source/'simulator/gsim/harness/bridge_payload_enable.cpp'],timeout=120)
  if done('generate'):return
  controls=json.loads((root/'fixture/negative_matrix.json').read_text())['negatives']
  for name in ('primary','oversize'):
   model=out/name/'model';objects=[]
   flags=['-std=c++20','-O1','-g1','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(model),'-DTL_SIZE_BITS='+('3' if name=='primary' else '4')]
   sources=sorted(model.glob('BridgePayloadEnablePairGsim[0-9]*.cpp'))+[source/'simulator/gsim/harness/bridge_payload_enable.cpp']
   assert len(sources)>1,'GSIM source list empty'
   for i,p in enumerate(sources):
    obj=model/(str(i)+'.o');objects.append(obj);run(name+'-compile-'+str(i),[cxx,*flags,'-c',p,'-o',obj],timeout=240)
   run(name+'-link',[cxx,*flags,*objects,'-ldl','-o',model/'run'],timeout=120)
   runtime=[] if name=='primary' else ['--oversize-only']
   anchor='BRIDGE_PAYLOAD_ENABLE_PASS' if name=='primary' else 'BRIDGE_PAYLOAD_OVERSIZE_PASS'
   run(name+'-positive',[model/'run',*runtime],timeout=120,anchor=anchor)
   if name=='primary':
    for entry in controls:
     run('negative-'+entry['mode'],[model/'run',*entry['args']],timeout=120,expected='nonzero',anchor=entry['anchors_any'])
  if done('sanitized'):return
  for side in ('off','on'):
   native=out/'native'/side;rtl=native/'rtl';rtl.mkdir()
   run(side+'-native-lower',[firtool,native/'TileLinkAxi4OutstandingBridge.fir','--format=fir','--split-verilog','--strip-debug-info','--disable-all-randomization','--default-layer-specialization=disable','-o',rtl],timeout=180)
  run('native-audit',['python3',root/'native_audit.py','--root',out/'native'],timeout=60,anchor='PASS_NATIVE_LOCAL_PAYLOAD_ENABLE')
  assert all(sha(source/n)==d for n,d in freeze['files'].items()),'source drift during gate'
  state['artifacts']={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p!=receipt and p.suffix not in ('.o',)}
  done('native');state['status']='PASS_COMPONENT_AND_NATIVE';save()
 except BaseException as error:
  state['status']='FAILED';state['error']=repr(error);save();raise
 finally:save()
if __name__=='__main__':main()
