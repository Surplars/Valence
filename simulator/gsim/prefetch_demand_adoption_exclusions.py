#!/usr/bin/env python3
"""Add three dynamic exclusions using exact already-qualified ON objects only."""
import argparse, hashlib, json, os, re, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
TOP='CoherentCacheHomeGsim'
BASE_HEAD='507c81beefede7ecb806dc5219d65df8591ba5df'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def tracked():
    return {n:sha(ROOT/n) for n in subprocess.check_output(['git','ls-files','-z'],cwd=ROOT,text=True).split('\0') if n and (ROOT/n).is_file()}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qualified-models-from',type=Path,required=True)
    p.add_argument('--qualified-receipt-sha256',required=True)
    p.add_argument('--model-source-head',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--run-grant',action='store_true')
    a=p.parse_args();assert a.run_grant,'explicit host link/run grant required'
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT),'freeze source first'
    priorDir=a.qualified_models_from.resolve();priorPath=priorDir/'receipt.json'
    assert sha(priorPath)==a.qualified_receipt_sha256,'qualified receipt changed'
    prior=json.loads(priorPath.read_text())
    assert prior['status']=='PASS_COMPONENT_ONLY' and prior['source_head']==a.model_source_head
    assert prior['models']['off']['directed_cases']==2 and prior['models']['on']['directed_cases']==18
    assert any(c['name']=='on-positive' and c['exit']==0 for c in prior['commands'])
    assert len([c for c in prior['commands'] if c['name'].startswith('on-negative-') and c['exit']==1])==6
    frozen=tracked();head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    baseReceipt=ROOT.parent.parent/'prefetch-demand-adoption-candidate/focused-r4/receipt.json'
    assert sha(baseReceipt)=='46832fc00c59c49da0e31df49b247615387b172cc96ae80bb70d2031c782840c'
    base=json.loads(baseReceipt.read_text())['inputs']
    assert set(base)<=set(prior['inputs']),'model source omitted qualified base inputs'
    extra=set(prior['inputs'])-set(base)
    assert extra<={'docs/cache-route-grants.md','simulator/gsim/cache_route_grants.py'},'unrecognized model-only inputs'
    if extra:assert a.model_source_head=='db8394529f960622263e3c0d75fec4e2456285d4'
    changed={n:{'qualified_base':base[n],'model_source':prior['inputs'][n]} for n in base if base[n]!=prior['inputs'][n]}
    # Rebinding is explicit. The only supported future hardware revision is the
    # independently qualified cache route cone; no original PASS is inherited.
    assert set(changed)<={'src/main/scala/core/ooo/NonBlockingCoherentLineCache.scala'},changed
    assert not changed or a.model_source_head!=BASE_HEAD
    for n,h in base.items():
        if n!='simulator/gsim/harness/prefetch_demand_adoption_oracle.h':assert frozen[n]==h,'host overlay crossed unrelated source: '+n
    assert {k:sha(Path(k).resolve()) for k in prior['tools']}==prior['tools'],'qualified tools drifted'
    cxx=Path(os.environ['VALENCE_CLOUD_ENV'])/'sysroot/usr/bin/clang++-19'
    assert str(cxx) in prior['tools']
    model=priorDir/'on';artifacts=prior['models']['on']['artifacts']
    modelNames=['actual-parameters.json',TOP+'.fir',TOP+'.h']+[q.name for q in sorted(model.glob(TOP+'[0-9]*.cpp'))]+[q.name for q in sorted(model.glob(TOP+'[0-9]*.o'))]
    assert len([n for n in modelNames if n.endswith('.o')])==3
    hashes={n:sha(model/n) for n in modelNames}
    assert all(artifacts[n]==h for n,h in hashes.items()),'qualified model artifacts changed'
    actual=json.loads((model/'actual-parameters.json').read_text())
    assert actual['cacheConcurrency']['readPrefetchDemandAdoption'] is True
    assert actual==prior['models']['on']['actual_parameters']
    origin=priorDir;originReceipt=prior;chain=[]
    while not any(c['name']=='on-generate' and c['exit']==0 for c in originReceipt['commands']):
        binding=originReceipt['host_only_reuse'];nextPath=Path(binding['path'])/'receipt.json'
        assert sha(nextPath)==binding['receipt_sha256'],'reuse chain receipt changed'
        chain.append({'path':str(nextPath),'sha256':sha(nextPath)})
        origin=nextPath.parent;originReceipt=json.loads(nextPath.read_text())
    assert originReceipt['tools']==prior['tools']
    assert all(any(c['name']=='on-compile-'+str(i) and c['exit']==0 for c in originReceipt['commands']) for i in range(3))
    out=a.output.resolve();assert not out.exists(),'fresh evidence directory required';out.mkdir(parents=True)
    r={'schema':'prefetch-demand-adoption-exclusion-extension-v1','status':'RUNNING','source_head':head,'source_root':str(ROOT),
       'inputs':frozen,'tools':prior['tools'],'qualified_model_source_head':a.model_source_head,
       'qualified_receipt':str(priorPath),'qualified_receipt_sha256':sha(priorPath),'reuse_receipt_chain':chain,
       'original_generation_receipt':str(origin/'receipt.json'),'original_generation_receipt_sha256':sha(origin/'receipt.json'),
       'model_source_changes_from_adoption_base':changed,'model_only_inputs':{n:prior['inputs'][n] for n in sorted(extra)},
       'model_artifact_sha256':hashes,
       'model_resolved_paths':{n:str((model/n).resolve()) for n in modelNames},'actual_parameters':actual,
       'original_component_pass':{'off_cases':2,'on_cases':18,'negative_cases':6,'rerun':False},
       'extension_cases':3,'model_compiles':0,'gsim_generations':0,'compiler_jobs':1,'commands':[],
       'executing_cpu':False,'physical_qualification':False,'performance_qualification':False,
       'probe_attach_conflict':'UNREACHED: real home serializes DMA maintenance behind active Acquire; no B injection input',
       'memory_oracle_bytes':131072}
    def save():(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
    def checkFrozen():
        assert tracked()==frozen,'extension source drift'
        assert sha(priorPath)==a.qualified_receipt_sha256,'qualified receipt drift'
        assert {n:sha(model/n) for n in modelNames}==hashes,'model artifact drift'
        assert {k:sha(Path(k).resolve()) for k in prior['tools']}==prior['tools'],'tool drift'
    def step(name,cmd,expected,anchor,timeout=120):
        checkFrozen();cmd=list(map(str,cmd));log=out/(name+'.log');usage=out/(name+'-resource.txt')
        print('+ '+' '.join(cmd),flush=True);start=time.monotonic()
        wrapper='import json,resource,subprocess,sys; from pathlib import Path; r=subprocess.run(sys.argv[2:]); Path(sys.argv[1]).write_text(json.dumps({"max_rss_kib":resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss})); sys.exit(r.returncode)'
        with log.open('x') as f:result=subprocess.run([sys.executable,'-c',wrapper,str(usage),*cmd],cwd=ROOT,
            stdout=f,stderr=subprocess.STDOUT,timeout=timeout,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        text=log.read_text();rss=json.loads(usage.read_text())['max_rss_kib']
        r['commands'].append({'name':name,'argv':cmd,'exit':result.returncode,'expected_exit':expected,
            'seconds':time.monotonic()-start,'max_rss_kib':rss,'log_sha256':sha(log),'resource_sha256':sha(usage)});save()
        assert result.returncode==expected and anchor in text,f'{name} failed: {text[-6000:]}'
        assert not re.search(r'ERROR: AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|LeakSanitizer',text)
        assert rss<=512*1024,'host-only process exceeded assigned 512 MiB budget'
        return text
    try:
        save()
        flags=['-std=c++20','-O1','-g','-gz=zlib','-fsanitize=address,undefined','-fno-sanitize-recover=all',
            '-I'+str(model),'-I'+str(ROOT/'simulator/gsim/harness'),'-DSPLIT_PREFETCH_TRACKING=1',
            '-DSTORE_PF_LRU_ON=0','-DPF_CANDIDATE_CYCLES=16','-DCACHE_WAYS=2','-DREAD_PF_DIRTY_RETRY=1',
            '-DREAD_PF_DEMAND_ADOPTION=1','-DREAD_MSHRS=2','-DCACHE_LINES=512','-DRESPONSE_ENTRIES=2','-DAXI_SLOTS=4']
        binary=out/'run';host=ROOT/'simulator/gsim/harness/prefetch_demand_adoption_exclusions.cpp'
        step('host-link',[cxx,*flags,host,*sorted(model.glob(TOP+'[0-9]*.o')),'-ldl','-o',binary],0,'')
        result=step('positive',[binary,'--images='+str(out/'images')],0,'PREFETCH_ADOPTION_EXCLUSIONS_PASS cases=3')
        cases=[]
        for line in result.splitlines():
            if line.startswith('PREFETCH_ADOPTION_EXCLUSION_RESULT '):cases.append(dict(x.split('=',1) for x in line.split()[1:]))
        assert [x['name'] for x in cases]==['ordinary_store','atomic_add','uncached_read']
        r['case_results']=cases
        for case in cases:
            assert case['accepted']==case['responses']=='1' and case['attach']=='0'
            assert int(case['stable_offer_samples'])>=9
            if case['name']!='uncached_read':assert int(case['changed_bytes'])>0
        for name in ('ordinary_store','atomic_add','uncached_read'):
            step('negative-'+name,[binary,'--inject-class='+name],1,
                'PREFETCH_ADOPTION_EXCLUSION_NEGATIVE name='+name+' changed_external_class=1 actual_attach=1 actual_accept_delta=1')
        images=sorted((out/'images').glob('*-expected.bin'));assert len(images)==3
        r['images']={}
        for expected in images:
            actualImage=expected.with_name(expected.name.replace('-expected.bin','-actual.bin'))
            assert expected.stat().st_size==131072 and sha(expected)==sha(actualImage)
            r['images'][expected.stem.replace('-expected','')]={'bytes':131072,'expected_sha256':sha(expected),'actual_sha256':sha(actualImage)}
        checkFrozen();r['binary_sha256']=sha(binary);r['status']='PASS_THREE_EXCLUSIONS_COMPONENT_ONLY'
    except BaseException as e:r['status']='FAIL';r['error']=str(e);raise
    finally:save()
    print(r['status'],out/'receipt.json',flush=True)
if __name__=='__main__':main()
