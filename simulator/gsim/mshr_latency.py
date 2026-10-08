#!/usr/bin/env python3
"""Bounded idle-latency refinement proof: real compact cache/home1/2/4 and home2/4."""
import argparse,hashlib,json,os,re,subprocess,time,resource
from pathlib import Path
import run as common
from mshr_occupancy import validate

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--tag',required=True);ap.add_argument('--build-run',action='store_true');a=ap.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9_-]+',a.tag)
    if not a.build_run:print('Prepared6smallmodels (one narrow ordered-bridge repair regression): compact real1/2/4,home2/4; no CPU or board model');return
    out=common.BUILD/('mshr-latency-'+a.tag);out.mkdir(parents=True,exist_ok=False)
    paths=list((common.ROOT/'src').rglob('*.scala'))+[Path(__file__),common.HERE/'mshr_occupancy.py']+[common.HERE/'harness'/p for p in ['coherent_cache_home.cpp','home_mshr.cpp','board_ddr_multiid.h','mshr_occupancy.h','tilelink_bridge.cpp']]
    hashes=lambda:{str(p.relative_to(common.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report={'status':'RUNNING','sources':hashes(),'cases':{}};start=time.monotonic()
    try:
        gsim,cxx=common.setup(False)
        ordered=common.test(gsim,cxx,str(out.relative_to(common.BUILD)/'ordered'),'ooo.OrderedTileLinkBridgeGsimMain','OrderedTileLinkBridge','tilelink_bridge.cpp',parameters=('mixed','flow'),defines={'ORDERED_WRITES':1,'ALLOW_WRITE_ERRORS':1,'MIXED_ACCESSES':1,'FLOW_HEAD_RESPONSE':1},timeout=120)
        negative=subprocess.run([ordered/'run','--inject-mismatch'],capture_output=True,text=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=120)
        (ordered/'negative.log').write_text(negative.stdout+negative.stderr)
        assert negative.returncode and 'mismatch' in negative.stdout+negative.stderr
        report['cases']['ordered']={'log':(ordered/'test.log').read_text(),'negative':'PASS','empty_payload_poison':255}
        for n in (1,2,4):
            r=max(2,n);target=out/f'real{n}';target.mkdir()
            common.run(['mill','-i','IonSoC.test.runMain','ooo.CoherentCacheHomeGsimMain',target,n,512,r,1],log=target/'elaborate.log')
            common.run([gsim,'--threads=1','--dir='+str(target),target/'CoherentCacheHomeGsim.fir'],log=target/'generate.log')
            bad=validate(common.ROOT,target/'CoherentCacheHomeGsim.h',n,'cache$')
            try:validate(common.ROOT,bad,n,'cache$')
            except AssertionError:pass
            else:raise RuntimeError('changed header schema was accepted')
            fir=(target/'CoherentCacheHomeGsim.fir').read_text()
            assert 'reg tags : UInt<18>[512]' in fir
            if n==1: assert 'reg ownedTags : UInt<26>[512]' in fir
            else: assert all(f'cmem tagBanks_{way} : UInt<18>[256]' in fir for way in (0,1))
            common.run([cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',f'-DREAD_MSHRS={n}','-DCACHE_LINES=512',f'-DRESPONSE_ENTRIES={r}','-I'+str(target),*sorted(target.glob('CoherentCacheHomeGsim[0-9]*.cpp')),common.HERE/'harness/coherent_cache_home.cpp','-ldl','-o',target/'run'],log=target/'compile.log')
            common.run([target/'run'],env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},log=target/'test.log',timeout=180)
            text=(target/'test.log').read_text();print(text,flush=True)
            lat=[{k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)} for line in text.splitlines() if line.startswith('IDLE_MISS_LATENCY ')]
            assert len(lat)==3
            if n==1:reference=lat
            else:assert lat==reference,f'M{n} idle latency differs: {lat} vs {reference}'
            p=subprocess.run([target/'run','--inject-mismatch'],capture_output=True,text=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=180)
            (target/'negative.log').write_text(p.stdout+p.stderr);assert p.returncode and 'CPU independent byte oracle mismatch' in p.stdout+p.stderr
            report['cases'][f'real{n}']={'log':text,'latency':lat,'schema_mutation':'PASS','oracle_negative':'PASS'}
            (out/'progress.json').write_text(json.dumps(report,indent=2)+'\n')
        for n in (2,4):
            target=common.test(gsim,cxx,str(out.relative_to(common.BUILD)/f'home{n}'),'ooo.HomeMshrGsimMain','HomeMshrGsim','home_mshr.cpp',parameters=(n,1),defines={'HOME_ENTRIES':n},timeout=120)
            for flag,anchor in [('--inject-data','independent Grant data mismatch'),('--bad-sink','GrantAck has no live sink'),('--inject-dispatch','dispatch independent payload mismatch')]:
                p=subprocess.run([target/'run',flag],capture_output=True,text=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=120)
                (target/(flag[2:]+'.log')).write_text(p.stdout+p.stderr);assert p.returncode and anchor in p.stdout+p.stderr
            report['cases'][f'home{n}']={'log':(target/'test.log').read_text(),'negatives':'PASS'}
        assert hashes()==report['sources'],'source drift';report['status']='PASS'
    except BaseException as e:report['status']='FAIL';report['error']=str(e);raise
    finally:
        report['seconds']=time.monotonic()-start;report['max_rss_kib']=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        report['artifacts']={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file() and p.name!='receipt.json'}
        (out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
