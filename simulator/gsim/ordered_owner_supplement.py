#!/usr/bin/env python3
"""Host-only supplementary directed checks on the sealed two owner-chain DUTs."""
import argparse,hashlib,importlib.util,json,os,re,shutil,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
sys.dont_write_bytecode=True
import run as common
import ordered_owner_chain as original
import gsim_initialization_epoch as epoch

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(ok,msg):
    if not ok:raise RuntimeError(msg)
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--tag',required=True)
    ap.add_argument('--compile-receipt',type=Path,required=True);ap.add_argument('--tool-receipt',type=Path,required=True)
    ap.add_argument('--original-receipt',type=Path,required=True);ap.add_argument('--continuity-receipt',type=Path,required=True)
    a=ap.parse_args();need(re.fullmatch(r'[A-Za-z0-9_-]+',a.tag),'safe fresh tag required')
    old=json.loads(a.original_receipt.read_text());continuity=json.loads(a.continuity_receipt.read_text())
    need(sha(a.original_receipt)=='cbd8f6a553a66ac2aff0a1365e5e210fdcf34ab67ef552e65b1ace47bf4820b0' and old['status']==original.PASS,'exact qualified original run required')
    need(sha(a.continuity_receipt)=='77cb1e41a27ef79922b3f5225f39d22cb82de04b62d24ad231535b2ad7868b3d' and continuity['status']=='PASS_EXACT_FIR_SOURCE_TOOL_CONTINUITY' and continuity['compile_receipt_sha256']==sha(a.compile_receipt),'exact r3 continuity required')
    before=original.inputs();need(before==old['inputs'],'sealed component inputs changed')
    host=common.HERE/'harness/ordered_owner_supplement.cpp'
    inputs={**before,str(host.relative_to(common.ROOT)):sha(host),str(Path(__file__).resolve().relative_to(common.ROOT)):sha(__file__)}
    external={str(a.original_receipt.resolve()):sha(a.original_receipt),str(a.continuity_receipt.resolve()):sha(a.continuity_receipt)}
    for receipt_path,record in ((a.original_receipt,old),(a.continuity_receipt,continuity)):
        for name,digest in record['artifacts'].items():external[str((receipt_path.parent/name).resolve())]=digest
    for name,digest in external.items():need(sha(name)==digest,'sealed artifact drift: '+name)
    binding=epoch.tool_binding(a.tool_receipt);need(binding==old['tool_epoch']==continuity['tool_epoch'],'tool epoch differs')
    spec=importlib.util.spec_from_file_location('scala_gate',common.ROOT/'fpga/common/scala_compile_receipt.py');gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
    gate.verify_receipt(a.compile_receipt,common.ROOT)
    out=common.BUILD/a.tag;out.mkdir(exist_ok=False,parents=True)
    r={'schema':'valence-ordered-owner-supplement-v1','status':'RUNNING','inputs':inputs,'tool_epoch':binding,
       'compile_receipt_sha256':sha(a.compile_receipt),'original_receipt_sha256':sha(a.original_receipt),'continuity_receipt_sha256':sha(a.continuity_receipt),
       'sealed_artifacts':external,'new_DUT_builds':0,'new_Scala_compiles':0,'host_builds':0,'tests':{},'negatives':{},
       'started_utc':datetime.now(timezone.utc).isoformat(),
       'cancel_before_request':{'status':'UNREACHABLE_IN_FIXED_ORDINARY_TOPOLOGY','generic_LSU_coverage':False}}
    try:
        cxx,_=common.compiler();cxx=shutil.which(cxx);need(cxx,'compiler unavailable')
        for mode in ('baseline','owner_pair'):
            frozen=a.original_receipt.parent/mode;target=out/mode;target.mkdir()
            objects=sorted(frozen.glob('OrderedOwnerChainGsim[0-9]*.o'));need(objects,'sealed DUT objects missing')
            flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(frozen)]
            common.run([cxx,*flags,'-fsyntax-only',host],log=target/'real-header-syntax.log',timeout=180)
            common.run([cxx,*flags,'-c',host,'-o',target/'host.o'],log=target/'host-compile.log',timeout=180)
            common.run([cxx,*flags,*objects,target/'host.o','-ldl','-o',target/'run'],log=target/'link.log',timeout=180);r['host_builds']+=1
            env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
            common.run([target/'run'],env={**env,'ORDERED_OWNER_TRACE':str(target/'valid-events.bin')},log=target/'test.log',timeout=120)
            text=(target/'test.log').read_text();need('ORDERED_OWNER_SUPPLEMENT_PASS ' in text and text.count('ORDERED_OWNER_SUPPLEMENT_CASE ')==3,'supplement complete coverage marker missing')
            r['tests'][mode]={'status':'PASS','log':str((target/'test.log').relative_to(out)),'output':text}
            for fault,rejection in {'tag':'chain full64 completion owner','discard':'supp cancellation incomplete terminal ledger','epoch':'supp independently derived authorization epoch mismatch'}.items():
                run=subprocess.run([str(target/'run'),fault],capture_output=True,text=True,env=env,timeout=120);text=run.stdout+run.stderr
                (target/('negative-'+fault+'.log')).write_text(text)
                marker=('CHAIN' if fault=='tag' else 'SUPPLEMENT')+'_INJECTION_REACHED kind='+fault
                need(run.returncode==1 and rejection in text and text.count(marker)==1 and 'ORDERED_OWNER_SUPPLEMENT_PASS ' not in text and not any(w in text for w in ('AddressSanitizer','runtime error:','Assertion failed:')),'supplement negative failure mismatch: '+fault)
                r['negatives'][mode+'_'+fault]={'status':'EXPECTED_REJECTION','diagnostic':rejection,'exit_code':run.returncode}
        first=(out/'baseline/valid-events.bin').read_bytes();second=(out/'owner_pair/valid-events.bin').read_bytes()
        need(first and first==second,'supplement valid-event bytes differ')
        need((out/'baseline/test.log').read_bytes()==(out/'owner_pair/test.log').read_bytes(),'supplement cycle/coverage mismatch')
        r['matched_trace']={'status':'BYTE_EXACT','bytes':len(first),'sha256':hashlib.sha256(first).hexdigest()}
        gate.verify_receipt(a.compile_receipt,common.ROOT)
        for name,digest in external.items():need(sha(name)==digest,'sealed artifact changed during host reuse')
        r['status']='PASS_ORDERED_OWNER_SUPPLEMENT'
    except Exception as exc:r['status']='FAIL';r['error']=str(exc);raise
    finally:
        r['inputs_unchanged']=all(sha(common.ROOT/name)==digest for name,digest in inputs.items())
        if not r['inputs_unchanged']:r['status']='FAIL_INPUT_DRIFT'
        r['finished_utc']=datetime.now(timezone.utc).isoformat()
        r['artifacts']={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='receipt.json'}
        (out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({'status':r['status'],'receipt':str(out/'receipt.json'),'sha256':sha(out/'receipt.json')}))
if __name__=='__main__':main()
