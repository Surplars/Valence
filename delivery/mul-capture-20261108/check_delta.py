#!/usr/bin/env python3
"""Bounded closure and continuity check. No functional or physical equivalence claim."""
import argparse, hashlib, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'combined-20261108'))
from check_emission import inspect

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--original',required=True,type=Path);p.add_argument('--control',required=True,type=Path);p.add_argument('--candidate',required=True,type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args()
    old=json.loads((a.original/'ooc-identity.json').read_text());ctrl=json.loads((a.control/'ooc-identity.json').read_text());new=json.loads((a.candidate/'ooc-identity.json').read_text())
    oldkeys=[k for k in old.keys()|ctrl.keys() if old.get(k)!=ctrl.get(k)]
    assert oldkeys==['compileBinding'],oldkeys
    reports=[inspect(x) for x in (a.control,a.candidate)]
    original_hashes={p.name:sha(p) for p in (a.original/'rtl').glob('*.sv')}
    assert reports[0]['sv_sha256']==original_hashes,'Fresh control differs from delivered control'
    delta={}
    for key in ('effectiveCore','cpuConfig'):
        delta[key]={k:[ctrl[key].get(k),new[key].get(k)] for k in ctrl[key].keys()|new[key].keys() if ctrl[key].get(k)!=new[key].get(k)}
        assert delta[key]=={'registeredMulLoadOperandCapture':['false','true']},delta[key]
    changedkeys={k for k in ctrl.keys()|new.keys() if ctrl.get(k)!=new.get(k)}
    assert changedkeys=={'mode','cpuConfig','effectiveCore','memoryProfile'},changedkeys
    assert ctrl['memoryProfile']=='experimental-efficiency-refactor-4'
    assert new['memoryProfile']=='experimental-mul-load-operand-capture'
    aHashes,bHashes=[r['sv_sha256'] for r in reports]
    changed=sorted(k for k in aHashes.keys()|bHashes.keys() if aHashes.get(k)!=bHashes.get(k))
    assert changed==['IntegerBackend.sv'],changed
    report={'status':'PASS_STRUCTURAL_CLOSURE_AND_DELIVERED_CONTROL_CONTINUITY','control':reports[0],'candidate':reports[1],'configuration_delta':delta,'changed_rtl_files':changed,'original_delivered_rtl_byte_identical':True,'original_identity_changed_keys':oldkeys,'memory_policy':'Exact named MUL experiment validator; original efficiency4 memory behavior preserved','combined_cpu_runtime':'NOT_RUN','vivado':'NOT_RUN','limits':'Not functional equivalence, physical timing, whole-board, or bus-bandwidth qualification'}
    a.out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('control','candidate')}))
if __name__=='__main__':main()
