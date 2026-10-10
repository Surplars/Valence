"""Host executor; isolated original-model or explicitly pinned object-retry verifier."""
import subprocess,sys,json
from pathlib import Path
from contract import load,require,sha
_ORIGIN=Path(__file__).resolve().parent.parent/'posted-preparation-priority-cpu-prep-r1'
sys.path.insert(0,str(_ORIGIN))
_frozen=load('_frontier_frozen_command_executor',_ORIGIN/'model.py')
def measured(q):
 result=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('stage_measure.py'))],input=json.dumps(q),capture_output=True,text=True)
 require(result.stdout,'measured stage produced no receipt: '+result.stderr[-4000:])
 r=json.loads(result.stdout);require(result.returncode==0 and r['status']=='PASS','measured stage failed: '+str(r.get('error'))+' resources='+str(r.get('resources')))
 r['result']['stage_resources']=r['resources'];r['result']['measurement_path']=q['measurement'];r['result']['measurement_sha256']=sha(q['measurement'])
 return r['result']
def execute(cmd,log,seconds,cwd=_frozen.ROOT,expected=0,extra_env=None,artifact_limit_bytes=None):
 return measured(dict(stage='command',cmd=list(map(str,cmd)),log=str(log),seconds=seconds,cwd=str(cwd),expected=expected,extra_env=extra_env,artifact_limit_bytes=artifact_limit_bytes,measurement=str(log)+'.resources.json'))
def validate_measured(out,side,case):
 return measured(dict(stage='validate',out=str(out),side=side,case=case,measurement=str(Path(out)/'validation.resources.json')))
_OBJECT_DIR=_ORIGIN.parent/'posted-preparation-priority-cpu-object-r1'
def verify(path,digest):
 path=Path(path).resolve();require(sha(path)==digest,'model terminal receipt pin mismatch');r=json.loads(path.read_text())
 names={'posted-preparation-priority-compiled-object-v1':'compile_stage.py','posted-preparation-priority-literal-object-model-v1':'object_stage.py'}
 require(r.get('schema') in names,'unsupported new object model schema');verifier=_OBJECT_DIR/names[r['schema']]
 require(sha(_OBJECT_DIR/'VERIFIER-PINS.json')=='65931c61ae4032058c4d234555349985dd5bcb40274adcd205fbd964f0a97842','object verifier pin inventory changed');pins=json.loads((_OBJECT_DIR/'VERIFIER-PINS.json').read_text());require(sha(verifier)==pins[verifier.name],'new object verifier changed')
 result=subprocess.run([sys.executable,'-B',str(verifier),'verify','--receipt',str(path),'--sha256',digest],cwd=_ORIGIN.parent,capture_output=True,text=True)
 require(result.returncode==0,'isolated new object model verifier failed: '+result.stderr[-4000:]);return json.loads(result.stdout)
