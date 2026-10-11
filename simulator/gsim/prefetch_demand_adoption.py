#!/usr/bin/env python3
"""Frozen-source serial real posted-enabled cache/home demand-adoption gate."""
import argparse, hashlib, json, os, re, shutil, subprocess, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
TOP='CoherentCacheHomeGsim'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def inputs():
    names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT,text=True).split('\0')
    return {n:sha(ROOT/n) for n in names if n and (ROOT/n).is_file()}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--run-grant',action='store_true')
    p.add_argument('--reuse-models-from',type=Path,help='only frozen host-only revision; verify exact generated hardware inputs')
    a=p.parse_args()
    if not a.run_grant:p.error('explicit serial build/run slot required')
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT),'freeze and commit source first'
    out=a.output.resolve();assert not out.exists(),'fresh evidence directory required';out.mkdir(parents=True)
    env=Path(os.environ['VALENCE_CLOUD_ENV']);gsim=env/'gsim-src/build/gsim/gsim';cxx=env/'sysroot/usr/bin/clang++-19';mill=Path(shutil.which('mill'))
    tools={str(x):sha(x.resolve()) for x in (gsim,cxx,mill)}
    receipt={'schema':'prefetch-demand-adoption-component-gate-v1','status':'RUNNING',
        'source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'source_root':str(ROOT),'inputs':inputs(),'tools':tools,'commands':[],'models':{},
        'compiler_jobs':1,'gsim_cpp_max_size_KB':1024,'executing_cpu':False,'physical_qualification':False,
        'qualification_inherited':False,'memory_oracle_bytes':131072,'posted_enabled':True,'posted_generation_bits':64,
        'dynamic_generation_exhausted_fallback':False,'ordinary_checked_physical_boundary':True}
    def save(): (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    def step(name,cmd,expected=0,anchor=None,timeout=900):
        assert inputs()==receipt['inputs'],'frozen source drift'
        assert {k:sha(Path(k).resolve()) for k in tools}==tools,'tool drift'
        cmd=list(map(str,cmd));print('+ '+' '.join(cmd),flush=True);start=time.monotonic();log=out/(name+'.log')
        with log.open('x')as f:r=subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=timeout,
            env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0','PYTHONDONTWRITEBYTECODE':'1'})
        text=log.read_text();receipt['commands'].append({'name':name,'argv':cmd,'exit':r.returncode,
            'expected_exit':expected,'seconds':time.monotonic()-start,'log_sha256':sha(log)});save()
        assert r.returncode==expected,f'{name} failed: {text[-5000:]}'
        assert not re.search(r'ERROR: AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|LeakSanitizer',text),name
        if anchor:assert anchor in text,f'{name} lacks {anchor}'
        return text
    prior=None
    try:
        save()
        if a.reuse_models_from:
            prior=json.loads((a.reuse_models_from/'receipt.json').read_text())
            allowed={'simulator/gsim/prefetch_demand_adoption.py','simulator/gsim/harness/prefetch_demand_adoption.cpp',
                'simulator/gsim/harness/prefetch_demand_adoption_oracle.h','simulator/gsim/harness/prefetch_demand_adoption_transport.h'}
            assert prior['tools']==tools and set(prior['inputs'])==set(receipt['inputs'])
            changed={n for n in receipt['inputs']if receipt['inputs'][n]!=prior['inputs'][n]}
            assert changed<=allowed,'reuse crosses production or wrapper change: '+str(changed)
            assert any(c['name']=='configuration' and c['exit']==0 for c in prior['commands']) or prior.get('host_only_reuse'),'reuse lacks configuration provenance'
            receipt['host_only_reuse']={'path':str(a.reuse_models_from.resolve()),'receipt_sha256':sha(a.reuse_models_from/'receipt.json'),'changed':sorted(changed)}
        else:
            step('configuration',[mill,'-i','-j','1','IonSoC.test.testOnly','ooo.ReadPrefetchDemandAdoptionConfigSpec',
                'ooo.ReadPrefetchDirtyRetryConfigSpec','ooo.SplitPrefetchTrackingConfigSpec'],anchor='All tests passed')
        for enabled in (0,1):
            label='on' if enabled else 'off';model=out/label;model.mkdir()
            reused=bool(prior and (a.reuse_models_from/label).is_dir())
            if reused:
                old=a.reuse_models_from/label
                for q in sorted(old.iterdir()):
                    if q.name=='actual-parameters.json' or q.suffix in ('.fir','.h','.cpp','.o'):(model/q.name).symlink_to(q.resolve())
                origin=a.reuse_models_from.resolve();origin_receipt=prior
                while not any(c['name']==label+'-generate' and c['exit']==0 for c in origin_receipt['commands']):
                    assert origin_receipt.get('host_only_reuse'),'missing original generation provenance'
                    origin=Path(origin_receipt['host_only_reuse']['path'])
                    origin_receipt=json.loads((origin/'receipt.json').read_text())
                artifact_names=['actual-parameters.json',TOP+'.fir',TOP+'.h']
                artifact_names += [q.name for q in sorted(old.glob(TOP+'[0-9]*.cpp'))]
                artifact_names += [q.name for q in sorted(old.glob(TOP+'[0-9]*.o'))]
                artifact_hashes={name:sha(old/name) for name in artifact_names}
                archived=prior.get('models',{}).get(label,{}).get('artifacts',{})
                if archived:
                    for name,digest in artifact_hashes.items():assert archived[name]==digest,'reused artifact changed'
                receipt.setdefault('reused_models',{})[label]={'original_source_head':origin_receipt['source_head'],
                    'original_receipt':str(origin/'receipt.json'),'original_receipt_sha256':sha(origin/'receipt.json'),
                    'original_tools':origin_receipt['tools'],
                    'original_commands':[c for c in origin_receipt['commands']if c['name'].startswith(label+'-compile')],
                    'artifact_sha256':artifact_hashes,'hash_timing':'captured at current reuse startup; compared to prior PASS artifact hashes where available',
                    'inherited_functional_qualification':False}
                save()
            else:
                step(label+'-emit',[mill,'-i','-j','1','IonSoC.test.runMain','ooo.ReadPrefetchDemandAdoptionGsimMain',model,enabled])
            actual=json.loads((model/'actual-parameters.json').read_text());c=actual['cacheConcurrency']
            baseline=json.loads((ROOT/'simulator/gsim/config/prefetch-demand-adoption-matched-b.json').read_text())
            normalized=dict(c);normalized.pop('readPrefetchDemandAdoption')
            assert normalized==baseline['cache'],'complete actual B cache concurrency mismatch'
            assert actual['cacheTagConfig']==baseline['expected_cache_tag_config']
            pc=actual['postedConfig'];assert pc['enabled'] and pc['generationBits']==64 and pc['epochBits']==32
            assert pc['lineEntries']==2 and pc['storeEntries']==16 and pc['cacheSets']==256 and pc['cacheWays']==2
            assert pc['readMshrs']==pc['responseEntries']==pc['writebackEntries']==2
            assert pc['guaranteedBase']==actual['cacheGeometry']['base'] and pc['guaranteedBytes']==131072
            assert c['readPrefetchDemandAdoption']==bool(enabled)
            for name in ('readPrefetchDirtyRetry','splitPrefetchTracking','independentDemandAdmission','nextLinePrefetch',
                'storeNextLinePrefetch','storePrefetchMruInsertion','overlapWritebackRefill'):assert c[name],name
            assert c['prefetchCandidateCycles']==16 and not c['storePrefetchLruVictim'] and not c['distinctWayRelease']
            assert actual['postedEnabled'] and actual['postedGenerationBits']==64
            assert actual['cacheMshrs']==actual['cacheResponses']==actual['cacheWritebacks']==actual['homeAcquireEntries']==actual['homeWritebackEntries']==2
            assert actual['cacheWays']==2 and actual['cacheLines']==512
            if not reused:step(label+'-generate',[gsim,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(model),model/(TOP+'.fir')])
            units=sorted(model.glob(TOP+'[0-9]*.cpp'));assert units
            flags=['-std=c++20','-O1','-g','-gz=zlib','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                '-I'+str(model),'-I'+str(ROOT/'simulator/gsim/harness'),'-DSPLIT_PREFETCH_TRACKING=1','-DSTORE_PF_LRU_ON=0',
                '-DPF_CANDIDATE_CYCLES=16','-DCACHE_WAYS=2','-DREAD_PF_DIRTY_RETRY=1','-DREAD_PF_DEMAND_ADOPTION='+str(enabled),
                '-DREAD_MSHRS=2','-DCACHE_LINES=512','-DRESPONSE_ENTRIES=2','-DAXI_SLOTS=4']
            objects=[]
            for i,unit in enumerate(units):
                obj=unit.with_suffix('.o')
                if not reused:step(label+'-compile-'+str(i),[cxx,*flags,'-c',unit,'-o',obj])
                else:
                    assert obj.is_file() and any(c['name']==label+'-compile-'+str(i) and c['exit']==0 for c in origin_receipt['commands'])
                    assert sha(obj)==receipt['reused_models'][label]['artifact_sha256'][obj.name]
                objects.append(obj)
            binary=model/'run';step(label+'-link',[cxx,*flags,ROOT/'simulator/gsim/harness/prefetch_demand_adoption.cpp',*objects,'-ldl','-o',binary])
            result=step(label+'-positive',[binary,'--images='+str(model/'images')],anchor='PREFETCH_DEMAND_ADOPTION_PASS',timeout=240)
            expected_cases=18 if enabled else 2
            assert f'cases={expected_cases}' in result,'directed case inventory differs'
            if enabled:
                negatives=[('cpu-byte','CPU independent byte oracle mismatch'),('dirty-byte','dirty release byte oracle mismatch'),('wrong-pa','attachment lost exact issued read-PF full PA/phase'),
                    ('wrong-tag','refill transaction tag differs from original issued PF kind'),
                    ('duplicate-cpu','duplicate CPU response violates accepted-ticket ownership'),
                    ('lost-wb','ReleaseAck lost independently saved WB obligation')]
                for mutation,message in negatives:
                    step(label+'-negative-'+mutation,[binary,'--inject-'+mutation],expected=1,anchor=message,timeout=120)
            images=sorted((model/'images').glob('*-expected.bin'));assert len(images)==expected_cases
            for expected in images:
                actual_image=expected.with_name(expected.name.replace('-expected.bin','-actual.bin'))
                assert expected.stat().st_size==131072 and sha(expected)==sha(actual_image)
            receipt['models'][label]={'actual_parameters':actual,'directed_cases':expected_cases,'split_units':len(units),
                'artifacts':{str(q.relative_to(model)):sha(q) for q in model.rglob('*')if q.is_file()}};save()
        off=receipt['models']['off']['actual_parameters'];on=receipt['models']['on']['actual_parameters']
        oc=dict(off['cacheConcurrency']);nc=dict(on['cacheConcurrency']);assert oc.pop('readPrefetchDemandAdoption')is False;assert nc.pop('readPrefetchDemandAdoption')is True;assert oc==nc
        for k in ('cacheGeometry','homeGeometry','cacheLines','cacheWays','cacheMshrs','cacheResponses','cacheWritebacks',
            'homeTrackedLines','homeTrackedWays','homeAcquireEntries','homeWritebackEntries','axiSlots','postedEnabled','postedGenerationBits','cacheTagConfig','postedConfig'):assert off[k]==on[k],k
        for image in (out/'off/images').glob('*-expected.bin'):assert sha(image)==sha(out/'on/images'/image.name)
        assert inputs()==receipt['inputs'];receipt['status']='PASS_COMPONENT_ONLY'
    except BaseException as e:
        receipt['status']='FAIL';receipt['error']=str(e);raise
    finally:save()
    print(receipt['status'],out/'receipt.json',flush=True)
if __name__=='__main__':main()
