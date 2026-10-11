#!/usr/bin/env python3
"""One frozen synthetic-manager adoption-ON B-conflict model and actual no-B negative."""
import argparse,hashlib,json,os,re,shutil,subprocess,sys,time
from pathlib import Path
from ports import emit_driver
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];TOP='PostedPrefetchCoexistGsim'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def inputs():
    return {n:sha(ROOT/n) for n in subprocess.check_output(['git','ls-files','-z'],cwd=ROOT,text=True).split('\0') if n and (ROOT/n).is_file()}
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--run-grant',action='store_true')
    p.add_argument('--reuse-model-from',type=Path)
    a=p.parse_args();assert a.run_grant,'exclusive one-model heavy slot required'
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT),'source must be committed and clean'
    out=a.output.resolve();assert not out.exists(),'fresh attempt required';out.mkdir(parents=True)
    env=Path(os.environ['VALENCE_CLOUD_ENV']);cxx=env/'sysroot/usr/bin/clang++-19';gsim=env/'gsim-src/build/gsim/gsim';mill=Path(shutil.which('mill'))
    tools={str(p):sha(p.resolve()) for p in (cxx,gsim,mill)};frozen=inputs()
    r={'schema':'prefetch-adoption-raw-b-contract-v1','status':'RUNNING','source_root':str(ROOT),
       'source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
       'production_base':'db8394529f960622263e3c0d75fec4e2456285d4','inputs':frozen,'tools':tools,'commands':[],
       'scope':'real posted cache/engine/SRAM, synthetic TL manager; no natural Mixed-home B/attach schedule claim',
       'configuration':{'readPrefetchDemandAdoption':True,'independentDemandAdmission':True,'splitPrefetchTracking':True,
          'readPrefetchDirtyRetry':True,'postedPrefetchCoexistence':True,'storePrefetchMruInsertion':True,
          'prefetchCandidateCycles':16,'generationBits':64,'readMshrs':2,'responseEntries':2,'writebackEntries':2,
          'cacheLines':16,'cacheWays':2,'base':4096,'bytes':4096},
       'compiler_jobs':1,'gsim_cpp_max_size_KB':1024,'models':1,'cases':1,'negative_controls':1,
       'model_reuse':False,'historical_pass_inherited':False,'executing_cpu':False,'physical_qualification':False}
    def save():(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
    def step(name,cmd,expected=0,anchor='',timeout=900):
        assert inputs()==frozen;assert {k:sha(Path(k).resolve()) for k in tools}==tools
        cmd=list(map(str,cmd));log=out/(name+'.log');usage=out/(name+'-resource.json');start=time.monotonic()
        wrapper='import json,resource,subprocess,sys; from pathlib import Path; r=subprocess.run(sys.argv[2:]); Path(sys.argv[1]).write_text(json.dumps({"max_rss_kib":resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss})); sys.exit(r.returncode)'
        print('+ '+name+' '+' '.join(cmd),flush=True)
        with log.open('x') as f:result=subprocess.run([sys.executable,'-c',wrapper,str(usage),*cmd],cwd=ROOT,
             stdout=f,stderr=subprocess.STDOUT,timeout=timeout,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0','PYTHONDONTWRITEBYTECODE':'1'})
        text=log.read_text();r['commands'].append({'name':name,'argv':cmd,'exit':result.returncode,'expected_exit':expected,
          'seconds':time.monotonic()-start,'max_rss_kib':json.loads(usage.read_text())['max_rss_kib'],'log_sha256':sha(log)});save()
        assert result.returncode==expected and anchor in text,name+': '+text[-6000:]
        assert not re.search(r'ERROR: AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|LeakSanitizer',text)
        assert inputs()==frozen
    try:
        save();model=out/'model';model.mkdir()
        if a.reuse_model_from:
            priorDir=a.reuse_model_from.resolve();prior=json.loads((priorDir/'receipt.json').read_text())
            checkpoint=json.loads((priorDir/'model-checkpoint.json').read_text())
            assert sha(priorDir/'receipt.json')==checkpoint['receipt_sha256']
            assert prior['tools']==tools and set(prior['inputs'])==set(frozen)
            changed={n for n in frozen if frozen[n]!=prior['inputs'][n]}
            assert changed<={'simulator/gsim/prefetch_adoption_probe/fixture.py','simulator/gsim/prefetch_adoption_probe/run.py'}
            assert all(any(c['name']==name and c['exit']==0 for c in prior['commands'])
                for name in ['emit','generate','compile-0','compile-1','host-link'])
            for name,digest in checkpoint['model_artifact_sha256'].items():
                path=priorDir/'model'/name;assert sha(path)==digest;(model/name).symlink_to(path.resolve())
            r['model_reuse']={'receipt':str(priorDir/'receipt.json'),'sha256':sha(priorDir/'receipt.json'),
                'checkpoint_sha256':sha(priorDir/'model-checkpoint.json'),'artifacts':checkpoint['model_artifact_sha256'],
                'changed_host_inputs':sorted(changed),'model_compiles_this_attempt':0}
            binary=model/'run';save()
        else:
            step('emit',[mill,'-i','-j','1','IonSoC.test.runMain','ooo.ReadPrefetchAdoptionProbeGsimMain',model])
            step('generate',[gsim,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(model),model/(TOP+'.fir')])
            driver=model/'driver.cpp';emit_driver(driver)
            flags=['-std=c++20','-O1','-g','-gz=zlib','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(model)]
            step('host-syntax',[cxx,*flags,'-fsyntax-only',driver])
            units=sorted(model.glob(TOP+'[0-9]*.cpp'));assert units
            objects=[]
            for i,unit in enumerate(units):
                obj=unit.with_suffix('.o');step('compile-'+str(i),[cxx,*flags,'-c',unit,'-o',obj]);objects.append(obj)
            binary=model/'run';step('host-link',[cxx,*flags,driver,*objects,'-ldl','-o',binary])
        step('positive',[sys.executable,'-B',HERE/'fixture.py','--executable',binary,'--output',out/'positive'],
             anchor='ADOPTION_PROBE_PASS cases=1',timeout=120)
        step('negative-no-b',[sys.executable,'-B',HERE/'fixture.py','--executable',binary,'--output',out/'negative-no-b','--negative-no-b'],
             expected=1,anchor='ADOPTION_PROBE_NEGATIVE changed_external_b=1 actual_attach=1 actual_accept_delta=1',timeout=120)
        positive=json.loads((out/'positive/result.json').read_text());negative=json.loads((out/'negative-no-b/result.json').read_text())
        assert positive['status']=='PASS' and positive['adoption_probe_events']['b_cpu_offer_overlap']>=6
        assert negative['adoption_probe_events']['attach']==1
        r['positive']=positive;r['negative']=negative
        r['artifacts']={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='receipt.json'}
        r['status']='PASS_SYNTHETIC_MANAGER_B_ATTACHMENT_EXCLUSION_ONLY'
    except BaseException as e:r['status']='FAIL';r['error']=str(e);raise
    finally:save()
    print(r['status'],out/'receipt.json',flush=True)
if __name__=='__main__':main()
