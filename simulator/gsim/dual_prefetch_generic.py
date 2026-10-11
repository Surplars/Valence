#!/usr/bin/env python3
"""Exactly two generic split-token boundaries; no policy grid or broad suite."""
import argparse,hashlib,json,os,pathlib,re,subprocess,time
ROOT=pathlib.Path(__file__).resolve().parents[2]
TOP='CoherentCacheHomeGsim'
def sha(path):return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
def inputs():
    names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    return {n:sha(ROOT/n) for n in names if n and (ROOT/n).is_file()}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=pathlib.Path)
    p.add_argument('--run-grant',action='store_true');a=p.parse_args()
    assert a.run_grant,'serial run grant required'
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT),'freeze source first'
    out=a.output.resolve();assert not out.exists();out.mkdir()
    tool=pathlib.Path(os.environ['VALENCE_CLOUD_ENV']);gsim=tool/'gsim-src/build/gsim/gsim';cxx=tool/'sysroot/usr/bin/clang++-19'
    r={'schema':'dual-prefetch-generic-boundaries-v1','status':'RUNNING','inputs':inputs(),
       'source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
       'tools':{str(p):sha(p) for p in (gsim,cxx.resolve())},'commands':[],'models':{},
       'scope':'One-way opposite-token veto/demand progress; configured LRU protected-way skip with real dirty ReleaseAck',
       'executing_cpu':False,'physical_qualification':False}
    def save():(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
    def step(name,cmd,code=0,anchor=None):
        assert inputs()==r['inputs'],'source drift'
        assert all(sha(p)==h for p,h in r['tools'].items()),'tool drift'
        cmd=list(map(str,cmd));log=out/(name+'.log');start=time.monotonic();print('+ '+' '.join(cmd),flush=True)
        with log.open('x') as stream:
            v=subprocess.run(cmd,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=600,
                env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0','PYTHONDONTWRITEBYTECODE':'1'})
        text=log.read_text();r['commands'].append({'name':name,'argv':cmd,'exit':v.returncode,
            'expected_exit':code,'seconds':time.monotonic()-start,'log_sha256':sha(log)});save()
        assert v.returncode==code,f'{name}: {text[-4000:]}'
        assert not re.search(r'ERROR: AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|LeakSanitizer',text),name
        if anchor:assert anchor in text,(name,anchor)
        return text
    try:
        save()
        for label,ways,lru,mutation,diagnostic in [('one-way',1,0,'token-address','resident token full PA/index differs'),
            ('lru-protected',2,1,'victim','candidate selected protected or wrong full-PA victim')]:
            model=out/label;model.mkdir()
            step(label+'-emit',['mill','-i','-j','1','IonSoC.test.runMain','ooo.DualPrefetchTrackingGsimMain',model,1,lru,16,ways])
            actual=json.loads((model/'actual-parameters.json').read_text());cache=actual['cacheConcurrency']
            assert cache['splitPrefetchTracking'] and cache['independentDemandAdmission'] and cache['storePrefetchMruInsertion']
            assert cache['storePrefetchLruVictim']==bool(lru) and cache['prefetchCandidateCycles']==16
            assert actual['cacheWays']==ways and actual['cacheLines']==512
            assert actual['cacheMshrs']==actual['cacheWritebacks']==actual['cacheResponses']==2
            step(label+'-generate',[gsim,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(model),model/(TOP+'.fir')])
            flags=['-std=c++20','-O1','-g','-gz=zlib','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                '-I'+str(model),'-I'+str(ROOT/'simulator/gsim/harness'),'-DSPLIT_PREFETCH_TRACKING=1',
                '-DPF_CANDIDATE_CYCLES=16','-DCACHE_WAYS='+str(ways),'-DSTORE_PF_LRU_ON='+str(lru),
                '-DREAD_MSHRS=2','-DCACHE_LINES=512','-DRESPONSE_ENTRIES=2','-DAXI_SLOTS=4']
            units=sorted(model.glob(TOP+'[0-9]*.cpp'));assert units;objects=[]
            for i,unit in enumerate(units):
                obj=unit.with_suffix('.o');step(label+'-compile-'+str(i),[cxx,*flags,'-c',unit,'-o',obj]);objects.append(obj)
            binary=model/'run';step(label+'-link',[cxx,*flags,ROOT/'simulator/gsim/harness/dual_prefetch_generic.cpp',*objects,'-ldl','-o',binary])
            text=step(label+'-positive',[binary,'--case='+label,'--images='+str(model/'images')],anchor='DUAL_PREFETCH_GENERIC_PASS')
            assert len([row for row in text.splitlines() if row.startswith('DUAL_PREFETCH_TRACKING_CASE ')])==1
            expected=list((model/'images').glob('*-expected.bin'));assert len(expected)==1
            assert expected[0].read_bytes()==expected[0].with_name(expected[0].name.replace('-expected.bin','-actual.bin')).read_bytes()
            text=step(label+'-negative',[binary,'--case='+label,'--inject-'+mutation],code=1,anchor=diagnostic)
            assert 'DUAL_PREFETCH_TRACKING_MUTATION_TRIGGER '+mutation in text
            r['models'][label]={'actual_parameters':actual,'artifacts':{str(path.relative_to(model)):sha(path) for path in model.rglob('*') if path.is_file()}};save()
        assert inputs()==r['inputs'];r['status']='PASS_TWO_GENERIC_BOUNDARIES_ONLY'
    except BaseException as e:r['status']='FAIL';r['error']=str(e);raise
    finally:save()
    print(r['status'],out/'receipt.json',flush=True)
if __name__=='__main__':main()
