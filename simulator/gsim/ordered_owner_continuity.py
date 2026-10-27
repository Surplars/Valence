#!/usr/bin/env python3
"""Bind an immutable actual-component run to one unrelated test-only Scala rename.

Fresh exact FIR emission is not a new GSIM build or execution. Original receipt,
compiled objects, host, logs, negatives and trace are preserved and fully rehashed.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timezone
sys.dont_write_bytecode=True
import run as common
import gsim_initialization_epoch as epoch
import ordered_owner_chain as original

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(ok,msg):
    if not ok:raise RuntimeError(msg)
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--original-receipt',type=Path,required=True)
    ap.add_argument('--original-compile-receipt',type=Path,required=True)
    ap.add_argument('--compile-receipt',type=Path,required=True)
    ap.add_argument('--tool-receipt',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();old=json.loads(args.original_receipt.read_text())
    need(sha(args.original_receipt)=='cbd8f6a553a66ac2aff0a1365e5e210fdcf34ab67ef552e65b1ace47bf4820b0','exact qualified original receipt required')
    need(old['status']==original.PASS and old['inputs_unchanged'],'original component run not qualified')
    need(sha(args.original_compile_receipt)==old['compile_receipt_sha256'],'original compile identity mismatch')
    before=original.inputs();need(before==old['inputs'],'component source/host/runner inputs changed')
    for name,value in old['artifacts'].items():need(sha(args.original_receipt.parent/name)==value,'original artifact drift: '+name)
    binding=epoch.tool_binding(args.tool_receipt);need(binding==old['tool_epoch'],'original tool identity changed')
    spec=importlib.util.spec_from_file_location('scala_gate',common.ROOT/'fpga/common/scala_compile_receipt.py');gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
    compiled=gate.verify_receipt(args.compile_receipt,common.ROOT)
    previous=json.loads(args.original_compile_receipt.read_text())
    a,b=previous['sourceInputs'],compiled['sourceInputs']
    need(set(a)==set(b),'Scala source input names changed')
    changed=[p for p in a if a[p]!=b[p]]
    allowed=str(common.ROOT/'src/test/scala/ooo/AdvisoryExclusionGsim.scala')
    need(changed==[allowed],'only unrelated reserved-name fixture rename permitted')
    current=Path(allowed).read_bytes()
    need(current.count(b'legacyThird')==4,'unexpected rename occurrence count')
    restored=current.replace(b'legacyThird',b'old')
    need(hashlib.sha256(restored).hexdigest()==a[allowed],'source delta exceeds exact old->legacyThird identifier rename')
    args.out.mkdir(parents=True,exist_ok=False)
    record={'schema':'valence-ordered-owner-compile-continuity-v1','status':'RUNNING',
            'compile_receipt_sha256':sha(args.compile_receipt),
            'original_compile_receipt_sha256':sha(args.original_compile_receipt),
            'original_receipt':str(args.original_receipt.resolve()),'original_receipt_sha256':sha(args.original_receipt),
            'tool_epoch':binding,'inputs':before,'all_component_inputs_exact':True,
            'all_fir_bytes_exact':False,'new_DUT_builds':0,'new_GSIM_executions':0,
            'source_delta':{'path':str(Path(allowed).relative_to(common.ROOT)),'old_sha256':a[allowed],'new_sha256':b[allowed],'exact_change':'old -> legacyThird (four identifier occurrences)'},
            'original_artifacts':old['artifacts'],'fir_comparisons':{},
            'started_utc':datetime.now(timezone.utc).isoformat(),
            'producer':{'path':str(Path(__file__).resolve()),'sha256':sha(__file__)}}
    try:
        cp=os.pathsep.join(compiled['runClasspathEntries'])
        for mode,label in ((0,'baseline'),(1,'owner_pair')):
            target=args.out/label;target.mkdir()
            common.run([binding['java']['path'],'-cp',cp,'ooo.OrderedOwnerChainGsimMain',target,str(mode)],log=target/'elaborate.log',timeout=180)
            fresh=target/'OrderedOwnerChainGsim.fir';historical=args.original_receipt.parent/label/'OrderedOwnerChainGsim.fir'
            need(fresh.read_bytes()==historical.read_bytes(),'full FIR bytes changed: '+label)
            record['fir_comparisons'][label]={'bytes':fresh.stat().st_size,'sha256':sha(fresh),'original_path':str(historical.resolve()),'fresh_path':str(fresh.resolve()),'status':'BYTE_EXACT'}
        gate.verify_receipt(args.compile_receipt,common.ROOT)
        need(original.inputs()==before,'component input drift during rebind')
        need(epoch.tool_binding(args.tool_receipt)==binding,'tool drift during rebind')
        for name,value in old['artifacts'].items():need(sha(args.original_receipt.parent/name)==value,'old artifact modified during rebind')
        record['all_fir_bytes_exact']=True
        record['status']='PASS_EXACT_FIR_SOURCE_TOOL_CONTINUITY'
    except Exception as exc:
        record['status']='FAIL';record['error']=str(exc);raise
    finally:
        record['finished_utc']=datetime.now(timezone.utc).isoformat()
        record['artifacts']={str(p.relative_to(args.out)):sha(p) for p in sorted(args.out.rglob('*')) if p.is_file() and p.name!='receipt.json'}
        (args.out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'status':record['status'],'receipt':str(args.out/'receipt.json'),'sha256':sha(args.out/'receipt.json')}))
if __name__=='__main__':main()
