#!/usr/bin/env python3
"""One/three/sixteen-attempt prefetch hints: fixed capacities, independent RTL memory/context gates."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path
import run as common

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--tag',required=True);a=ap.parse_args()
    out=common.BUILD/a.tag;out.mkdir(parents=True,exist_ok=False)
    harnesses=('prefetch_candidate_lifetime.cpp','data_prefetch.cpp','coherent_cache_home.cpp','cache_concurrency_stress.cpp',
        'mshr_occupancy.h','board_ddr_mixed.h','board_ddr_benchmark.h','board_ddr_multiid.h','prefetch_barrier.cpp',
        'context_window.cpp','next_line_authorization.cpp')
    paths=sorted((common.ROOT/'src').rglob('*.scala'))+[Path(__file__),common.HERE/'run.py',common.HERE/'config/toolchain.json',
        common.ROOT/'build.mill']+[common.HERE/'harness'/x for x in harnesses]
    def hashes():return {str(p.relative_to(common.ROOT)):sha(p) for p in paths}
    r={'status':'RUNNING','source_sha256':hashes(),'models':{},'fixed':{'mshrs':2,'replies':2,'writebacks':2,'lines':512,
        'ways':2,'axi_slots':4,'line_bytes':64,'coherent_burst_beats':8},'scope':
        'Independent cache/home/AXI plus existing physical-authorization and CPU context/busy proof. No CPU workload/PPA claim.'}
    env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
    def save():(out/'progress.json').write_text(json.dumps(r,indent=2)+'\n')
    try:
        gsim,cxx=common.setup(False)
        common.run(['mill','-i','IonSoC.test.testOnly','ooo.DataPrefetchConfigSpec'],log=out/'configuration.log')
        for cycles,base,origin in ((1,0x80010000,None),(3,0x80010000,None),(16,0x80010000,None),(16,0xffff0000,65536)):
            name=f'cycles{cycles}'+('-cross4g' if base==0xffff0000 else '')
            d=out/name;d.mkdir()
            parameters=(2,512,2,1,2,1,4,1,1,'--banked-cache-tags',f'--prefetch-candidate-cycles={cycles}',f'--ram-base={base}')
            common.run(['mill','-i','IonSoC.test.runMain','ooo.CoherentCacheHomeGsimMain',d,*parameters],log=d/'elaborate.log')
            common.run([gsim,'--threads=1','--dir='+str(d),d/'CoherentCacheHomeGsim.fir'],log=d/'generate.log')
            flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(d)]
            objects=[]
            for cpp in sorted(d.glob('CoherentCacheHomeGsim[0-9]*.cpp')):
                obj=cpp.with_suffix('.o');objects.append(obj)
                common.run([cxx,*flags,'-c',cpp,'-o',obj],log=cpp.with_suffix('.compile.log'))
            defines={'READ_MSHRS':2,'CACHE_LINES':512,'RESPONSE_ENTRIES':2,'AXI_SLOTS':4,'MIXED_MODEL':1,'MIXED_RTL':1,
                'PREFETCH_ENABLED':1,'PREFETCH_CANDIDATE_CYCLES':cycles,'CACHE_BASE':str(base)+'ULL'}
            if origin is not None:defines['RETENTION_ORIGIN_OFFSET']=origin
            entry={'parameters':parameters,'model_directory':str(d.relative_to(common.ROOT)),'programs':{}}
            programs=[('prefetch_candidate_lifetime.cpp',{'PREFETCH_BENCHMARK_MODEL':1},[('directed',[])],
                [('--inject-mismatch','CPU independent byte oracle mismatch'),
                 ('--freeze-deadline','retained candidate exceeded its original deadline')])]
            if origin is None:
                programs += [('data_prefetch.cpp',{'PREFETCH_BENCHMARK_MODEL':1},[('directed',[])],
                    [('--inject-mismatch','CPU independent byte oracle mismatch'),
                     ('--bypass-permission','independent host protection range violation')]),
                    ('cache_concurrency_stress.cpp',{},[(str(seed),['--seed',str(seed),'--iterations','1024']) for seed in (1,7)],
                     [('--inject-mismatch','CPU independent byte oracle mismatch')])]
            for harness,extra,runs,negatives in programs:
                exe=d/harness.removesuffix('.cpp')
                common.run([cxx,*flags,*[f'-D{k}={v}' for k,v in {**defines,**extra}.items()],*objects,
                    common.HERE/'harness'/harness,'-ldl','-o',exe],log=exe.with_suffix('.compile.log'))
                initial=sha(exe);logs={}
                for suffix,args in runs:
                    log=d/(exe.name+'-'+suffix+'.log');common.run([exe,*args],log=log,timeout=180,env=env);logs[suffix]=log.read_text()
                for flag,anchor in negatives:
                    result=subprocess.run([exe,flag],capture_output=True,text=True,timeout=180,env=env)
                    (d/(exe.name+'-'+flag[2:]+'.log')).write_text(result.stdout+result.stderr)
                    assert result.returncode!=0 and anchor in result.stdout+result.stderr,(name,harness,flag,result.stdout+result.stderr)
                assert sha(exe)==initial
                entry['programs'][harness]={'binary_sha256':initial,'logs':logs,'negatives':'PASS'}
            entry['artifacts_sha256']={p.name:sha(p) for p in d.iterdir() if p.is_file()}
            r['models'][name]=entry;save();assert hashes()==r['source_sha256'],'source drift'
        for name,main,top,harness,parameters,negative in [
            ('authorization','ooo.NextLineAuthorizationGsimMain','NextLineAuthorizationGsim','next_line_authorization.cpp',(),
             ('--inject-permission','independent whole-line permission oracle mismatch')),
            ('context-barrier','ooo.PrefetchBarrierGsimMain','PrefetchBarrierGsim','prefetch_barrier.cpp',(1,),
             ('--bypass-busy','external prefetch owner missing from memoryBusy'))]:
            d=common.test(gsim,cxx,f'{a.tag}/{name}',main,top,harness,parameters=parameters,
                defines={'PREFETCH_BARRIER_ENABLED':1},timeout=180)
            initial=sha(d/'run');result=subprocess.run([d/'run',negative[0]],capture_output=True,text=True,timeout=180,env=env)
            (d/'negative.log').write_text(result.stdout+result.stderr)
            assert result.returncode!=0 and negative[1] in result.stdout+result.stderr
            assert sha(d/'run')==initial
            r['models'][name]={'model_directory':str(d.relative_to(common.ROOT)),'log':(d/'test.log').read_text(),
                'negative':'PASS','artifacts_sha256':{p.name:sha(p) for p in d.iterdir() if p.is_file()}}
            save();assert hashes()==r['source_sha256'],'source drift'
        r['status']='PASS'
    except BaseException as error:r['status']='FAIL';r['error']=str(error);raise
    finally:(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')

if __name__=='__main__':main()
