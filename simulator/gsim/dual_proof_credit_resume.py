#!/usr/bin/env python3
"""Exact generated-input/object bridge for a test-host-only correction; never alters prior FAIL evidence."""
import argparse,json,shutil,subprocess,sys
from pathlib import Path
import dual_proof_credit as gate
import bound_store_replay_common as portable
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--from-output',type=Path,required=True)
ap.add_argument('--from-receipt-sha256',required=True)
ap.add_argument('--output',type=Path,required=True)
portable.add_paths(ap,gate.run.ROOT)
a=ap.parse_args();old=a.from_output.resolve();new=a.output.resolve();root=a.source_root.resolve()
oldpath=old/'receipt.json';assert portable.sha(oldpath)==a.from_receipt_sha256,'prior receipt identity drift'
r=json.loads(oldpath.read_text());assert r['schema']=='bound-store-portable-stage-v1'
assert all(s in r.get('completed_stages',[]) for s in ['config','emit','generate']), 'prior generation incomplete'
stage_commands=r.get('stage_reuse',{}).get('commands',[])+[c for c in r['commands'] if c['label'].endswith(('-emit','-generate')) or c['label']=='focused-config']
assert len(stage_commands)==1+2*len(r['models']) and all(c['exit']==0 for c in stage_commands),'missing successful source-bound stage proof'
assert r['models']==list(gate.run.MODELS), 'model set differs'
gate.run.ROOT=root
current=gate.run.source_inputs(r['models'])
allow={'simulator/gsim/pending_store_proof_integration.py','simulator/gsim/dual_proof_credit.py',
    'simulator/gsim/dual_proof_credit_resume.py','simulator/gsim/harness/bounded_early_load_credit.cpp',
    'simulator/gsim/harness/dual_proof_credit_backend.cpp','simulator/gsim/harness/dual_proof_credit_controls.cpp'}
changed={p for p in set(current)|set(r['inputs']) if current.get(p)!=r['inputs'].get(p)}
assert changed<=allow, 'non-host source change forbids generation reuse: '+str(changed-allow)
tools=portable.tool_paths(a,ap);assert portable.tool_binding(tools)==r['tools'],'toolchain differs'
# Every generated artifact is exact, including every header, and old source is never overwritten.
for rel,digest in r['model_artifacts'].items():
    q=Path(rel);assert not q.is_absolute() and '..' not in q.parts
    assert portable.sha(old/q)==digest,'old generated artifact drift: '+rel
argv=[sys.executable,str(root/'simulator/gsim/dual_proof_credit.py'),'freeze','--output',str(new),'--source-root',str(root)]
for key,value in tools.items():argv+=['--'+key,str(value)]
subprocess.run(argv,check=True)
fresh=json.loads((new/'receipt.json').read_text())
assert fresh['inputs']==current
for rel,digest in r['model_artifacts'].items():
    q=Path(rel);assert not any(x in q.parts for x in ['sanitized','asan','ubsan']), 'generation map unexpectedly contains native build'
    target=new/q;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(old/q,target)
    assert portable.sha(target)==digest
fresh['completed_stages']=['config','emit','generate']
fresh['status']='GENERATE_PASS'
fresh['model_artifacts']=r['model_artifacts']
fresh['stage_reuse']={'receipt':str(oldpath),'receipt_sha256':a.from_receipt_sha256,
    'changed_host_inputs':sorted(changed),'source_contract':'All hardware, wrappers, build files and original model artifacts unchanged by SHA256.',
    'commands':stage_commands}
fresh['reusable_objects']={}
for name in r['models']:
    top=gate.run.MODELS[name][0]
    for n,source in enumerate(sorted((old/name).glob(top+'[0-9]*.cpp'))):
        obj=old/name/'sanitized'/(source.stem+'.o');rel=str(obj.relative_to(old))
        if rel not in r.get('objects',{}):continue
        assert portable.sha(obj)==r['objects'][rel]
        matches=[c for c in r['commands'] if c['label']==name+'-sanitized-compile-'+str(n) and c['exit']==0]
        # Later bridged receipts carry the exact original compile proof separately.
        prior=r.get('reusable_objects',{}).get(name,{}).get(source.name)
        assert len(matches)==1 or prior,'missing successful compile binding'
        flags=matches[0]['argv'][1:matches[0]['argv'].index('-c')] if matches else prior['flags']
        fresh['reusable_objects'].setdefault(name,{})[source.name]={'path':str(obj),
            'object_sha256':r['objects'][rel],'cpp_sha256':portable.sha(source),'flags':flags,'tools':r['tools']}
(new/'receipt.json').write_text(json.dumps(fresh,indent=2)+'\n')
print(json.dumps({'status':'EXACT_GENERATION_BRIDGE','output':str(new),'changed_host_inputs':sorted(changed),
    'reused_objects':sum(map(len,fresh['reusable_objects'].values()))},indent=2))
