#!/usr/bin/env python3
"""One fresh paired generic-PMP component; no CPU, new stage or PPA claim."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import run as common

ROOT=common.ROOT
TOP='PmpGenericRangesGsim'
HOST=common.HERE/'harness/pmp_generic_ranges.cpp'
SOURCE=ROOT/'src/main/scala/core/ooo/mmu/PmpGenericRangeComparisons.scala'
MANIFEST=common.HERE/'config/pmp-generic-range-mutants.json'

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(v,s):
    if not v: raise ValueError(s)
def mutants():
    source=SOURCE.read_text(); records=json.loads(MANIFEST.read_text())
    require(len(records)==5,'mutant set changed')
    for m in records:
        require(source.count(m['old'])==m['count'],'mutation anchor drift: '+m['name'])
        expected=source.replace('class PmpGenericRangeComparisons(',f"class PmpGenericRangeMutant{m['index']}(").replace(m['old'],m['new'])
        p=ROOT/m['path']
        require(p.read_text()==expected and sha(p)==m['sha256'],'mutant is not exact source difference: '+m['name'])
    return records

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag',required=True);ap.add_argument('--gsim',type=Path)
    ap.add_argument('--compile-receipt',type=Path);ap.add_argument('--build-run',action='store_true')
    args=ap.parse_args();ms=mutants()
    require(re.fullmatch(r'[A-Za-z0-9_-]+',args.tag),'unsafe tag')
    if not args.build_run:
        print('PASS_GENERIC_RANGE_SOURCE_PREFLIGHT');return
    require(args.gsim and args.compile_receipt,'locked GSIM and bound public compile receipt required')
    spec=importlib.util.spec_from_file_location('compile_gate',ROOT/'fpga/common/scala_compile_receipt.py');gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
    gate.verify_receipt(args.compile_receipt,ROOT)
    out=common.BUILD/args.tag;out.mkdir(parents=True,exist_ok=False)
    gsim=args.gsim.resolve(strict=True);cxx,compiler=common.compiler();compiler_path=Path(shutil.which(str(cxx)) or cxx).resolve()
    files=sorted((ROOT/'src/main/scala').rglob('*.scala'))+sorted((ROOT/'src/test/scala').rglob('*.scala'))+[HOST,Path(__file__),MANIFEST,common.HERE/'run.py',common.HERE/'factored_pmp_structure.py',common.HERE/'test_factored_pmp_structure.py',common.HERE/'registered_raw_certified_cones.py']
    before={str(p.relative_to(ROOT)):sha(p) for p in files}
    r={'schema':'valence-generic-pmp-equivalence-v1','status':'RUNNING','sources':before,'gsim_sha256':sha(gsim),'compiler':compiler,'compiler_sha256':sha(compiler_path),'compile_receipt_sha256':sha(args.compile_receipt),'negative_controls':[],'scope':'One exact old/candidate generic PMP matrix 0/8/16 with raw65 and real decode paths; no CPU or PPA'}
    def save(): (out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
    save()
    try:
        common.run(['mill','-i','IonSoC.test.runMain','ooo.PmpGenericRangesGsimMain',out],log=out/'elaborate.log')
        fir=out/(TOP+'.fir');r['fir_sha256']=sha(fir)
        import factored_pmp_structure
        structure=factored_pmp_structure.review(fir);require(len(structure['instances'])==3,'expected exactly three production range instances');(out/'structure.json').write_text(json.dumps(structure,indent=2)+'\n');r['structure_sha256']=sha(out/'structure.json');save()
        common.run([gsim,'--threads=1',f'--dir={out}',fir],log=out/'generate.log')
        flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(out)]
        common.run([cxx,*flags,'-fsyntax-only',HOST],log=out/'header-syntax.log')
        sources=sorted(out.glob(TOP+'[0-9]*.cpp'));require(sources,'missing generated model');objects=[]
        for p in [*sources,HOST]:
            obj=out/(p.stem+'.o');common.run([cxx,*flags,'-c',p,'-o',obj],log=out/(p.stem+'-compile.log'));objects.append(obj)
        binary=out/'run';common.run([cxx,*flags,*objects,'-ldl','-o',binary],log=out/'link.log')
        env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
        common.run([binary],env=env,timeout=120,log=out/'test.log')
        log=(out/'test.log').read_text();require(log.count('PMP_GENERIC_RANGES_PASS ')==1,'missing final oracle result')
        r['metrics_line']=next(x for x in log.splitlines() if x.startswith('PMP_GENERIC_RANGES_PASS '))
        for name in [m['name'] for m in ms]+['inject-oracle']:
            flag='--'+name;run=subprocess.run([str(binary),flag],env=env,text=True,capture_output=True,timeout=30);text=run.stdout+run.stderr
            path=out/(name+'.log');path.write_text(text)
            expected='GENERIC_PMP_DECISION_ORACLE' if name=='inject-oracle' else 'MUTANT_RANGE_ORACLE'
            marker='REACHED_ORACLE_NEGATIVE' if name=='inject-oracle' else 'REACHED_MUTANT '+flag
            require(run.returncode==1 and expected in text and marker in text and 'NEGATIVE_CONTROL_ESCAPED' not in text,'negative control failed: '+name)
            require('ERROR: AddressSanitizer' not in text and 'runtime error:' not in text,'sanitizer failure')
            r['negative_controls'].append({'name':name,'source_mutant':name!='inject-oracle','exit':run.returncode,'sha256':sha(path)})
        require(before=={str(p.relative_to(ROOT)):sha(p) for p in files},'source drift')
        require(sha(gsim)==r['gsim_sha256'] and sha(compiler_path)==r['compiler_sha256'],'tool drift')
        gate.verify_receipt(args.compile_receipt,ROOT)
        r.update(status='PASS_GENERIC_PMP_EQUIVALENCE',binary_sha256=sha(binary),header_sha256=sha(out/(TOP+'.h')),test_log_sha256=sha(out/'test.log'),objects={p.name:sha(p) for p in objects},generated={p.name:sha(p) for p in sources})
        save();print(r['status'])
    except Exception as e:
        r.update(status='FAIL',error=str(e));save();raise
if __name__=='__main__': main()
