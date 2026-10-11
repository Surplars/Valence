#!/usr/bin/env python3
"""Narrow lifetime1/16 gate: reuse qualified L1 objects, build only the L16 model."""
import argparse, hashlib, json, os, pathlib, re, subprocess, time
ROOT=pathlib.Path(__file__).resolve().parents[2]
TOP='CoherentCacheHomeGsim'
def sha(path):return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
def sources():
    names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    return {n:sha(ROOT/n) for n in names if n and (ROOT/n).is_file()}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True,type=pathlib.Path)
    p.add_argument('--donor',required=True,type=pathlib.Path)
    p.add_argument('--run-grant',action='store_true');a=p.parse_args()
    assert a.run_grant,'explicit serial run grant required'
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT),'commit source first'
    out=a.output.resolve();donor=a.donor.resolve()
    assert not out.exists(),'fresh output required'
    prior=json.loads((donor/'receipt.json').read_text())
    assert prior['status']=='PASS_COMPONENT_ONLY' and prior['lifetime']==1 and prior['store_lru']==0 and prior['ways']==2
    assert prior['models']['on']['actual_parameters']['cacheConcurrency']['independentDemandAdmission']
    for name,digest in prior['inputs'].items():
        if name.startswith('src/') or name.startswith('simulator/gsim/harness/'):
            assert sha(ROOT/name)==digest,'qualified original model/harness source changed: '+name
    model1=donor/'on'
    for name,digest in prior['models']['on']['artifacts'].items():
        assert sha(model1/name)==digest,'qualified donor artifact drift: '+name
    tool=pathlib.Path(os.environ['VALENCE_CLOUD_ENV'])
    gsim=tool/'gsim-src/build/gsim/gsim';cxx=tool/'sysroot/usr/bin/clang++-19'
    assert prior['tools'][str(cxx.resolve())]==sha(cxx.resolve())
    assert prior['tools'][str(gsim)]==sha(gsim)
    out.mkdir(parents=True)
    r={'schema':'dual-prefetch-dirty-demand-retention-v1','status':'RUNNING',
       'source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
       'inputs':sources(),'donor_receipt':str(donor/'receipt.json'),'donor_receipt_sha256':sha(donor/'receipt.json'),
       'donor_model_artifacts':prior['models']['on']['artifacts'],
       'tools':{str(gsim):sha(gsim),str(cxx.resolve()):sha(cxx.resolve())},'commands':[],'models':{},
       'scope':'Only actual dirty-demand/read-candidate capture/send retention and existing demand/flush cancellation',
       'executing_cpu':False,'physical_qualification':False}
    def save():(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
    def step(name,cmd,code=0,anchor=None):
        assert sources()==r['inputs'],'frozen source drift'
        assert all(sha(path)==digest for path,digest in r['tools'].items()),'tool drift'
        log=out/(name+'.log');cmd=list(map(str,cmd));start=time.monotonic()
        print('+ '+' '.join(cmd),flush=True)
        with log.open('x') as f:
            result=subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=600,
                                  env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0','PYTHONDONTWRITEBYTECODE':'1'})
        text=log.read_text();r['commands'].append({'name':name,'argv':cmd,'exit':result.returncode,
            'expected_exit':code,'seconds':time.monotonic()-start,'log_sha256':sha(log)});save()
        assert result.returncode==code,f'{name}: {text[-4000:]}'
        assert not re.search(r'ERROR: AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|LeakSanitizer',text),name
        if anchor:assert anchor in text,f'{name}: missing {anchor}'
        return text
    try:
        save()
        for life in (1,16):
            label='life'+str(life);dest=out/label;dest.mkdir()
            model=model1 if life==1 else dest/'model'
            if life==16:
                model.mkdir()
                step(label+'-emit',['mill','-i','-j','1','IonSoC.test.runMain','ooo.DualPrefetchTrackingGsimMain',model,1,0,16,2])
                actual=json.loads((model/'actual-parameters.json').read_text())
                expected=json.loads((model1/'actual-parameters.json').read_text())
                expected['cacheConcurrency']['prefetchCandidateCycles']=16
                assert actual==expected,'L16 actual component differs beyond existing candidate lifetime'
                step(label+'-generate',[gsim,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(model),model/(TOP+'.fir')])
            flags=['-std=c++20','-O1','-g','-gz=zlib','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                   '-I'+str(model),'-I'+str(ROOT/'simulator/gsim/harness'),'-DSPLIT_PREFETCH_TRACKING=1',
                   '-DSTORE_PF_LRU_ON=0','-DPF_CANDIDATE_CYCLES='+str(life),'-DCACHE_WAYS=2',
                   '-DREAD_MSHRS=2','-DCACHE_LINES=512','-DRESPONSE_ENTRIES=2','-DAXI_SLOTS=4']
            units=sorted(model.glob(TOP+'[0-9]*.cpp'));assert units
            objects=[unit.with_suffix('.o') for unit in units]
            if life==16:
                for i,(unit,obj) in enumerate(zip(units,objects)):
                    step(label+'-compile-'+str(i),[cxx,*flags,'-c',unit,'-o',obj])
            else:
                for obj in objects:assert sha(obj)==prior['models']['on']['artifacts'][obj.name]
            binary=dest/'run'
            step(label+'-link',[cxx,*flags,ROOT/'simulator/gsim/harness/dual_prefetch_retention.cpp',*objects,'-ldl','-o',binary])
            step(label+'-positive',[binary,'--images='+str(dest/'images')],anchor='DUAL_PREFETCH_RETENTION_PASS')
            text=step(label+'-negative',[binary,'--inject-retention-expectation'],code=1,
                      anchor='DUAL_PREFETCH_RETENTION_MUTATION_TRIGGER retention-expectation')
            assert 'retention allocation differs from explicit lifetime expectation' in text
            r['models'][label]={'model_reused':life==1,'model_directory':str(model),
                'objects':{str(obj):sha(obj) for obj in objects},
                'artifacts':{str(path.relative_to(dest)):sha(path) for path in dest.rglob('*') if path.is_file()}}
            save()
        assert sources()==r['inputs'],'final source drift'
        r['status']='PASS_RETENTION_COMPONENT_ONLY'
    except BaseException as e:r['status']='FAIL';r['error']=str(e);raise
    finally:save()
    print(r['status'],out/'receipt.json',flush=True)
if __name__=='__main__':main()
