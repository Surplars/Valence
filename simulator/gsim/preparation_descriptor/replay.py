#!/usr/bin/env python3
"""Source-bound focused replay against the freshly generated paired descriptor models.
The original runner intentionally retains the two pre-pipeline fixed-phase guards.
This continuation preserves their failures, tests phase-independent obligations,
and never changes or regenerates model objects.
"""
import argparse,hashlib,json,os,pathlib,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[3]
HERE=pathlib.Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--models',type=pathlib.Path,required=True)
ap.add_argument('--output',type=pathlib.Path,required=True)
a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=False)
frozen=json.loads((ROOT/'docs/recovery/preparation-descriptor-r1/receipt.json').read_text())
for n,h in frozen['source_inputs'].items():
    assert sha(ROOT/n)==h,'source drift: '+n
for arm,files in frozen['models'].items():
    for n,h in files.items():
        if n!='read_inventory':assert sha(a.models/arm/n)==h,'model drift: '+arm+'/'+n
receipt=dict(status='RUNNING',commands=[],model_receipt_sha256=sha(ROOT/'docs/recovery/preparation-descriptor-r1/receipt.json'),sources={p.name:sha(p) for p in HERE.glob('*.cpp')})
def save():(a.output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
def run(label,cmd,negative=None):
    with (a.output/(label+'.log')).open('w') as log:
        p=subprocess.run(list(map(str,cmd)),stdout=log,stderr=log,timeout=300,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0','UBSAN_OPTIONS':'halt_on_error=1'})
    text=(a.output/(label+'.log')).read_text();receipt['commands'].append(dict(label=label,argv=list(map(str,cmd)),exit=p.returncode,sha256=sha(a.output/(label+'.log'))));save()
    assert (p.returncode!=0 and negative in text) if negative else p.returncode==0,text[-2500:]
try:
    for arm,name,args in [('baseline','baseline_recovery_held',[]),('baseline','baseline_recovery_phase_positive',[]),('descriptor','ready_all_phase',['on']),('descriptor','normal_fault_overlap',[]),('descriptor','full_kill',[]),('descriptor','recovery_phase_positive',[]),('descriptor','recovery_cancel_negative',[]),('descriptor','reset_clocked',[]),('descriptor','qlive_cancel',[]),('descriptor','owner_reuse',[]),('descriptor','proof_control_scenarios',[]),('descriptor','proof_control_block_new',[]),('descriptor','pool_bare_preparation',[])]:
        model=a.models/arm;binary=a.output/name
        run(name+'-link',[os.environ['GSIM_CXX'],'-std=c++20','-O1','-g0','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(model),'-I'+str(HERE),'-I'+str(ROOT/'simulator/gsim/ready_store_query77'),HERE/(name+'.cpp'),*sorted(model.glob('ReadyStoreQuery77BackendGsim[0-9]*.o')),'-ldl','-o',binary])
        run(name,[binary,*args])
    run('data-negative',[a.output/'ready_all_phase','on','--mutate-data'],'independent execution data mismatch')
    run('retirement-negative',[a.output/'full_kill','--mutate-retirement'],'fault/killed/duplicate retirement')
    run('bare-negative',[a.output/'pool_bare_preparation','--mutate-bare-address'],'independent bare resident address mismatch')
    receipt['status']='PASS_FOCUSED_PHASE_AWARE_DESCRIPTOR_REPLAY';save()
except BaseException as e:
    receipt.update(status='FAILED_PRESERVE_EVIDENCE',failure=str(e));save();raise
