#!/usr/bin/env python3
"""Focused two-client M2/W2 Home protocol proof; installed GSIM only, no CPU/board claim."""
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
    p.add_argument('--whole', choices=('0', '1', 'both'), default='both')
    a = p.parse_args()
    assert all(c.isalnum() or c in '-_' for c in a.tag), 'invalid output tag'
    output = common.BUILD / ('common-home-clients-' + a.tag)
    output.mkdir(parents=True, exist_ok=False)
    guard = Guard(output)
    gsim = a.gsim_source / 'build/gsim/gsim'
    receipt = json.loads(a.qualification.read_text())
    revision = subprocess.check_output(['git','rev-parse','HEAD'], cwd=a.gsim_source, text=True).strip()
    changed = subprocess.check_output(['git','diff','HEAD','--name-only'], cwd=a.gsim_source, text=True).splitlines()
    patch = subprocess.check_output(['git','diff','HEAD','--binary'], cwd=a.gsim_source)
    validate_qualification(receipt, a.gsim_source, gsim, a.cxx, revision, changed,
        hashlib.sha256(patch).hexdigest(), common.LOCK)
    sources = sorted((common.ROOT / 'src/main/scala').rglob('*.scala')) + [
        common.ROOT/'src/test/scala/ooo/CommonHomeClientsGsim.scala',
        common.HERE/'harness/common_home_clients.cpp', Path(__file__)]
    hashes = lambda: {str(f.relative_to(common.ROOT)): hashlib.sha256(f.read_bytes()).hexdigest() for f in sources}
    report = {'status':'RUNNING', 'source_sha256':hashes(), 'gsim_sha256':receipt['binary_sha256'],
        'scope':'Full 1024-line/4-way/256-set Home, two protocol clients, external byte oracle; no CPU, board or timing claim', 'cases':{}}
    env = {**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
    try:
        for whole in ((0,1) if a.whole=='both' else (int(a.whole),)):
            name=f'whole-{whole}'; target=output/name; target.mkdir()
            guard.run(name+'-emit', ['bash',a.mill,'-i','-j2','IonSoC.test.runMain',
                'ooo.CommonHomeClientsGsimMain',target,whole], timeout=600)
            guard.run(name+'-generate', [gsim,'--threads=1',f'--dir={target}',target/'CommonHomeClientsGsim.fir'],timeout=600)
            flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',f'-I{target}']
            objects=[]
            for n,source in enumerate(sorted(target.glob('CommonHomeClientsGsim[0-9]*.cpp'))):
                obj=source.with_suffix('.o'); objects.append(obj)
                guard.run(name+f'-compile-{n}', [a.cxx,*flags,'-c',source,'-o',obj],timeout=600)
            guard.run(name+'-driver', [a.cxx,*flags,f'-DWHOLE_GRANT={whole}',common.HERE/'harness/common_home_clients.cpp',*objects,'-ldl','-o',target/'run'],timeout=600)
            positive=guard.run(name+'-positive',[target/'run'],env=env)
            assert 'COMMON_HOME_CLIENTS_PASS' in positive
            negatives={}
            for flag,anchor in [('--inject-data','independent Grant data mismatch'),
                    ('--bad-client-e','GrantAck has no live sink or matching client')]:
                result=subprocess.run([target/'run',flag],capture_output=True,text=True,env=env,timeout=120)
                (target/(flag[2:]+'.log')).write_text(result.stdout+result.stderr)
                assert result.returncode and anchor in result.stdout+result.stderr, 'negative control failed: '+flag
                negatives[flag]=result.returncode
            report['cases'][name]={'positive':positive,'negative_exits':negatives}
            print(positive,end='',flush=True)
        assert hashes()==report['source_sha256'], 'source changed during proof'
        report['status']='PASS_HOME_PROTOCOL_ONLY'
    except Exception as exc:
        report.update(status='FAIL',error=str(exc)); raise
    finally:
        report['commands']=guard.records
        (output/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__': main()
