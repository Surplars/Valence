#!/usr/bin/env python3
"""Seal source/output hashes and the default-off structural comparison."""
import argparse, hashlib, json, re, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def normalized(path):return '\n'.join(re.sub(r' @\[.*\]','',line).rstrip() for line in Path(path).read_text().splitlines())+'\n'
def declarations(text):return [line.strip() for line in text.splitlines() if re.match(r'^\s*(input|output|reg|regreset|mem|cmem|smem) ',line)]
def main():
    ap=argparse.ArgumentParser();ap.add_argument('receipt',type=Path);ap.add_argument('output',type=Path);a=ap.parse_args()
    r=json.loads(a.receipt.read_text());assert r['status']=='PASS'
    for path,digest in r['source_sha256'].items():assert sha(ROOT/path)==digest
    artifacts=0
    for model in r['models'].values():
        for path,digest in model['artifacts_sha256'].items():assert sha(ROOT/model['model_directory']/path)==digest;artifacts+=1
    for path,digest in r['artifacts_sha256'].items():assert sha(a.receipt.parent/path)==digest;artifacts+=1
    older=ROOT/'build/gsim/prefetch-candidate-lifetime-r1/receipt.json';old=json.loads(older.read_text());assert old['status']=='PASS'
    original=ROOT/old['models']['cycles3']['model_directory']/'CoherentCacheHomeGsim.fir'
    assert sha(original)==old['models']['cycles3']['artifacts_sha256'][original.name]
    reference=a.receipt.parent/'reference/CoherentCacheHomeGsim.fir'
    candidate=a.receipt.parent/'break/CoherentCacheHomeGsim.fir'
    x,y,z=map(normalized,[original,reference,candidate]);assert x==y
    assert declarations(y)==declarations(z)
    for harness in ['prefetch_candidate_lifetime.cpp','data_prefetch.cpp','cache_concurrency_stress.cpp']:
        assert r['models']['reference']['programs'][harness]['logs']==r['models']['break']['programs'][harness]['logs']
    result={'schema':'valence-qualified-prefetch-store-history-v1','status':'PASS','frozen_hardware':'df4594f',
        'source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'runner_receipt':str(a.receipt.resolve()),'runner_receipt_sha256':sha(a.receipt),'gate':r,
        'reporter_sha256':sha(__file__),'verified_source_count':len(r['source_sha256']),'verified_local_artifact_count':artifacts,
        'structure':{'normalization':'remove trailing FIR source annotations and trailing spaces; preserve all logic text',
            'original_qualified_receipt_sha256':sha(older),'original_fir_sha256':sha(original),
            'reference_fir_sha256':sha(reference),'candidate_fir_sha256':sha(candidate),
            'default_off_full_normalized_fir_sha256':hashlib.sha256(x.encode()).hexdigest(),
            'candidate_and_reference_identical_port_register_memory_declarations':len(declarations(y))},
        'limits':['This is a cache/home module gate; integrated workload performance is a separate board result.',
            'Context gating is compositional: new cache history/lifetime tests plus reverified prior authorization and CPU busy fixtures.',
            'No mapped resources, routed timing or physical bandwidth measurement.']}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(a.output,sha(a.output))

if __name__=='__main__':main()
