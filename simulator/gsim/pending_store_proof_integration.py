#!/usr/bin/env python3
"""Portable fresh-build pending-store focused qualification. No object relink or board/Vivado work."""
import argparse, hashlib, json, os, re, shutil, subprocess, time
from pathlib import Path
import bound_store_replay_common as portable
ROOT=Path(__file__).resolve().parents[2]
MODELS={
    'bank1':('PendingStoreProofBankGsim','bank',['1'],['PENDING_STORE_SLOTS=1'],'PENDING_BANK_PASS'),
    'bank2':('PendingStoreProofBankGsim','bank',['2'],['PENDING_STORE_SLOTS=2'],'PENDING_BANK_PASS'),
    'backend0':('PendingStoreProofBackendGsim','backend',['0'],['PENDING_STORE_ENABLED=0'],'PENDING_BACKEND_PASS'),
    'backend1':('PendingStoreProofBackendGsim','backend',['1'],['PENDING_STORE_ENABLED=1'],'PENDING_BACKEND_PASS'),
    'transport':('PendingStoreProofTransportGsim','transport',[],['MEMORY_PROOF_ENABLED=1'],'PENDING_TRANSPORT_PASS'),
}
# Thin public adapters may register a model without copying stage execution.
DEFAULT_MODELS='backend0,backend1,transport'
CONFIG_SUITES=['ooo.PendingVirtualStoreProofConfigSpec']
HOST_FILES={}
EXTRA_NEGATIVES={}
EXTRA_INPUTS=[]
def validate_source(root):
    pass

def host_file(stem):
    return ROOT/HOST_FILES.get(stem,f'simulator/gsim/harness/pending_store_proof_{stem}.cpp')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def source_inputs(models):
    files=[Path(__file__), ROOT/'simulator/gsim/harness/pending_store_proof_reference.h']
    files += [host_file(MODELS[m][1]) for m in models]
    files += [ROOT/name for name in EXTRA_INPUTS]
    return portable.source_inputs(ROOT, files)

def main():
    global ROOT
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage',choices=['freeze','config','emit','generate','sanitized'])
    ap.add_argument('--output',type=Path,required=True)
    portable.add_paths(ap,ROOT)
    ap.add_argument('--models',default=DEFAULT_MODELS)
    args=ap.parse_args()
    ROOT=args.source_root.resolve()
    validate_source(ROOT)
    tools=portable.tool_paths(args,ap);MILL=tools['mill'];GSIM=tools['gsim'];CXX=tools['cxx']
    models=args.models.split(',');assert models and len(set(models))==len(models) and all(m in MODELS for m in models)
    out=args.output.resolve();receipt_path=out/'receipt.json'
    if portable.preflight(args,source_inputs(models),tools):return
    if args.stage=='freeze':
        out.mkdir(parents=True,exist_ok=False)
        inputs=source_inputs(models)
        receipt={'status':'SOURCE_FROZEN','models':models,'inputs':inputs,'inputs_sha256':digest(inputs),
            'runner_sha256':sha(__file__),'commands':[],
            'tools':portable.tool_binding(tools),'schema':'bound-store-portable-stage-v1',
            'scope':'focused bank/one-credit component, real-decoder backend or frozen transport as individually listed',
            'limitations':['No whole-board, performance, Vivado, routed timing or full regression claim.',
                'Combined ASan+UBSan instrumented build, halt on error. Per-process detect_leaks=0; LSan is unavailable under ptrace.',
                'Serial store waits for early LSU read drain. Late-store-fault and kill-before-response are distinct reachable witnesses.']}
        receipt_path.write_text(json.dumps(receipt,indent=2)+'\n')
        print(json.dumps({'status':receipt['status'],'inputs_sha256':receipt['inputs_sha256'],
            'runner_sha256':receipt['runner_sha256'],'receipt':str(receipt_path)},indent=2));return
    receipt=json.loads(receipt_path.read_text());assert receipt['models']==models
    assert source_inputs(models)==receipt['inputs'],'source drift'
    assert receipt['schema']=='bound-store-portable-stage-v1','historical receipts are immutable evidence only'
    assert portable.tool_binding(tools)==receipt['tools'],'toolchain drift'
    portable.check_tools(receipt['tools'])
    assert not receipt['status'].endswith('_FAILED'),'fresh output required after failure'
    if receipt.get('model_artifacts'):portable.verify_model_inputs(out,receipt['model_artifacts'])
    prerequisite={'generate':'emit','asan':'generate','ubsan':'generate','sanitized':'generate'}.get(args.stage)
    if prerequisite:assert prerequisite in receipt.get('completed_stages',[]),'missing stage: '+prerequisite
    def save():receipt_path.write_text(json.dumps(receipt,indent=2)+'\n')
    def run(label,argv,anchor=None,negative=False):
        assert source_inputs(models)==receipt['inputs'],'source drift'
        portable.check_tools(receipt['tools'])
        path=out/(label+'.log');assert not path.exists(),'preserve earlier evidence; freeze a fresh revision'
        start=time.monotonic()
        with path.open('x') as log:
            proc=subprocess.Popen(portable.command_args(argv,tools),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'})
            _,status,usage=os.wait4(proc.pid,0);proc.returncode=os.waitstatus_to_exitcode(status)
        text=path.read_text(errors='replace')
        result={'label':label,'argv':list(map(str,argv)),'exit':proc.returncode,'seconds':round(time.monotonic()-start,3),
            'max_rss_KiB':usage.ru_maxrss,'log_sha256':sha(path),'expected':'nonzero' if negative else 0}
        receipt['commands'].append(result);save()
        assert (proc.returncode!=0 if negative else proc.returncode==0) and (anchor is None or anchor in text),(result,text[-5000:])
        print(label,proc.returncode,f"{result['seconds']}s",flush=True)
    try:
        if args.stage=='config':
            run('focused-config',[MILL,'-i','-j','1','IonSoC.test.testOnly',*CONFIG_SUITES])
        for name in ([] if args.stage=='config' else models):
            top,stem,parameters,defines,anchor=MODELS[name];model=out/name
            if args.stage=='emit':
                model.mkdir(exist_ok=False)
                run(name+'-emit',[MILL,'-i','-j','1','IonSoC.test.runMain','ooo.'+top+'Main',model,*parameters])
            elif args.stage=='generate':
                run(name+'-generate',[GSIM,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(model),model/(top+'.fir')])
            else:
                sanitizer='address,undefined'
                target=model/'sanitized';target.mkdir(exist_ok=False)
                flags=['-std=c++20','-O1','-g','-fsanitize='+sanitizer,'-fno-sanitize-recover=all','-I'+str(model)]
                run(name+'-'+args.stage+'-host-syntax',[CXX,*flags,*['-D'+d for d in defines],
                    '-fsyntax-only',host_file(stem)])
                objects=[]
                sources=sorted(model.glob(top+'[0-9]*.cpp'));assert sources,'generated model missing'
                for n,source in enumerate(sources):
                    obj=target/(source.stem+'.o');objects.append(obj)
                    reused=receipt.get('reusable_objects',{}).get(name,{}).get(source.name)
                    if reused:
                        assert sha(source)==reused['cpp_sha256'] and sha(reused['path'])==reused['object_sha256'], 'reused object drift'
                        assert [f for f in reused['flags'] if not f.startswith('-I')]==[f for f in flags if not f.startswith('-I')] and reused['tools']==receipt['tools'], 'reused object compiler/flags drift'
                        shutil.copy2(reused['path'],obj)
                        receipt.setdefault('object_reuse',{})[str(obj.relative_to(out))]=reused;save()
                    else:
                        run(name+'-'+args.stage+f'-compile-{n}',[CXX,*flags,'-c',source,'-o',obj])
                    receipt.setdefault('objects',{})[str(obj.relative_to(out))]=sha(obj);save()
                binary=target/'run'
                run(name+'-'+args.stage+'-link',[CXX,*flags,*['-D'+d for d in defines],
                    host_file(stem),*objects,'-ldl','-o',binary])
                run(name+'-'+args.stage+'-positive',[binary],anchor)
                if stem=='bank':
                    run(name+'-'+args.stage+'-mutate-full-tag',[binary,'--mutate-full-tag'],'independent full-tuple oracle mismatch',True)
                    run(name+'-'+args.stage+'-double-reserve',[binary,'--assert-double-reserve'],'early-load reserve requires a pre-edge free entry',True)
                elif stem=='backend':
                    run(name+'-'+args.stage+'-mutate-data',[binary,'--mutate-data'],'independent execution data mismatch',True)
                    if name=='backend1':run(name+'-'+args.stage+'-mutate-retirement',[binary,'--mutate-retirement'],'fault/killed/duplicate retirement',True)
                elif stem=='transport':
                    run(name+'-'+args.stage+'-mutate-token',[binary,'--inject-token'],'independent full-token origin pairing mismatch',True)
                    run(name+'-'+args.stage+'-malformed-mask',[binary,'--assert-mask'],'frozen store proof requires',True)
                    run(name+'-'+args.stage+'-atomic-proof',[binary,'--assert-atomic'],'ordinary virtual',True)
                for flag,anchor in EXTRA_NEGATIVES.get(stem,[]):
                    run(name+'-'+args.stage+'-'+flag.lstrip('-'),[binary,flag],anchor,True)
        receipt['model_artifacts']=portable.model_artifacts(out,models);receipt.setdefault('completed_stages',[]).append(args.stage)
        receipt['status']=args.stage.upper()+'_PASS';save()
    except BaseException as error:
        receipt['status']=args.stage.upper()+'_FAILED';receipt['error']=str(error);save();raise
if __name__=='__main__':main()
