#!/usr/bin/env python3
"""Fixed aligned-four-byte PMP proof: preflight by default, two bounded component models on request."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def verify_sources():
    production=(common.ROOT/'src/main/scala/core/ooo/PhysicalMemoryProtection.scala').read_text()
    prefix='package soc.core.ooo\nimport chisel3._\nimport chisel3.util._\n\n'
    body=prefix+production[production.index('/** Parallel range'):]
    mutations=json.loads((common.HERE/'config/pmp-word-source-mutants.json').read_text())
    for m in mutations:
        assert body.count(m['old'])==1, m['name']+' production anchor drift'
        expected=body.replace('class PmpChecker(',f"class PmpWordSourceMutant{m['mode']}(").replace(m['old'],m['new'])
        source=common.ROOT/f"src/test/scala/ooo/PmpWordSourceMutant{m['mode']}.scala"
        assert source.read_text()==expected and sha(source)==m['source_sha256'],m['name']+' is not the declared source mutant'
    reference=common.ROOT/'src/test/scala/ooo/R6PmpCheckerReference.scala'
    assert sha(reference)=='b49960ca6555c2e005fcc24c3f3566f44f78b4841c5cdc5ed2af96284dffa03b','frozen byte reference changed'
    return mutations

def verify_negative(flag,code,text,reason):
    assert code!=0 and reason in text and 'NEGATIVE_CONTROL_ESCAPED' not in text,(flag,code,text[-2000:])
    if flag.startswith(('--mutant-','--contract-')):assert 'REACHED '+flag in text,(flag,'missing reached')
    assert not any(x in text for x in ('ERROR: AddressSanitizer','runtime error:','UndefinedBehaviorSanitizer'))

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--tag',required=True);ap.add_argument('--build-run',action='store_true');a=ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.tag):ap.error('unsafe tag')
    mutations=verify_sources()
    if not a.build_run:
        print(json.dumps({'status':'PREFLIGHT_SOURCE_DERIVATION_PASS','models':2,'source_mutants':len(mutations),'contract_negative_attribution':'shared-source multi-instance assertions, not isolated candidate','full_cpu':False,'physical_metrics':'UNMEASURED'}));return
    out=common.BUILD/a.tag;out.mkdir(parents=True,exist_ok=False)
    files=sorted((common.ROOT/'src/main/scala').rglob('*.scala'))+sorted((common.ROOT/'src/test/scala').rglob('*.scala'))+[Path(__file__),common.HERE/'run.py',common.HERE/'config/pmp-word-source-mutants.json',*[common.HERE/'harness'/f for f in ('pmp_word_granule.cpp','pmp_csr_publication.cpp','pmp_csr_oracle.h')]]
    before={str(p.relative_to(common.ROOT)):sha(p) for p in files};receipt={'status':'RUNNING','source_sha256':before,'controls':[],'contract_negative_attribution':'shared-source multi-instance assertions, not isolated candidate','physical_metrics':'UNMEASURED'}
    def negative(label,cmd,reason):
        r=subprocess.run(list(map(str,cmd)),cwd=common.ROOT,capture_output=True,text=True,timeout=180,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        text=r.stdout+r.stderr;(out/(label+'.log')).write_text(text);verify_negative(label if label.startswith('--') else '',r.returncode,text,reason)
        receipt['controls'].append({'label':label,'argv':list(map(str,cmd)),'exit':r.returncode,'log_sha256':sha(out/(label+'.log'))})
    try:
        gsim,cxx=common.setup(False)
        word=common.test(gsim,cxx,a.tag+'/word','ooo.PmpWordGranuleGsimMain','PmpWordGranuleGsim','pmp_word_granule.cpp',defines={},timeout=120)
        assert 'PMP_WORD_GRANULE_PASS' in (word/'test.log').read_text()
        for name in ('high-address','priority','lock','write-permission','inactive','high-region'):
            flag='--mutant-'+name;negative(flag,[word/'run',flag],'ORACLE_BYTE_RANGE_FIRST_PERMISSION')
        for name in ('granule','size','alignment'):
            flag='--contract-'+name;reason='word PMP requires complete decoded four-byte region granules' if name=='granule' else 'aligned word PMP checker requires a four-byte aligned four-byte access'
            negative(flag,[word/'run',flag],reason)
        csr=common.test(gsim,cxx,a.tag+'/csr','ooo.PmpCsrPublicationGsimMain','PmpCsrPublicationGsim','pmp_csr_publication.cpp',parameters=('registered','entries=16'),defines={'PMP_ENTRIES':16},timeout=120)
        assert 'PMP CSR publication PASS entries=16' in (csr/'test.log').read_text()
        negative('csr-observer',[csr/'run','--inject-mismatch'],'PMP publication oracle mismatch')
        negative('constructor-domain',['mill','-i','IonSoC.test.runMain','ooo.PmpWordGranuleConfigMain','bad'],'decoded word PMP requires the fixed aligned four-byte access domain')
        assert {str(p.relative_to(common.ROOT)):sha(p) for p in files}==before,'source changed during run'
        receipt['status']='PASS_COMPONENTS_ONLY';receipt['artifacts']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file()}
    except BaseException as e:receipt['status']='FAIL';receipt['error']=str(e);raise
    finally:(out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
if __name__=='__main__':main()
