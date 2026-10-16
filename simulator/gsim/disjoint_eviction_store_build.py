#!/usr/bin/env python3
"""Explicitly granted serial OFF/ON emit, GSIM build and focused component acceptance."""
import argparse, hashlib, importlib.util, json, os, shutil, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--gsim',type=Path,required=True);p.add_argument('--run-grant',action='store_true')
    a=p.parse_args();assert a.run_grant,'parent-granted serial compiler window required'
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    top='DisjointEvictionStoreGsim'; cxx=Path(os.environ['GSIM_CXX']);mill=shutil.which('mill');assert mill
    files=list((ROOT/'src/main/scala').rglob('*.scala'))+[ROOT/'src/test/scala/ooo/DisjointEvictionStoreGsim.scala',
            ROOT/'src/test/scala/ooo/ThreeProofRowNativeProfile.scala']
    def hashes():return {str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    original=hashes();receipt=dict(status='RUNNING',source_hashes=original,commands=[])
    def run(label,command):
        assert hashes()==original,'source changed during frozen batch'
        command=list(map(str,command));print(label,flush=True)
        with (out/(label+'.log')).open('w') as f:
            r=subprocess.run(command,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,
                             env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=600)
        receipt['commands'].append(dict(label=label,argv=command,exit=r.returncode))
        (out/'build-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
        assert r.returncode==0,label
    spec=importlib.util.spec_from_file_location('ports',ROOT/'simulator/gsim/posted_cache_rebuild/ports.py')
    ports=importlib.util.module_from_spec(spec);spec.loader.exec_module(ports)
    try:
        for mode,flag in [('off',0),('on',1)]:
            d=out/mode;d.mkdir()
            run(mode+'-emit',[mill,'-i','-j','1','IonSoC.test.runMain','ooo.'+top+'Main',d,1,1,0,1,1,flag])
            run(mode+'-generate',[a.gsim.resolve(),'--threads=1','--cpp-max-size-KB=1024','--dir='+str(d),d/(top+'.fir')])
            ports.emit_driver(d/'driver.cpp')
            (d/'driver.cpp').write_text((d/'driver.cpp').read_text().replace('PostedStoreCacheGsim',top))
            flags=['-std=c++20','-O1','-g0','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(d)]
            objects=[]
            for cpp in sorted(d.glob(top+'[0-9]*.cpp')):
                obj=cpp.with_suffix('.o');run(mode+'-'+cpp.stem,[cxx,*flags,'-c',cpp,'-o',obj]);objects.append(obj)
            assert objects
            run(mode+'-link',[cxx,*flags,d/'driver.cpp',*objects,'-ldl','-o',d/'run'])
            run(mode+'-cases',[sys.executable,ROOT/'simulator/gsim/disjoint_eviction_store.py','--overlap',flag,
                              '--executable',d/'run','--output',d/'qualified'])
        run('compare',[sys.executable,ROOT/'simulator/gsim/disjoint_eviction_store_compare.py','--models',out,
                       '--cases','qualified','--output',out/'paired'])
        receipt['status']='PASS_PRIVATE_CACHE_COMPONENT_ONLY'
    finally:(out/'build-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
if __name__=='__main__':main()
