#!/usr/bin/env python3
"""Portable B2 source-bound qualification: fresh OLD backend and two fresh NEW models."""
import argparse, hashlib, json, os, re, shutil, subprocess, time
from pathlib import Path
import bound_store_replay_common as portable
ROOT=Path(__file__).resolve().parents[2]
MODELS={
 'oldbackend':('PendingStoreProofBackendGsim','backend',['1','0']),
 'slots':('BoundHeadStoreOverlapGsim','slots',['1']),
 'backend':('PendingStoreProofBackendGsim','backend',['1','1']),
}
BASE_FLAGS=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all']
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def inputs():
 files=[Path(__file__),ROOT/'simulator/gsim/harness/pending_store_proof_reference.h']
 files += list((ROOT/'simulator/gsim/harness').glob('bound_head_store_overlap_*.cpp'))
 return portable.source_inputs(ROOT,files)

def main():
 global ROOT
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('stage',choices=['freeze','config','emit','generate','sanitized'])
 ap.add_argument('--output',type=Path,required=True);ap.add_argument('--models',default='oldbackend,slots,backend');portable.add_paths(ap,ROOT)
 args=ap.parse_args();ROOT=args.source_root.resolve()
 tools=portable.tool_paths(args,ap);MILL=tools['mill'];GSIM=tools['gsim'];CXX=tools['cxx']
 models=args.models.split(',');assert models and len(set(models))==len(models) and all(m in MODELS for m in models)
 out=args.output.resolve();receipt_path=out/'receipt.json'
 if portable.preflight(args,inputs(),tools):return
 if args.stage=='freeze':
  source=inputs();out.mkdir(parents=True,exist_ok=False)
  r={'status':'SOURCE_FROZEN','models':models,'source_commit':portable.source_revision(ROOT),
   'inputs':source,'inputs_sha256':digest(source),'runner_sha256':sha(__file__),'flags':BASE_FLAGS,
   'tools':portable.tool_binding(tools),'schema':'bound-store-portable-stage-v1','commands':[],
   'scope':'Fresh OLD B-prime ON1 and NEW same profile with only boundHeadStoreOverlap enabled; dedicated saved-operation ParallelLSU contracts.',
   'limitations':['No historical qualification inherited. OLD is built from this source freeze; bank/transport are separate gates.',
    'No full ISA/CPU performance/board/Vivado/routed claim. Component synthetic qualifier is trusted backend input, not arbitrary forged ROB membership.',
    'Combined ASan+UBSan O1; LSan disabled because ptrace; official GSIM split model translation units compiled sequentially.']}
  receipt_path.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({'status':r['status'],'inputs_sha256':r['inputs_sha256'],'receipt':str(receipt_path)}));return
 r=json.loads(receipt_path.read_text());assert r['models']==models and r['inputs']==inputs(),'source drift'
 assert r['schema']=='bound-store-portable-stage-v1','historical receipts are evidence only'
 assert r['tools']==portable.tool_binding(tools),'tool drift'
 assert not r['status'].endswith('_FAILED'),'fresh output required after failure'
 if r.get('model_artifacts'):portable.verify_model_inputs(out,r['model_artifacts'])
 prerequisite={'generate':'emit','sanitized':'generate'}.get(args.stage)
 if prerequisite:assert prerequisite in r.get('completed_stages',[]),'missing stage: '+prerequisite
 def save():receipt_path.write_text(json.dumps(r,indent=2)+'\n')
 def run(label,argv,anchor=None,negative=False,corrupt=False):
  portable.check_tools(r['tools'])
  assert r['inputs']==inputs(),'source drift';path=out/(label+'.log');assert not path.exists(),'preserve prior evidence; freeze a fresh revision'
  started=time.monotonic()
  with path.open('x') as log:
   proc=subprocess.Popen(portable.command_args(argv,tools),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0:halt_on_error=1','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'})
   _,status,usage=os.wait4(proc.pid,0);proc.returncode=os.waitstatus_to_exitcode(status)
  text=path.read_text(errors='replace');result={'label':label,'argv':list(map(str,argv)),'exit':proc.returncode,'seconds':round(time.monotonic()-started,3),'max_rss_KiB':usage.ru_maxrss,'log_sha256':sha(path),'expected':'nonzero' if negative else 0,'anchor':anchor,'actual_corruption_required':corrupt}
  r['commands'].append(result);save()
  assert (proc.returncode!=0 if negative else proc.returncode==0) and (anchor is None or anchor in text) and (not corrupt or re.search(r'ACTUAL_CORRUPTION count=[1-9]',text)),(result,text[-6000:])
  print(label,proc.returncode,f"{result['seconds']}s",flush=True)
 def host_runs(name,binary,stem,new):
  run(name+'-positive',[binary],'BOUND_OVERLAP_'+('BACKEND' if stem=='backend' else 'SLOTS')+'_PASS')
  cases=([('--mutate-frozen-pa','bound store failed frozen physical handoff'),('--mutate-local-ack','memory retirement before actual response and completion'),('--mutate-load-error','physical error lost exact completion cause/original VA'),('--mutate-store-error','physical error lost exact completion cause/original VA')] if stem=='backend' else [('--mutate-owner','request owner full-tag corruption'),('--mutate-slot','accepted overlap selected a completing or busy slot'),('--mutate-pa','frozen PA/full-token origin corruption')])
  if new:
   for flag,anchor in cases:run(name+flag,[binary,flag],anchor,True,True)
   if stem=='backend':
    run(name+'-mutate-data',[binary,'--mutate-data'],'independent execution data mismatch',True,True)
    run(name+'-mutate-retirement',[binary,'--mutate-retirement'],'fault/killed/duplicate retirement',True,True)
   else:run(name+'-assert-same-edge-cancel',[binary,'--assert-same-edge-cancel'],'every pre-edge co-owner must survive the accepted bound-store start',True)
 try:
  if args.stage=='config':run('focused-config',[MILL,'-i','-j','1','IonSoC.test.testOnly','ooo.PendingVirtualStoreProofConfigSpec'])
  else:
   for name in models:
    top,stem,parameters=MODELS[name];model=out/name
    if args.stage=='emit':
     model.mkdir(exist_ok=False);run(name+'-emit',[MILL,'-i','-j','1','IonSoC.test.runMain','ooo.'+top+'Main',model,*parameters])
    elif args.stage=='generate':
     run(name+'-generate',[GSIM,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(model),model/(top+'.fir')])
    else:
     target=model/'sanitized';target.mkdir(exist_ok=False);flags=BASE_FLAGS+['-I'+str(model),'-DPENDING_STORE_ENABLED=1','-DBOUND_HEAD_STORE_OVERLAP='+str(int(name!='oldbackend'))];host=ROOT/f'simulator/gsim/harness/bound_head_store_overlap_{stem}.cpp'
     run(name+'-'+args.stage+'-syntax',[CXX,*flags,'-fsyntax-only',host]);objects=[];sources=sorted(model.glob(top+'[0-9]*.cpp'));assert sources
     for n,source in enumerate(sources):
      obj=target/(source.stem+'.o');objects.append(obj)
      assert not obj.exists(),'fresh object build required'
      run(name+f'-compile-{n}',[CXX,*flags,'-c',source,'-o',obj]);r.setdefault('objects',{})[str(obj.relative_to(out))]=sha(obj);save()
     binary=target/'run';run(name+'-'+args.stage+'-link',[CXX,*flags,host,*objects,'-ldl','-o',binary]);host_runs(name,binary,stem,name!='oldbackend')
  r['model_artifacts']=portable.model_artifacts(out,models);r.setdefault('completed_stages',[]).append(args.stage)
  r['status']=args.stage.upper()+'_PASS';save()
 except BaseException as error:r['status']=args.stage.upper()+'_FAILED';r['error']=str(error);save();raise
if __name__=='__main__':main()
