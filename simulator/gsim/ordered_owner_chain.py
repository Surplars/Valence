#!/usr/bin/env python3
"""Actual matched owner-only chain gate. One frozen public compile; GSIM only.

The two fixture modes differ only in registered ordered owners and integer
response readiness. DTA, Sv39 walker, AtomicMemory and FP are real modules.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys
from datetime import datetime, timezone
sys.dont_write_bytecode = True
import run as common
import gsim_initialization_epoch as epoch

SCHEMA = 'valence-ordered-owner-chain-v1'
PASS = 'PASS_ORDERED_OWNER_CHAIN'
TOOL_SHA = '128c4853a6584cd1181cff863fc727a824fe132ad3c60f3ba323d46ea3b135fa'
NEGATIVES = {'tag': 'chain full64 completion owner', 'data': 'chain independent data mismatch',
             'cause': 'chain independent cause mismatch', 'tval': 'chain independent tval mismatch',
             'phase': 'atomic independent phase order mismatch',
             'completion': 'atomic missing completion/phase terminal timeout'}

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def need(condition, why):
    if not condition:
        raise RuntimeError(why)

def inputs():
    paths = list((common.ROOT/'src/main/scala').rglob('*.scala'))
    paths += [common.ROOT/p for p in (
        'src/test/scala/ooo/OrderedOwnerChainGsim.scala',
        'src/test/scala/ooo/BufferedReturnChainGsim.scala',
        'simulator/gsim/harness/ordered_owner_chain.cpp',
        'simulator/gsim/harness/gsim_model_storage.h',
        'simulator/gsim/ordered_owner_chain.py', 'simulator/gsim/run.py',
        'simulator/gsim/gsim_initialization_epoch.py',
        'fpga/common/scala_compile_receipt.py','simulator/gsim/config/toolchain.json','build.mill')]
    return {str(p.relative_to(common.ROOT)):sha(p) for p in sorted(paths)}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build-run',action='store_true');ap.add_argument('--tag',required=True)
    ap.add_argument('--compile-receipt',type=Path);ap.add_argument('--tool-receipt',type=Path)
    args=ap.parse_args()
    need(re.fullmatch(r'[A-Za-z0-9_-]+',args.tag),'fresh filesystem-safe tag required')
    before=inputs()
    if not args.build_run:
        print(json.dumps({'status':'PREFLIGHT_ONLY','inputs':before}));return
    need(args.compile_receipt and args.tool_receipt and sha(args.tool_receipt)==TOOL_SHA,'frozen compile and exact corrected GSIM epoch required')
    binding=epoch.tool_binding(args.tool_receipt)
    spec=importlib.util.spec_from_file_location('scala_gate',common.ROOT/'fpga/common/scala_compile_receipt.py')
    gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
    compiled=gate.verify_receipt(args.compile_receipt,common.ROOT)
    cp=os.pathsep.join(compiled['runClasspathEntries'])
    out=common.BUILD/args.tag;out.mkdir(parents=True,exist_ok=False)
    receipt={'schema':SCHEMA,'status':'RUNNING','inputs':before,
             'compile_receipt_sha256':sha(args.compile_receipt),'tool_epoch':binding,
             'tests':{},'negatives':{},'started_utc':datetime.now(timezone.utc).isoformat(),
             'limits':['Actual component chain, not full CPU/ISA qualification.',
                       'Directed finite stimuli; not exhaustive arbitrary-state proof.',
                       'Observation negatives corrupt host samples, not rebuilt RTL mutants.',
                       'Owner-only valid-event traces compared; invalid head/payload/readiness excluded.']}
    try:
        cxx,version=common.compiler();cxx=shutil.which(cxx);need(cxx,'pinned compiler unavailable')
        receipt['compiler']={'path':cxx,'sha256':sha(cxx),'version':version}
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
        cases=[]
        for mode in (0,1):
            need(before==inputs(),'source drift after freeze')
            model=out/('owner_pair' if mode else 'baseline');model.mkdir()
            common.run([binding['java']['path'],'-cp',cp,'ooo.OrderedOwnerChainGsimMain',model,str(mode)],log=model/'elaborate.log',timeout=180)
            top='OrderedOwnerChainGsim'
            common.run([binding['gsim']['path'],'--threads=1','--dir='+str(model),model/(top+'.fir')],log=model/'generate.log',timeout=600)
            shutil.copyfile(common.HERE/'harness/gsim_model_storage.h',model/'gsim_model_storage.h')
            flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(model)]
            host=common.HERE/'harness/ordered_owner_chain.cpp'
            common.run([cxx,*flags,'-fsyntax-only',host],log=model/'real-header-syntax.log',timeout=180)
            objs=[]
            for source in sorted(model.glob(top+'[0-9]*.cpp')):
                obj=source.with_suffix('.o');common.run([cxx,*flags,'-c',source,'-o',obj],log=obj.with_suffix('.compile.log'),timeout=600);objs.append(obj)
            need(objs,'empty generated object set')
            hobj=model/'host.o';common.run([cxx,*flags,'-c',host,'-o',hobj],log=model/'host-compile.log',timeout=180)
            common.run([cxx,*flags,*objs,hobj,'-ldl','-o',model/'run'],log=model/'link.log',timeout=180)
            common.run([model/'run'],env={**env,'ORDERED_OWNER_TRACE':str(model/'valid-events.bin')},log=model/'test.log',timeout=120)
            output=(model/'test.log').read_text()
            need('ORDERED_OWNER_CHAIN_PASS ' in output,'positive chain marker missing')
            rows=[line for line in output.splitlines() if line.startswith('ORDERED_OWNER_CHAIN_CASE ')]
            need(len(rows)==14,'all directed actual chain cases required')
            cases.append(rows)
            receipt['tests'][model.name]={'status':'PASS','log':str((model/'test.log').relative_to(out)),'sha256':sha(model/'test.log'),'output':output}
            for fault,rejection in NEGATIVES.items():
                result=subprocess.run([str(model/'run'),fault],capture_output=True,text=True,env=env,timeout=120)
                output=result.stdout+result.stderr;log=model/('negative-'+fault+'.log');log.write_text(output)
                need(result.returncode==1 and rejection in output and 'ORDERED_OWNER_CHAIN_PASS ' not in output and output.count('CHAIN_INJECTION_REACHED kind='+fault)==1 and not any(x in output for x in ('AddressSanitizer','runtime error:','Assertion failed:')),'negative exact failure mismatch: '+fault)
                receipt['negatives'][model.name+'_'+fault]={'status':'EXPECTED_REJECTION','exit_code':result.returncode,'rejection':rejection,'log':str(log.relative_to(out)),'sha256':sha(log)}
        need(cases[0]==cases[1],'owner-only changed cycles or diagnostic digests under matched service')
        baseline_trace=(out/'baseline/valid-events.bin').read_bytes()
        candidate_trace=(out/'owner_pair/valid-events.bin').read_bytes()
        need(baseline_trace and baseline_trace==candidate_trace,'owner-only changed exact valid-qualified event bytes')
        receipt['matched_trace']={'status':'BYTE_EXACT','trace_bytes':len(baseline_trace),'trace_sha256':hashlib.sha256(baseline_trace).hexdigest(),'cases':len(cases[0]),'baseline':cases[0],'owner_pair':cases[1]}
        gate.verify_receipt(args.compile_receipt,common.ROOT)
        need(epoch.tool_binding(args.tool_receipt)==binding,'tool epoch drift')
        receipt['status']=PASS
    except Exception as exc:
        receipt['status']='FAIL';receipt['error']=str(exc);raise
    finally:
        receipt['inputs_unchanged']=before==inputs()
        if not receipt['inputs_unchanged']:receipt['status']='FAIL_INPUT_DRIFT'
        receipt['finished_utc']=datetime.now(timezone.utc).isoformat()
        receipt['artifacts']={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='receipt.json'}
        (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'status':PASS,'receipt':str(out/'receipt.json'),'sha256':sha(out/'receipt.json')}))

if __name__=='__main__':main()
