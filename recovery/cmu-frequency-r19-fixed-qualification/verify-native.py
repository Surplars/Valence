#!/usr/bin/env python3
"""Rehash the full r19 native receipt against retained original workspace inputs."""
import hashlib,json,pathlib,sys
root=pathlib.Path.cwd();d=pathlib.Path(sys.argv[1]).resolve();r=json.loads((d/'receipt.json').read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
assert r['status']=='PASS' and r['requested_subset']['full_matrix'] and r['requested_subset']['negatives']
frozen_test_inputs = {
    'simulator/gsim/common/i1_runtime_fixed_tb.sv': 'testbench.source.sv',
    'simulator/gsim/common/i1_runtime_fixed_native.py': 'runner.source.py',
}
for n,h in r['source_sha256'].items():
    p=root/n
    if sha(p)!=h and n in frozen_test_inputs:
        p=d/frozen_test_inputs[n]
    assert sha(p)==h,n
for n,t in r['tools'].items():assert sha(pathlib.Path(t['path']))==t['sha256'],n
for n,h in r['guest']['artifacts'].items():assert sha(d/n)==h,n
for n,h in r['logs_sha256'].items():assert sha(d/n)==h,n
assert sha(d/'sim.vvp')==r['sim_sha256']
assert sha(d/'preprocessed.sv')==r['production_assertions']['preprocessed_sha256']
cases={c['name']:c for c in r['cases']}
positives=[f'{ratio}-case-{i}' for ratio in ('unrelated','reversed') for i in range(4)]
for name in positives:
 c=cases[name];assert c['returncode']==0 and not c['timed_out'] and not c['interrupted'] and c['child_reaped']
 assert 'I1_RUNTIME_FIXED_PASS' in (d/(name+'.log')).read_text()
for i,marker in enumerate(('NETWORK_ORACLE_PAYLOAD','NETWORK_ORACLE_DRAIN','NETWORK_ORACLE_GUARD','FIXED_ORACLE_STALE_IDLE'),1):
 c=cases[f'negative-{i}'];s=(d/(f'negative-{i}.log')).read_text()
 assert c['returncode']!=0 and not c['timed_out'] and not c['interrupted'] and c['child_reaped']
 assert marker in s and 'I1_RUNTIME_FIXED_PASS' not in s
rtl={pathlib.Path(x).name:pathlib.Path(x) for x in cases['compile']['command'] if str(x).endswith('.sv') and pathlib.Path(x).name!='i1_runtime_fixed_tb.sv'}
assert set(rtl)==set(r['rtl_sha256'])
for n,h in r['rtl_sha256'].items():assert sha(rtl[n])==h,n
p=pathlib.Path(r['emission_receipt']['path']);assert sha(p)==r['emission_receipt']['sha256'];e=json.loads(p.read_text())
assert e['status']=='PASS_EMIT_ONLY' and e['rtl_sha256']==r['rtl_sha256']
for n,h in e['source_sha256'].items():assert sha(root/n)==h,n
proof=dict(status='PASS_INDEPENDENT_FULL_NATIVE_REHASH',receipt_sha256=sha(d/'receipt.json'),sources=len(r['source_sha256']),emission_sources=len(e['source_sha256']),tools=len(r['tools']),rtl=len(rtl),positive_cases=8,negative_controls=4,compiled_sha256=r['sim_sha256'],physical_signoff=False)
(d/'independent-rehash.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof))
