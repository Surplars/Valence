#!/usr/bin/env python3
"""Serial real exhausted fallback, plus saved affected guards on identical ON64 objects."""
import argparse, hashlib,json,os,re,shutil,subprocess,time
from pathlib import Path
import bound_store_replay_common as portable
ROOT=Path(__file__).resolve().parents[2];TOP='CoherentCacheHomeGsim'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def inputs():
    return portable.source_inputs(ROOT,[Path(__file__),*sorted((ROOT/'simulator/gsim/harness').glob('*'))])
def main():
    global ROOT
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--paired',type=Path,required=True)
    p.add_argument('--paired-receipt-sha256',required=True)
    p.add_argument('--execute','--run-grant',dest='execute',action='store_true')
    p.add_argument('--reuse-models-from',type=Path);p.add_argument('--reuse-receipt-sha256')
    portable.add_paths(p,ROOT);a=p.parse_args();ROOT=a.source_root.resolve()
    paths=portable.tool_paths(a,p);gsim=paths['gsim'];cxx=paths['cxx'];mill=paths['mill'];tools=portable.tool_binding(paths)
    prior=portable.verified_receipt(a.paired,a.paired_receipt_sha256)
    assert prior['tools']==tools,'paired tool identity differs; rebuild fresh'
    portable.check_dependencies(prior.get('dependencies',{}))
    current=inputs()
    assert {n:v for n,v in current.items()if n.endswith('.scala') or n in ('build.mill','.mill-version','.mill-jvm-opts')}=={n:v for n,v in prior['inputs'].items()if n.endswith('.scala') or n in ('build.mill','.mill-version','.mill-jvm-opts')},'paired model source closure differs; rebuild fresh'
    portable.verify_model_inputs(a.paired/'on',prior['models']['on']['artifacts'])
    if a.reuse_models_from:
        reused=portable.verified_receipt(a.reuse_models_from,a.reuse_receipt_sha256)
        portable.check_dependencies(reused.get('dependencies',{}))
        assert reused['tools']==tools and reused['inputs'].keys()==current.keys(),'reuse identity mismatch'
        changed={n for n in current if current[n]!=reused['inputs'][n]}
        assert changed<={'simulator/gsim/read_prefetch_store_hold_extras.py','simulator/gsim/harness/read_prefetch_store_hold_fallback.cpp'},'reuse model inputs changed; rebuild fresh'
        portable.verify_model_inputs(a.reuse_models_from/'on-gen2',reused['models']['on-gen2']['artifacts'])
    if portable.preflight(a,current,paths):return
    if not a.execute:p.error('execution requires --execute; --preflight-only does not build or run')
    out=a.output.resolve();assert not out.exists(),'fresh evidence required';out.mkdir(parents=True)
    r={'schema':'bound-store-portable-component-v1','status':'RUNNING','qualification_scope':'ADDITIONAL_GEN2_FALLBACK_AND_REUSED_ON64_GUARDS',
       'source_root':str(ROOT),'source_head':portable.source_revision(ROOT),
       'inputs':current,'tools':tools,'commands':[],'models':{},'dependencies':{},'compiler_jobs':1,'gsim_cpp_max_size_KB':1024,
       'executing_cpu':False,'physical_qualification':False,'qualification_inherited':False,'memory_oracle_bytes':131072,
       'paired_receipt':{'path':str((a.paired/'receipt.json').resolve()),'sha256':sha(a.paired/'receipt.json')}}
    def save():(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
    def step(name,cmd,expected=0,anchor=None):
        assert inputs()==current,'frozen inputs changed';portable.check_tools(tools)
        assert sha(a.paired/'receipt.json')==a.paired_receipt_sha256,'paired receipt drift'
        if r['dependencies']:portable.check_dependencies(r['dependencies'])
        for label,item in r.get('reused_models',{}).items():portable.verify_model_inputs(out/label,item['artifacts'])
        cmd=list(map(str,cmd));print('+ '+' '.join(cmd),flush=True);start=time.monotonic();log=out/(name+'.log')
        with log.open('x')as f:q=subprocess.run(portable.command_args(cmd,paths),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=900,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0','PYTHONDONTWRITEBYTECODE':'1'})
        text=log.read_text();r['commands'].append({'name':name,'argv':cmd,'exit':q.returncode,'expected_exit':expected,'seconds':time.monotonic()-start,'log_sha256':sha(log)});save()
        assert q.returncode==expected,f'{name} failed: {text[-5000:]}'
        assert not re.search(r'ERROR: AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|LeakSanitizer',text)
        if anchor:assert anchor in text,name
        return text
    def flags(model):return ['-std=c++20','-O1','-g','-gz=zlib','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(model),'-I'+str(ROOT/'simulator/gsim/harness'),
        '-DSPLIT_PREFETCH_TRACKING=1','-DSTORE_PF_LRU_ON=0','-DPF_CANDIDATE_CYCLES=16','-DCACHE_WAYS=2','-DREAD_PF_DIRTY_RETRY=1','-DREAD_PF_DEMAND_ADOPTION=1','-DREAD_PF_STORE_HOLD=1',
        '-DREAD_MSHRS=2','-DCACHE_LINES=512','-DRESPONSE_ENTRIES=2','-DAXI_SLOTS=4']
    def record(label,model,actual,cases):
        images=list((model/'images').glob('*-expected.bin'));assert len(images)==cases
        for e in images:assert e.stat().st_size==131072 and sha(e)==sha(e.with_name(e.name.replace('-expected.bin','-actual.bin')))
        r['models'][label]={'actual_parameters':actual,'directed_cases':cases,'artifacts':{str(q.relative_to(model)):sha(q)for q in model.rglob('*')if q.is_file()}};save()
    try:
        r['dependencies'].update(prior['dependencies'])
        if a.reuse_models_from:r['dependencies'].update(reused['dependencies'])
        save();model=out/'on64-reused';model.mkdir();old=a.paired/'on';actual=prior['models']['on']['actual_parameters']
        for name,digest in prior['models']['on']['artifacts'].items():
            q=old/name
            if q.suffix in('.fir','.h','.cpp','.o')or name=='actual-parameters.json':
                assert sha(q)==digest;(model/name).symlink_to(q.resolve())
        r['reused_models']={'on64-reused':{'source_receipt':str((a.paired/'receipt.json').resolve()),'source_head':prior['source_head'],
            'actual_parameters_sha256':sha(model/'actual-parameters.json'),'artifacts':{q.name:sha(q)for q in model.iterdir()if q.is_file()}}};save()
        objects=sorted(model.glob(TOP+'[0-9]*.o'));assert len(objects)==3
        binary=model/'run';step('on64-reused-link',[cxx,*flags(model),ROOT/'simulator/gsim/harness/read_prefetch_store_hold_reused.cpp',*objects,'-ldl','-o',binary])
        text=step('on64-reused-positive',[binary,'--images='+str(model/'images')],anchor='READ_PREFETCH_STORE_HOLD_REUSED_PASS');assert'cases=3'in text
        record('on64-reused',model,actual,3)
        model=out/'on-gen2';model.mkdir();reused=False
        if a.reuse_models_from:
            oldr=portable.verified_receipt(a.reuse_models_from,a.reuse_receipt_sha256);assert oldr['tools']==tools
            portable.verify_model_inputs(a.reuse_models_from/'on-gen2',oldr['models']['on-gen2']['artifacts'])
            assert oldr['inputs'].keys()==current.keys()
            changes={n for n in current if current[n]!=oldr['inputs'][n]}
            assert changes<={'simulator/gsim/read_prefetch_store_hold_extras.py','simulator/gsim/harness/read_prefetch_store_hold_fallback.cpp'},changes
            old=a.reuse_models_from/'on-gen2'
            assert len(list(old.glob(TOP+'[0-9]*.o')))==3
            artifacts={}
            for q in sorted(old.iterdir()):
                if q.name=='actual-parameters.json'or q.suffix in('.fir','.h','.cpp','.o'):
                    artifacts[q.name]=sha(q);(model/q.name).symlink_to(q.resolve())
            r['host_only_reuse']={'path':str(a.reuse_models_from.resolve()),'receipt_sha256':sha(a.reuse_models_from/'receipt.json'),'changed':sorted(changes)}
            r['reused_models']['on-gen2']={'source_receipt':str((a.reuse_models_from/'receipt.json').resolve()),'source_head':oldr['source_head'],'artifacts':artifacts};save();reused=True
        else:step('gen2-emit',[mill,'-i','-j','1','IonSoC.test.runMain','ooo.ReadPrefetchStoreHoldFallbackGsimMain',model])
        actual=json.loads((model/'actual-parameters.json').read_text());assert actual['postedConfig']['generationBits']==actual['postedGenerationBits']==2
        assert actual['cacheConcurrency']==prior['models']['on']['actual_parameters']['cacheConcurrency']
        assert actual['cacheConcurrency']['readPrefetchStoreHold']
        if not reused:step('gen2-generate',[gsim,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(model),model/(TOP+'.fir')])
        objects=[]
        for i,unit in enumerate(sorted(model.glob(TOP+'[0-9]*.cpp'))):
            obj=unit.with_suffix('.o')
            if not reused:
                dep=obj.with_suffix('.d');step('gen2-compile-'+str(i),[cxx,*flags(model),'-MD','-MF',dep,'-c',unit,'-o',obj])
                portable.record_dependencies(dep,ROOT,r['dependencies']);save()
            else:assert sha(obj)==r['reused_models']['on-gen2']['artifacts'][obj.name]
            objects.append(obj)
        binary=model/'run';step('gen2-link',[cxx,*flags(model),ROOT/'simulator/gsim/harness/read_prefetch_store_hold_fallback.cpp',*objects,'-ldl','-o',binary])
        step('gen2-positive',[binary,'--images='+str(model/'images')],anchor='READ_PREFETCH_STORE_HOLD_FALLBACK_PASS')
        step('gen2-negative-nonposted',[binary,'--inject-nonposted'],expected=1,anchor='real exhausted fallback offer did not cancel candidate before admission')
        record('on-gen2',model,actual,1);r['status']='PASS_COMPONENT_ONLY'
    except BaseException as e:r['status']='FAIL';r['error']=str(e);raise
    finally:save()
    print(r['status'],out/'receipt.json',flush=True)
if __name__=='__main__':main()
