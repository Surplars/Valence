#!/usr/bin/env python3
"""Accepted-store history break: fixed cache capacities and unchanged retention deadline."""
import argparse, hashlib, json, os, shutil, subprocess
from pathlib import Path
import run as common

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--tag',required=True)
    ap.add_argument('--reuse-model-manifest',type=Path);a=ap.parse_args()
    out=common.BUILD/a.tag;out.mkdir(parents=True,exist_ok=False)
    harnesses=('prefetch_store_history.cpp','prefetch_candidate_lifetime.cpp','data_prefetch.cpp','coherent_cache_home.cpp',
        'cache_concurrency_stress.cpp','mshr_occupancy.h','board_ddr_mixed.h','board_ddr_benchmark.h','board_ddr_multiid.h')
    paths=sorted((common.ROOT/'src').rglob('*.scala'))+[Path(__file__),common.HERE/'run.py',common.HERE/'config/toolchain.json',
        common.ROOT/'build.mill']+[common.HERE/'harness'/h for h in harnesses]
    def inputs():return {str(p.relative_to(common.ROOT)):sha(p) for p in paths}
    r={'schema':'valence-prefetch-store-history-v1','status':'RUNNING','source_head':subprocess.check_output(
        ['git','rev-parse','HEAD'],cwd=common.ROOT,text=True).strip(),'source_sha256':inputs(),'models':{},
        'fixed':{'lines':512,'ways':2,'mshrs':2,'replies':2,'writebacks':2,'axi_slots':4,'candidate_attempts':3},
        'scope':'Accepted ordinary stores clear prediction history only. No credit/owner/permission or ready changes.'}
    env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
    def save():(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
    def negative(exe,flag,anchor,log):
        result=subprocess.run([exe,flag],capture_output=True,text=True,timeout=180,env=env)
        log.write_text(result.stdout+result.stderr)
        assert result.returncode!=0 and anchor in result.stdout+result.stderr,(flag,result.stdout+result.stderr)
    save()
    try:
        gsim,cxx=common.setup(False)
        reused={}
        if a.reuse_model_manifest:
            old_manifest=json.loads(a.reuse_model_manifest.read_text())
            for path,digest in old_manifest['source_sha256'].items():
                if path not in {'simulator/gsim/prefetch_store_history.py','simulator/gsim/harness/prefetch_store_history.cpp'}:
                    assert sha(common.ROOT/path)==digest,'changed reused model source '+path
            for name,item in old_manifest['failed_model_bindings'].items():
                for path,digest in item['artifacts'].items():assert sha(Path(item['directory'])/path)==digest
            configuration=a.reuse_model_manifest.parent/'configuration.log'
            assert sha(configuration)==old_manifest['configuration_sha256'] and 'All tests passed.' in configuration.read_text()
            shutil.copy2(configuration,out/'configuration.log');reused=old_manifest['failed_model_bindings']
            r['model_reuse']={'manifest':str(a.reuse_model_manifest.resolve()),'sha256':sha(a.reuse_model_manifest),
                'original_source_head':old_manifest['source_head'],'original_source_sha256':old_manifest['source_sha256']}
        else:
            common.run(['mill','-i','IonSoC.test.testOnly','ooo.DataPrefetchConfigSpec'],log=out/'configuration.log')
        for enabled,base,offset in ((False,0x80010000,0),(True,0x80010000,0),(True,0xffff0000,65536)):
            name=('break' if enabled else 'reference')+('-cross4g' if offset else '')
            d=out/name;d.mkdir();parameters=[2,512,2,1,2,1,4,1,1,'--banked-cache-tags','--prefetch-candidate-cycles=3',f'--ram-base={base}']
            if enabled:parameters+=['--prefetch-break-on-store']
            flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(d)]
            objects=[]
            if name in reused:
                item=reused[name];assert item['parameters']==parameters
                for path,digest in item['artifacts'].items():
                    shutil.copy2(Path(item['directory'])/path,d/path);assert sha(d/path)==digest
                objects=sorted(d.glob('CoherentCacheHomeGsim[0-9]*.o'));assert objects
            else:
                common.run(['mill','-i','IonSoC.test.runMain','ooo.CoherentCacheHomeGsimMain',d,*parameters],log=d/'elaborate.log')
                common.run([gsim,'--threads=1','--dir='+str(d),d/'CoherentCacheHomeGsim.fir'],log=d/'generate.log')
                for cpp in sorted(d.glob('CoherentCacheHomeGsim[0-9]*.cpp')):
                    obj=cpp.with_suffix('.o');objects.append(obj);common.run([cxx,*flags,'-c',cpp,'-o',obj],log=cpp.with_suffix('.compile.log'))
            defines={'READ_MSHRS':2,'CACHE_LINES':512,'RESPONSE_ENTRIES':2,'AXI_SLOTS':4,'MIXED_MODEL':1,'MIXED_RTL':1,
                'PREFETCH_ENABLED':1,'PREFETCH_CANDIDATE_CYCLES':3,'PREFETCH_BREAK_ON_STORE':int(enabled),
                'CACHE_BASE':str(base)+'ULL','HISTORY_ORIGIN_OFFSET':offset}
            if offset:defines['RETENTION_ORIGIN_OFFSET']=offset
            entry={'parameters':parameters,'model_directory':str(d.relative_to(common.ROOT)),'programs':{},
                'artifacts_sha256':{p.name:sha(p) for p in d.iterdir() if p.is_file()}}
            r['models'][name]=entry;save()
            history_negatives=[('--inject-mismatch','CPU independent byte oracle mismatch'),
                ('--clear-on-offer','independent accepted-request history validity mismatch')]
            if enabled:history_negatives+=[('--ignore-store-break','independent accepted-request history validity mismatch')]
            programs=[('prefetch_store_history.cpp',{'PREFETCH_BENCHMARK_MODEL':1},[('directed',[])],history_negatives),
                ('prefetch_candidate_lifetime.cpp',{'PREFETCH_BENCHMARK_MODEL':1},[('directed',[])],
                    [('--freeze-deadline','retained candidate exceeded its original deadline')])]
            if not offset:programs += [
                ('data_prefetch.cpp',{'PREFETCH_BENCHMARK_MODEL':1},[('directed',[])],
                    [('--bypass-permission','independent host protection range violation')]),
                ('cache_concurrency_stress.cpp',{},[(str(seed),['--seed',str(seed),'--iterations','1024']) for seed in (1,7)],
                    [('--inject-mismatch','CPU independent byte oracle mismatch')])]
            for harness,extra,runs,negatives in programs:
                exe=d/harness.removesuffix('.cpp')
                common.run([cxx,*flags,*[f'-D{k}={v}' for k,v in {**defines,**extra}.items()],*objects,
                    common.HERE/'harness'/harness,'-ldl','-o',exe],log=exe.with_suffix('.compile.log'))
                binary=sha(exe);logs={}
                for suffix,args in runs:
                    log=d/(exe.name+'-'+suffix+'.log');common.run([exe,*args],log=log,timeout=180,env=env);logs[suffix]=log.read_text()
                for flag,anchor in negatives:negative(exe,flag,anchor,d/(exe.name+'-'+flag[2:]+'.log'))
                assert sha(exe)==binary
                entry['programs'][harness]={'binary_sha256':binary,'logs':logs,'negatives':'PASS'};save()
            entry['artifacts_sha256']={p.name:sha(p) for p in d.iterdir() if p.is_file()}
            entry['status']='PASS';save();assert inputs()==r['source_sha256'],'source drift'
            print(name+' PASS',flush=True)
        for harness in ('prefetch_candidate_lifetime.cpp','data_prefetch.cpp'):
            assert r['models']['reference']['programs'][harness]['logs']==r['models']['break']['programs'][harness]['logs'],harness
        # Reuse unchanged authorization and actual-CPU busy-gating proofs. New
        # cache history is checked above; this remains a compositional context gate.
        old_path=common.BUILD/'prefetch-candidate-lifetime-r1/receipt.json';old=json.loads(old_path.read_text());assert old['status']=='PASS'
        allowed={'src/main/scala/core/ooo/CoherentCacheConcurrency.scala','src/main/scala/core/ooo/NonBlockingCoherentLineCache.scala',
            'src/test/scala/ooo/CoherentCacheHomeGsim.scala','src/test/scala/ooo/DataPrefetchConfigSpec.scala'}
        for path,digest in old['source_sha256'].items():
            if path not in allowed:assert sha(common.ROOT/path)==digest,'changed reusable proof input '+path
        r['context_proof']={'receipt':str(old_path),'receipt_sha256':sha(old_path),'changed_cache_sources':sorted(allowed),'replays':{}}
        for name,flag,anchor in [('authorization','--inject-permission','independent whole-line permission oracle mismatch'),
                ('context-barrier','--bypass-busy','external prefetch owner missing from memoryBusy')]:
            item=old['models'][name];directory=common.ROOT/item['model_directory']
            for path,digest in item['artifacts_sha256'].items():assert sha(directory/path)==digest
            common.run([directory/'run'],log=out/(name+'.log'),timeout=180,env=env)
            negative(directory/'run',flag,anchor,out/(name+'-negative.log'))
            r['context_proof']['replays'][name]={'original':item,'positive_sha256':sha(out/(name+'.log')),
                'negative_sha256':sha(out/(name+'-negative.log'))}
        r['artifacts_sha256']={p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='receipt.json'}
        assert inputs()==r['source_sha256'];r['status']='PASS'
    except BaseException as error:r['status']='FAIL';r['error']=str(error);raise
    finally:save()
    print(out/'receipt.json',flush=True)

if __name__=='__main__':main()
