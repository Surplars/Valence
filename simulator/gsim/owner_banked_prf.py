#!/usr/bin/env python3
"""Focused real-RAM proof plan; no build/download without explicit --build-run."""
import argparse, hashlib, json, os, subprocess, shutil
from prf_sampled_reset import lower
from pathlib import Path
import run as common

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build-run',action='store_true')
    ap.add_argument('--tag',default='owner-banked-prf')
    ap.add_argument('--firtool',type=Path,default=Path(os.environ.get('FIRTOOL','firtool')),
        help='Chisel7.3.0-compatible firtool1.135.0 for exact reset-lowering RTL comparison')
    a=ap.parse_args()
    if not a.tag.replace('-','').replace('_','').isalnum(): ap.error('invalid tag')
    files=sorted((common.ROOT/'src/main/scala').rglob('*.scala'))+[
        common.ROOT/'src/test/scala/ooo/OwnerBankedPrfGsim.scala',
        common.HERE/'harness/owner_banked_prf.cpp',common.HERE/'prf_sampled_reset.py',Path(__file__)]
    hashes=lambda:{str(p.relative_to(common.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    before=hashes()
    if not a.build_run:
        print(json.dumps(dict(status='PREPARED_NOT_RUN',depths=[48,64,128],source_files=len(before),
            scope='real asynchronous RAM + independent word oracle; core authorization remains separate')))
        return
    out=common.BUILD/a.tag;out.mkdir(parents=True,exist_ok=False)
    receipt=dict(status='running',source_sha256=before,cases={},physical_mapping='unverified')
    try:
        gsim,cxx=common.setup(False)
        model=out/'matrix';model.mkdir()
        common.run(['mill','-i','IonSoC.test.runMain','ooo.OwnerBankedPrfGsimMain',model],log=model/'elaborate.log')
        original=model/'original.fir'
        shutil.copy2(model/'OwnerBankedPrfGsim.fir',original)
        (model/'OwnerBankedPrfGsim.fir').write_text(lower(original.read_text()))
        for kind,source in [('original',original),('sampled',model/'OwnerBankedPrfGsim.fir')]:
            common.run([a.firtool,source,'--verilog','--strip-debug-info','--disable-all-randomization',
                '--default-layer-specialization=disable','-o',model/(kind+'.sv')],log=model/(kind+'-firtool.log'))
        if (model/'original.sv').read_bytes()!=(model/'sampled.sv').read_bytes():
            raise RuntimeError('test-only synchronous reset lowering changed synthesizable RTL')
        digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
        receipt['reset_lowering']={'registers':9,'sync_only':True,'full_sv_byte_equal':True,
            'original_fir_sha256':digest(original),'sampled_fir_sha256':digest(model/'OwnerBankedPrfGsim.fir'),
            'equivalent_sv_sha256':digest(model/'original.sv')}
        common.run([gsim,'--threads=1','--dir='+str(model),model/'OwnerBankedPrfGsim.fir'],log=model/'generate.log')
        flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(model)]
        objects=[]
        for cpp in sorted(model.glob('OwnerBankedPrfGsim[0-9]*.cpp')):
            obj=cpp.with_suffix('.o');objects.append(obj)
            common.run([cxx,*flags,'-c',cpp,'-o',obj],log=obj.with_suffix('.compile.log'))
        receipt['model_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [model/'OwnerBankedPrfGsim.fir',model/'OwnerBankedPrfGsim.h',*objects]}
        for depth in (48,64,128):
            case=out/f'depth-{depth}';case.mkdir()
            common.run([cxx,*flags,'-DPHYSICAL_REGS='+str(depth),common.HERE/'harness/owner_banked_prf.cpp',
                *objects,'-o',case/'run'],log=case/'link.log')
            common.run([case/'run'],log=case/'test.log',env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
            negatives=['--inject-mismatch','--wrong-priority']+(['--invalid-write'] if depth==48 else [])
            for flag in negatives:
                result=subprocess.run([case/'run',flag],capture_output=True,text=True,timeout=30,
                    env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
                text=result.stdout+result.stderr
                (case/(flag[2:]+'.log')).write_text(text)
                expected='PRF write address outside physical capacity' if flag=='--invalid-write' else 'PRF independent data oracle mismatch'
                if result.returncode==0 or expected not in text: raise RuntimeError('negative did not reject expected fault: '+flag)
            receipt['cases'][str(depth)]=(case/'test.log').read_text()
            (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
        if hashes()!=before: raise RuntimeError('source changed during proof')
        receipt['status']='PASS_PRF_RAM_ONLY'
    except Exception as error:
        receipt['status']='failed';receipt['error']=str(error);raise
    finally:
        (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')

if __name__=='__main__':main()
