#!/usr/bin/env python3
"""Small actual-bank old/new RTL comparison; no CPU, synthesis, placement or timing."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
import bound_store_replay_common as portable
import pending_store_rob_mapping as qualification

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def scalar_registers(text):
    regs={}
    for width,name in re.findall(r'\breg\s*(\[\d+:\d+\])?\s+(\w+)\s*;',text):
        nums=[int(v) for v in re.findall(r'\d+',width)]
        regs[name]=abs(nums[0]-nums[1])+1 if nums else 1
    return regs

def map_cone(text, root):
    # firtool may emit named wires, output assignments, or wrapped expressions.
    eq={}
    for name,expr in re.findall(r'\bwire\s*(?:\[[^\]]+\]\s*)?(\w+)\s*=\s*(.*?);',text,re.S):
        eq[name]=expr
    for name,expr in re.findall(r'\bassign\s+(\w+)\s*=\s*(.*?);',text,re.S):
        eq[name]=expr
    seen=set()
    def visit(name):
        if name in seen:return
        seen.add(name)
        for dep in re.findall(r'\b[A-Za-z_]\w*\b',eq.get(name,'')):
            if dep in eq or '_token_tag' in dep or '_token_index' in dep or '_valid' in dep:visit(dep)
    assert root in eq, 'missing native output: '+root
    visit(root)
    return {'expression':eq[root], 'names':sorted(seen),
            'proof_tag_readers':sorted(n for n in seen if re.search(r'candidate.*proofs.*token_tag',n)),
            'owner_tag_readers':sorted(n for n in seen if re.search(r'(io_owner.*token_tag|tokens_.*tag)',n))}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage',choices=['freeze','export','report'])
    ap.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parents[2])
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--toolchain-root',type=Path,required=True)
    ap.add_argument('--mill',type=Path,help='Optional hash-bound minimal-source Mill bridge')
    args=ap.parse_args()
    source=args.source_root.resolve();out=args.output.resolve();tool=args.toolchain_root.resolve()
    qualification.validate_source(source)
    paths={'activate':tool/'activate.sh','mill':args.mill.resolve() if args.mill else tool/'bin/mill',
        'firtool':tool/'firtool-1.135.0/firtool'}
    extra=[source/p for p in ['simulator/gsim/pending_store_rob_mapping_native.py',
        'simulator/gsim/pending_store_rob_mapping.py','simulator/gsim/pending_store_proof_integration.py',
        'simulator/gsim/prepare_pending_store_rob_mapping_cache.py',
        'simulator/gsim/harness/pending_store_rob_mapping.cpp','simulator/gsim/harness/pending_store_proof_reference.h']]
    sources=portable.source_inputs(source,extra)
    tools=portable.tool_binding(paths)
    receipt_path=out/'receipt.json'
    if args.stage=='freeze':
        out.mkdir(parents=True,exist_ok=False)
        state={'schema':'pending-store-rob-map-native-v1','status':'SOURCE_FROZEN','inputs':sources,'tools':tools,
            'commands':[], 'qualification':'Retained producer state and consumer comparison cone only. No FPGA utilization or timing claim.'}
        receipt_path.write_text(json.dumps(state,indent=2)+'\n')
        print('SOURCE_FROZEN',sha(receipt_path));return
    state=json.loads(receipt_path.read_text())
    assert state['schema']=='pending-store-rob-map-native-v1'
    assert not state['status'].endswith('FAILED'), 'preserve failures; freeze a fresh output'
    def guard():
        assert sources==state['inputs'],'source drift'
        for name,digest in state['inputs'].items():assert sha(source/name)==digest,'source drift: '+name
        assert tools==state['tools'],'tool drift'
        portable.check_tools(state['tools'])
    def save():receipt_path.write_text(json.dumps(state,indent=2)+'\n')
    def run(label,argv):
        guard();log=out/(label+'.log');assert not log.exists(),'preserve previous evidence'
        start=time.monotonic()
        with log.open('x') as f:
            proc=subprocess.Popen(portable.command_args(argv,paths),cwd=source,stdout=f,stderr=subprocess.STDOUT)
            _,status,usage=os.wait4(proc.pid,0);proc.returncode=os.waitstatus_to_exitcode(status)
        state['commands'].append({'label':label,'argv':list(map(str,argv)), 'exit':proc.returncode,
            'seconds':round(time.monotonic()-start,3),'max_rss_KiB':usage.ru_maxrss,'log_sha256':sha(log)})
        save();assert proc.returncode==0,(label,log.read_text()[-5000:]);print(label,'PASS',flush=True)
    try:
        guard()
        if args.stage=='export':
            for rows in [1,2]:
                for mode,label in [(1,'old'),(2,'new')]:
                    name=f'rows{rows}-{label}';model=out/name;model.mkdir()
                    run(name+'-emit',[paths['mill'],'-i','-j','1','IonSoC.test.runMain',
                        'ooo.PendingStoreRobMappingGsimMain',model,rows,mode])
                    run(name+'-lower',[paths['firtool'],model/'PendingStoreRobMappingGsim.fir','--format=fir',
                        '--split-verilog','--strip-debug-info','--disable-all-randomization',
                        '--default-layer-specialization=disable','-o',model/'rtl'])
            state['artifacts']={str(p.relative_to(out)):sha(p) for p in sorted(out.glob('rows*/**/*')) if p.is_file()}
            state['status']='NATIVE_EXPORT_PASS';save();return
        assert state['status']=='NATIVE_EXPORT_PASS'
        portable.verify_artifacts(out,state['artifacts'])
        comparison={'scope':'Native emitted RTL only; no FPGA mapped saving or timing claim.','rows':{}}
        for rows in [1,2]:
            modes={}
            for label in ['old','new']:
                rtl=out/f'rows{rows}-{label}'/'rtl'
                bank=(rtl/'PendingVirtualStoreProof.sv').read_text()
                top=(rtl/'PendingStoreRobMappingGsim.sv').read_text()
                regs=scalar_registers(bank)
                assert regs,'no retained bank registers'
                modes[label]={'registers':regs,'register_bits':sum(regs.values()),
                    'bank_sha256':sha(rtl/'PendingVirtualStoreProof.sv'),
                    'pmp_sha256':sha(rtl/'PmpChecker.sv'),
                    'presence_cone':map_cone(top,'io_candidateMap'),
                    'disjoint_cone':map_cone(top,'io_candidateDisjoint'),
                    'top_comparisons':len(re.findall(r'==|!=',top))}
            assert modes['old']['registers']==modes['new']['registers'],'retained state changed'
            assert modes['old']['bank_sha256']==modes['new']['bank_sha256'],'producer logic changed'
            assert modes['old']['pmp_sha256']==modes['new']['pmp_sha256'],'PMP logic changed'
            for kind in ['presence_cone','disjoint_cone']:
                assert modes['old'][kind]['proof_tag_readers'],'old map unexpectedly lacks full proof tag'
                assert not modes['new'][kind]['proof_tag_readers'],'new consumer map still reads wide proof tag'
            comparison['rows'][str(rows)]=modes
        (out/'comparison.json').write_text(json.dumps(comparison,indent=2)+'\n')
        state['comparison_sha256']=sha(out/'comparison.json');state['status']='NATIVE_COMPARE_PASS';save()
        print('NATIVE_COMPARE_PASS')
    except BaseException as error:
        state['status']=args.stage.upper()+'_FAILED';state['error']=str(error);save();raise
if __name__=='__main__':main()
