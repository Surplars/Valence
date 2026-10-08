#!/usr/bin/env python3
"""Bounded data prefetch: independent permission oracle, captured VM context, real coherent cache/home pair."""
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
import run as common

def build(gsim,cxx,name,main,top,harness,parameters=(),defines=None,timeout=120):
    target=common.BUILD/name;target.mkdir(parents=True,exist_ok=False)
    common.run(['mill','-i','IonSoC.test.runMain',main,target,*parameters],log=target/'elaborate.log')
    common.run([gsim,'--threads=1','--dir='+str(target),target/(top+'.fir')],log=target/'generate.log')
    flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(target)]
    objects=[]
    for source in sorted(target.glob(top+'[0-9]*.cpp')):
        obj=source.with_suffix('.o');common.run([cxx,*flags,'-c',source,'-o',obj],log=obj.with_suffix('.compile.log'));objects.append(obj)
    host=target/'harness.o'
    common.run([cxx,*flags,*[f'-D{k}={v}' for k,v in (defines or {}).items()],'-c',common.HERE/'harness'/harness,'-o',host],log=target/'harness-compile.log')
    common.run([cxx,*flags,*objects,host,'-ldl','-o',target/'run'],log=target/'link.log')
    common.run([target/'run'],log=target/'test.log',env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=timeout)
    print((target/'test.log').read_text(),end='',flush=True)
    return target

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--tag',required=True);args=ap.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9_-]+',args.tag)
    out=common.BUILD/('data-prefetch-'+args.tag);out.mkdir(parents=True,exist_ok=False)
    paths=sorted((common.ROOT/'src').rglob('*.scala'))+[Path(__file__)]+[common.HERE/'harness'/f for f in ('next_line_authorization.cpp','prefetch_barrier.cpp','context_window.cpp','identity_data_flow.cpp','data_prefetch.cpp','coherent_cache_home.cpp','board_ddr_mixed.h','board_ddr_benchmark.h')]
    def hashes():return {str(p.relative_to(common.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    r={'status':'RUNNING','source_sha256':hashes(),'models':{},'scope':'small authorization/adapter/cache-home; no CPU/FPGA performance claim'}
    (out/'freeze.json').write_text(json.dumps(r,indent=2)+'\n')
    def save(): (out/'progress.json').write_text(json.dumps(r,indent=2)+'\n')
    def negative(target,arg,anchor):
        x=subprocess.run([target/'run',arg],capture_output=True,text=True,timeout=120,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        (target/(arg[2:]+'.log')).write_text(x.stdout+x.stderr)
        assert x.returncode!=0 and anchor in x.stdout+x.stderr,(arg,x.stdout,x.stderr)
    try:
        gsim,cxx=common.setup(False)
        a=build(gsim,cxx,str(out.relative_to(common.BUILD)/'permission'),'ooo.NextLineAuthorizationGsimMain','NextLineAuthorizationGsim','next_line_authorization.cpp',timeout=120)
        assert 'NEXT_LINE_AUTH_PASS' in (a/'test.log').read_text()
        negative(a,'--inject-permission','independent whole-line permission oracle mismatch')
        r['models']['permission']={'status':'PASS','negative':'PASS'};save()
        for identity in (0,1):
            name=f'context-{identity}'
            a=build(gsim,cxx,str(out.relative_to(common.BUILD)/name),'ooo.TranslationContextGsimMain','TranslationContextGsim','identity_data_flow.cpp',parameters=(identity,'pmp','prefetch'),defines={'IDENTITY_FLOW':identity,'PREFETCH_AUTH':1},timeout=120)
            assert 'IDENTITY_DATA_FLOW_PASS' in (a/'test.log').read_text()
            negative(a,'--inject-permission','independent captured prefetch permission mismatch')
            r['models'][name]={'status':'PASS','negative':'PASS'};save()
        for enabled in (0,1):
            name=f'system-barrier-{enabled}'
            a=build(gsim,cxx,str(out.relative_to(common.BUILD)/name),'ooo.PrefetchBarrierGsimMain','PrefetchBarrierGsim','prefetch_barrier.cpp',parameters=(enabled,),defines={'PREFETCH_BARRIER_ENABLED':enabled},timeout=120)
            assert f'PREFETCH_BARRIER_PASS cases={9+enabled}' in (a/'test.log').read_text()
            if enabled:negative(a,'--bypass-busy','external prefetch owner missing from memoryBusy')
            # Reuse the real core model for an architectural MPRV consequence:
            # subsequent LD must trap at its own PC, with no physical request.
            flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(a)]
            common.run([cxx,*flags,f'-DPREFETCH_BARRIER_ENABLED={enabled}',common.HERE/'harness/context_window.cpp',*sorted(a.glob('PrefetchBarrierGsim[0-9]*.o')),'-ldl','-o',a/'context-run'],log=a/'context-compile.log')
            common.run([a/'context-run'],log=a/'context-test.log',env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=120)
            assert 'CONTEXT_WINDOW_PASS' in (a/'context-test.log').read_text()
            x=subprocess.run([a/'context-run','--inject-mismatch'],capture_output=True,text=True,timeout=120,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
            (a/'context-negative.log').write_text(x.stdout+x.stderr)
            assert x.returncode!=0 and 'CONTEXT_WINDOW_FAIL' in x.stdout+x.stderr
            r['models'][name]={'status':'PASS','cases':9+enabled,'mprv_precise_load_fault':'PASS','oracle_negative':'PASS','busy_negative':'PASS' if enabled else 'not_applicable'};save()
        for enabled in (0,1):
            name=f'cache-{enabled}'
            a=build(gsim,cxx,str(out.relative_to(common.BUILD)/name),'ooo.CoherentCacheHomeGsimMain','CoherentCacheHomeGsim','data_prefetch.cpp',parameters=(2,512,2,1,2,1,4,1,enabled),defines={'READ_MSHRS':2,'CACHE_LINES':512,'RESPONSE_ENTRIES':2,'AXI_SLOTS':4,'MIXED_MODEL':1,'PREFETCH_BENCHMARK_MODEL':1,'PREFETCH_ENABLED':enabled},timeout=120)
            log=(a/'test.log').read_text();assert f'DATA_PREFETCH_PASS enabled={enabled}' in log
            negative(a,'--inject-mismatch','CPU independent byte oracle mismatch')
            if enabled:negative(a,'--bypass-permission','independent host protection range violation')
            cases={}
            for line in log.splitlines():
                if line.startswith('PREFETCH_CASE '):
                    fields=dict(x.split('=',1) for x in line.split()[1:]);case=fields.pop('name');cases[case]={k:int(v) for k,v in fields.items()}
            r['models'][name]={'status':'PASS','negative':'PASS','cases':cases};save()
        assert r['models']['cache-1']['cases']['adjacent64k']['cycles']<r['models']['cache-0']['cases']['adjacent64k']['cycles'],'stream did not improve'
        assert hashes()==r['source_sha256'],'source drift'
        r['status']='PASS'
    except BaseException as e:r['status']='FAIL';r['error']=str(e);raise
    finally:(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
if __name__=='__main__':main()
