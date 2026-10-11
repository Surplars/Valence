#!/usr/bin/env python3
"""Portable narrow paired real-cache gate; --execute opts into serial build/run."""
import argparse, hashlib, json, os, re, shutil, subprocess, time
from pathlib import Path
import bound_store_replay_common as portable
ROOT=Path(__file__).resolve().parents[2]
TOP='CoherentCacheHomeGsim'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def inputs():
    return portable.source_inputs(ROOT,[Path(__file__),*sorted((ROOT/'simulator/gsim/harness').glob('*'))])
def main():
    global ROOT
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--execute','--run-grant',dest='execute',action='store_true')
    p.add_argument('--reuse-models-from',type=Path);p.add_argument('--reuse-receipt-sha256')
    portable.add_paths(p,ROOT);a=p.parse_args();ROOT=a.source_root.resolve()
    paths=portable.tool_paths(a,p);gsim=paths['gsim'];cxx=paths['cxx'];mill=paths['mill']
    toolhash=portable.tool_binding(paths)
    prior=portable.verified_receipt(a.reuse_models_from,a.reuse_receipt_sha256) if a.reuse_models_from else None
    if prior:
        assert prior['tools']==toolhash,'reuse tool identity differs; rebuild fresh'
        portable.check_dependencies(prior.get('dependencies',{}))
        assert prior['inputs'].keys()==inputs().keys(),'reuse source closure differs; rebuild fresh'
        changed={n for n,h in inputs().items() if h!=prior['inputs'][n]}
        assert changed<={'simulator/gsim/read_prefetch_store_hold.py','simulator/gsim/harness/read_prefetch_store_hold.cpp'},'reuse model inputs changed; rebuild fresh'
        for label in ('off','on'):portable.verify_model_inputs(a.reuse_models_from/label,prior['models'][label]['artifacts'])
    if portable.preflight(a,inputs(),paths):return
    if not a.execute:p.error('execution requires --execute; --preflight-only does not build or run')
    out=a.output.resolve();assert not out.exists(),'fresh evidence required';out.mkdir(parents=True)
    r={'schema':'bound-store-portable-component-v1','status':'RUNNING','source_root':str(ROOT),
       'source_head':portable.source_revision(ROOT),
       'inputs':inputs(),'tools':toolhash,'commands':[],'models':{},'dependencies':{},'compiler_jobs':1,
       'gsim_cpp_max_size_KB':1024,'executing_cpu':False,'physical_qualification':False,
       'qualification_inherited':False,'memory_oracle_bytes':131072,'posted_generation_bits':64}
    def save():(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
    def step(name,cmd,expected=0,anchor=None,timeout=900):
        assert inputs()==r['inputs'],'frozen source drift'
        portable.check_tools(toolhash)
        if a.reuse_models_from:assert sha(a.reuse_models_from/'receipt.json')==a.reuse_receipt_sha256,'reuse receipt drift'
        if r['dependencies']:portable.check_dependencies(r['dependencies'])
        for label,item in r.get('reused_models',{}).items():portable.verify_model_inputs(out/label,item['artifacts'])
        cmd=list(map(str,cmd));print('+ '+' '.join(cmd),flush=True);start=time.monotonic();log=out/(name+'.log')
        with log.open('x')as f:q=subprocess.run(portable.command_args(cmd,paths),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=timeout,
            env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0','PYTHONDONTWRITEBYTECODE':'1'})
        t=log.read_text();r['commands'].append({'name':name,'argv':cmd,'exit':q.returncode,'expected_exit':expected,
            'seconds':time.monotonic()-start,'log_sha256':sha(log)});save()
        assert q.returncode==expected,f'{name} failed: {t[-5000:]}'
        assert not re.search(r'ERROR: AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|LeakSanitizer',t),name
        if anchor:assert anchor in t,f'{name} lacks {anchor}'
        return t
    try:
        if prior:r['dependencies'].update(prior['dependencies'])
        save()
        if a.reuse_models_from:
            assert prior['tools']==toolhash and prior['inputs'].keys()==r['inputs'].keys()
            changed={n for n in r['inputs']if r['inputs'][n]!=prior['inputs'][n]}
            assert changed<={'simulator/gsim/read_prefetch_store_hold.py','simulator/gsim/harness/read_prefetch_store_hold.cpp'},changed
            r['host_only_reuse']={'path':str(a.reuse_models_from.resolve()),'receipt_sha256':sha(a.reuse_models_from/'receipt.json'),'changed':sorted(changed)}
            assert any(c['name']=='configuration'and c['exit']==0 for c in prior['commands'])or prior.get('host_only_reuse')
        else:step('configuration',[mill,'-i','-j','1','IonSoC.test.testOnly','ooo.ReadPrefetchStoreHoldConfigSpec'],anchor='All tests passed')
        for enabled in (0,1):
            label='on'if enabled else'off';model=out/label;model.mkdir()
            old=a.reuse_models_from/label if prior else None
            reused=bool(old and list(old.glob(TOP+'[0-9]*.o')) and len(list(old.glob(TOP+'[0-9]*.o')))==len(list(old.glob(TOP+'[0-9]*.cpp'))))
            if reused:
                artifacts={}
                for q in sorted(old.iterdir()):
                    if q.name=='actual-parameters.json'or q.suffix in('.fir','.h','.cpp','.o'):
                        artifacts[q.name]=sha(q);(model/q.name).symlink_to(q.resolve())
                r.setdefault('reused_models',{})[label]={'source_receipt':str(a.reuse_models_from/'receipt.json'),'source_head':prior['source_head'],
                    'artifacts':artifacts,'hash_timing':'current reuse startup; original successful emit/generate/compile logs and frozen inputs remain bound'};save()
            else:step(label+'-emit',[mill,'-i','-j','1','IonSoC.test.runMain','ooo.ReadPrefetchStoreHoldGsimMain',model,enabled])
            actual=json.loads((model/'actual-parameters.json').read_text());c=actual['cacheConcurrency']
            assert c['readPrefetchStoreHold']==bool(enabled)and c['prefetchCandidateCycles']==16
            assert c['readPrefetchDemandAdoption']and c['readPrefetchDirtyRetry']and c['splitPrefetchTracking']
            assert actual['postedConfig']['generationBits']==64
            assert actual['cacheMshrs']==actual['cacheResponses']==actual['cacheWritebacks']==2
            assert actual['cacheWays']==2 and actual['cacheLines']==512
            if not reused:step(label+'-generate',[gsim,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(model),model/(TOP+'.fir')])
            flags=['-std=c++20','-O1','-g','-gz=zlib','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                '-I'+str(model),'-I'+str(ROOT/'simulator/gsim/harness'),'-DSPLIT_PREFETCH_TRACKING=1','-DSTORE_PF_LRU_ON=0',
                '-DPF_CANDIDATE_CYCLES=16','-DCACHE_WAYS=2','-DREAD_PF_DIRTY_RETRY=1','-DREAD_PF_DEMAND_ADOPTION=1',
                '-DREAD_PF_STORE_HOLD='+str(enabled),'-DREAD_MSHRS=2','-DCACHE_LINES=512','-DRESPONSE_ENTRIES=2','-DAXI_SLOTS=4']
            units=sorted(model.glob(TOP+'[0-9]*.cpp'));assert units;objects=[]
            for i,unit in enumerate(units):
                obj=unit.with_suffix('.o')
                if not reused:
                    dep=obj.with_suffix('.d');step(label+'-compile-'+str(i),[cxx,*flags,'-MD','-MF',dep,'-c',unit,'-o',obj])
                    portable.record_dependencies(dep,ROOT,r['dependencies']);save()
                else:assert sha(obj)==r['reused_models'][label]['artifacts'][obj.name]
                objects.append(obj)
            binary=model/'run';step(label+'-link',[cxx,*flags,ROOT/'simulator/gsim/harness/read_prefetch_store_hold.cpp',*objects,'-ldl','-o',binary])
            text=step(label+'-positive',[binary,'--images='+str(model/'images')],anchor='READ_PREFETCH_STORE_HOLD_PASS',timeout=240)
            assert 'cases=12' in text
            if enabled:step(label+'-negative-hold-next',[binary,'--inject-hold-next'],expected=1,
                anchor='mutated real hold NEXT rejected',timeout=120)
            images=sorted((model/'images').glob('*-expected.bin'));assert len(images)==12
            for expected in images:
                observed=expected.with_name(expected.name.replace('-expected.bin','-actual.bin'))
                assert expected.stat().st_size==131072 and sha(expected)==sha(observed)
            r['models'][label]={'actual_parameters':actual,'directed_cases':12,'split_units':len(units),
                'artifacts':{str(q.relative_to(model)):sha(q)for q in model.rglob('*')if q.is_file()}};save()
        off=r['models']['off']['actual_parameters'];on=r['models']['on']['actual_parameters']
        oc=dict(off['cacheConcurrency']);nc=dict(on['cacheConcurrency']);assert not oc.pop('readPrefetchStoreHold');assert nc.pop('readPrefetchStoreHold');assert oc==nc
        for k in ('cacheGeometry','homeGeometry','cacheLines','cacheWays','cacheMshrs','cacheResponses','cacheWritebacks',
            'homeTrackedLines','homeTrackedWays','homeAcquireEntries','homeWritebackEntries','axiSlots','postedEnabled','postedGenerationBits','cacheTagConfig','postedConfig'):assert off[k]==on[k],k
        for image in(out/'off/images').glob('*-expected.bin'):assert sha(image)==sha(out/'on/images'/image.name)
        assert inputs()==r['inputs'];r['status']='PASS_COMPONENT_ONLY'
    except BaseException as e:r['status']='FAIL';r['error']=str(e);raise
    finally:save()
    print(r['status'],out/'receipt.json',flush=True)
if __name__=='__main__':main()
