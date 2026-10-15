#!/usr/bin/env python3
"""Focused real-module capacity/bank tests; existing fixed GSIM only."""
import argparse,hashlib,json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--gsim',type=Path,required=True)
    ap.add_argument('--reuse-from',type=Path)
    a=ap.parse_args();os.nice(10);out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    inputs={str(p.relative_to(ROOT)):sha(p) for p in ROOT.glob('src/**/*.scala')}
    for p in [Path(__file__),ROOT/'simulator/gsim/harness/proof_control_bank.cpp',ROOT/'simulator/gsim/harness/proof_control_capacity.cpp']:
        inputs[str(p.relative_to(ROOT))]=sha(p)
    receipt=dict(status='RUNNING',inputs=inputs,gsim_sha256=sha(a.gsim),commands=[])
    env={**os.environ,'JAVA_TOOL_OPTIONS':'-XX:ActiveProcessorCount=2','ASAN_OPTIONS':'detect_leaks=0','UBSAN_OPTIONS':'halt_on_error=1'}
    def save():(out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    def run(label,cmd,negative=None):
        assert all(sha(ROOT/p)==h for p,h in inputs.items()),'source drift'
        start=time.monotonic();log=out/(label+'.log')
        with log.open('x') as f:p=subprocess.run(list(map(str,cmd)),cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=1200)
        text=log.read_text(errors='replace');receipt['commands'].append(dict(label=label,exit=p.returncode,seconds=round(time.monotonic()-start,3),sha256=sha(log)));save()
        if negative:
            if p.returncode==0 or negative not in text:raise RuntimeError('negative failed '+label+'\n'+text[-5000:])
        elif p.returncode:raise RuntimeError(label+'\n'+text[-6000:])
        print(label,'PASS',flush=True);return text
    save()
    try:
        for mode,top in [('capacity','ProofControlCapacityGsim'),('bank','ProofControlBankGsim')]:
            d=out/mode
            reused=False
            if a.reuse_from and (a.reuse_from/mode).exists():
                import shutil
                previous=json.loads((a.reuse_from/'receipt.json').read_text())
                assert previous['gsim_sha256']==receipt['gsim_sha256']
                assert all(previous['inputs'].get(n)==h for n,h in inputs.items() if n.endswith('.scala'))
                d.mkdir()
                for p in (a.reuse_from/mode).iterdir():
                    if p.suffix in ('.fir','.h','.cpp','.o'):shutil.copy2(p,d/p.name)
                reused=True
            else:
                run(mode+'-emit',['mill','-i','-j','2','IonSoC.test.runMain','ooo.ProofControlComponentsMain',d,mode])
                run(mode+'-generate',[a.gsim,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(d),d/(top+'.fir')])
            receipt[mode+'_reused_model']=str(a.reuse_from/mode) if reused else None
            flags=['-std=c++20','-O1','-g0','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(d)]
            objs=[]
            for i,p in enumerate(sorted(d.glob(top+'[0-9]*.cpp'))):
                obj=p.with_suffix('.o')
                if not reused:run(mode+'-compile-'+str(i),['clang++-19',*flags,'-c',p,'-o',obj])
                assert obj.exists();objs.append(obj)
            assert objs
            binary=d/'run';run(mode+'-link',['clang++-19',*flags,ROOT/('simulator/gsim/harness/proof_control_'+mode+'.cpp'),*objs,'-ldl','-o',binary])
            receipt[mode+'_positive']=run(mode+'-positive',[binary])
            if mode=='bank':
                run('bank-load-oracle-negative',[binary,'--mutate-load'],'fresh different live owner result lost')
                run('bank-bind-evict-negative',[binary,'--bind-evict'],'actual relied-row binding excludes')
                run('bank-bound-epoch-negative',[binary,'--bound-epoch'],'surviving bound store cannot cross')
        receipt['status']='PASS_C1_CAPACITY_AND_BANK_COMPONENTS';save();print(receipt['status'],flush=True)
    except BaseException as e:
        receipt.update(status='FAILED_PRESERVE_EVIDENCE',failure=str(e));save();raise
if __name__=='__main__':main()
