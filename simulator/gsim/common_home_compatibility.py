#!/usr/bin/env python3
"""Focused single-client compatibility of the generalized Home, including the exact optimized shadow."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import run as common
from bringup import Guard, validate_qualification


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tag', required=True)
    p.add_argument('--gsim-source', required=True, type=Path)
    p.add_argument('--qualification', required=True, type=Path)
    p.add_argument('--mill', required=True, type=Path)
    p.add_argument('--cxx', required=True, type=Path)
    a = p.parse_args()
    assert all(c.isalnum() or c in '-_' for c in a.tag), 'invalid output tag'
    output = common.BUILD / ('common-home-compatibility-' + a.tag)
    output.mkdir(parents=True, exist_ok=False)
    guard = Guard(output)
    gsim = a.gsim_source / 'build/gsim/gsim'
    qualification = json.loads(a.qualification.read_text())
    revision = subprocess.check_output(['git','rev-parse','HEAD'], cwd=a.gsim_source, text=True).strip()
    changed = subprocess.check_output(['git','diff','HEAD','--name-only'], cwd=a.gsim_source, text=True).splitlines()
    patch = subprocess.check_output(['git','diff','HEAD','--binary'], cwd=a.gsim_source)
    validate_qualification(qualification, a.gsim_source, gsim, a.cxx, revision, changed,
        hashlib.sha256(patch).hexdigest(), common.LOCK)
    paths = sorted((common.ROOT/'src/main/scala').rglob('*.scala')) + [
        common.ROOT/'src/test/scala/ooo/HomeTagRamGsim.scala', common.HERE/'harness/home_mshr.cpp',
        common.HERE/'harness/home_tag_ram.cpp', common.ROOT/'src/test/scala/ooo/HomeSharedLookupGsim.scala',
        common.ROOT/'src/test/scala/ooo/FrozenR6MixedCoherentLineHome.scala',
        common.HERE/'home_shared_lookup.py',common.HERE/'harness/home_shared_lookup.cpp',Path(__file__)]
    hashes=lambda: {str(f.relative_to(common.ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in paths}
    report={'status':'RUNNING','source_sha256':hashes(),'gsim_sha256':qualification['binary_sha256'],
        'scope':'Single-client 512-line M2/W2 Home protocol and existing optimized Home paired-shadow protocol; no CPU/board/timing claim','cases':{}}
    env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
    try:
        target=output/'default';target.mkdir()
        guard.run('default-emit',['bash',a.mill,'-i','-j2','IonSoC.test.runMain','ooo.hometagram.HomeTagRamGsimMain',target,2,1,512,1],timeout=600)
        guard.run('default-generate',[gsim,'--threads=1',f'--dir={target}',target/'HomeMshrGsim.fir'],timeout=600)
        flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',f'-I{target}']
        objects=[]
        for n,source in enumerate(sorted(target.glob('HomeMshrGsim[0-9]*.cpp'))):
            obj=source.with_suffix('.o');objects.append(obj)
            guard.run(f'default-compile-{n}',[a.cxx,*flags,'-c',source,'-o',obj],timeout=600)
        guard.run('default-driver',[a.cxx,*flags,'-DHOME_ENTRIES=2','-DHOME_LINES=512','-DHOME_MIXED=1','-DHOME_BASE=0xffff0000ULL',
            common.HERE/'harness/home_tag_ram.cpp',*objects,'-ldl','-o',target/'run'],timeout=600)
        log=guard.run('default-positive',[target/'run'],env=env)
        assert 'HOME_TAG_RAM_PASS mixed=1 lines=512 entries=2' in log
        report['cases']['default']={'log':log}
        print(log,end='',flush=True)
        target=output/'exact';target.mkdir()
        guard.run('exact-emit',['bash',a.mill,'-i','-j2','IonSoC.test.runMain','ooo.HomeSharedLookupGsimMain',target,0,4,1,1,1,4,2],timeout=600)
        guard.run('exact-generate',[gsim,'--threads=1',f'--dir={target}',target/'HomeSharedLookupGsim.fir'],timeout=600)
        log=guard.run('exact-shadow',['python',common.HERE/'home_shared_lookup.py','--model',target,
            '--output',target/'proof','--cxx',a.cxx],timeout=600,env=env)
        assert 'HOME_SHARED_LOOKUP_PASS' in log
        shadow=json.loads((target/'proof/receipt.json').read_text())
        report['cases']['exact']={'log':log,'paired_members':len(shadow['paired_retained_members']),
            'protocol_log':(target/'proof/protocol.log').read_text()}
        print(log,end='',flush=True)
        assert hashes()==report['source_sha256'],'source changed during compatibility proof'
        report['status']='PASS_SINGLE_CLIENT_HOME_ONLY'
    except Exception as exc:
        report.update(status='FAIL',error=str(exc));raise
    finally:
        report['commands']=guard.records
        (output/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
