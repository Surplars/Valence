#!/usr/bin/env python3
"""Paired frontend payload-CE proof: ownership/invalidation stay exact, dead payload may capture."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import run as common
from data_cache_geometry import module


def capture_structure(fir, enabled):
    body=module(fir,'SynchronousFetch')
    nodes={}
    for line in body.splitlines():
        match=re.match(r'\s*node (\w+) = (.*?)(?: @\[.*)?$',line)
        if match:nodes[match.group(1)]=match.group(2)
    def depends(expression, needle, seen=None):
        seen=set() if seen is None else seen
        for token in re.findall(r'[A-Za-z_][A-Za-z0-9_.]*',expression):
            if token==needle:return True
            if token in nodes and token not in seen:
                seen.add(token)
                if depends(nodes[token],needle,seen):return True
        return False
    guards=[];payload=[];install=[]
    for line in body.splitlines():
        indent=len(line)-len(line.lstrip());text=line.strip().split(' @[')[0]
        while guards and indent<=guards[-1][0]:guards.pop()
        when=re.match(r'when (.*?) :$',text)
        if when:guards.append((indent,when.group(1)));continue
        connect=re.match(r'connect ([^,]+), (.*)$',text)
        if not connect:continue
        target,value=connect.groups();condition=' '.join(g for _,g in guards)+' '+target
        if re.match(r'(words|bases|contexts|errors|pageFaults|shiftedBases_\d+)\[',target):
            row={'target':target,'invalidate_in_enable':depends(condition,'io.invalidate'),
                 'stale_in_enable':depends(condition,'pendingStale')}
            assert row['invalidate_in_enable']==(not enabled) and row['stale_in_enable'],row
            payload.append(row)
        if target.startswith('valid[') and value=='UInt<1>(0h1)':
            assert depends(condition,'io.invalidate') and depends(condition,'pendingStale'),target
            install.append(target)
    assert payload and install,'payload/install write census missing'
    return {'payload_writes':payload,'valid_installs':install,
            'scope':'CHIRRTL combinational write-enable/address dependency; no routed timing result'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag',required=True)
    ap.add_argument('--seeds',default='1,7,31,127')
    ap.add_argument('--build-run',action='store_true')
    a=ap.parse_args();seeds=[int(x) for x in a.seeds.split(',')]
    if not a.build_run:
        print(json.dumps({'status':'PREFLIGHT_ONLY','widths':[2,4],'models':4,'seeds':seeds,
                          'cycle_contract':'unchanged','physical_timing':'UNMEASURED'},indent=2));return
    out=common.BUILD/a.tag;out.mkdir(parents=True,exist_ok=False)
    inputs=sorted((common.ROOT/'src').rglob('*.scala'))+[Path(__file__),common.HERE/'run.py',
        common.HERE/'data_cache_geometry.py',common.HERE/'config/toolchain.json',common.ROOT/'build.mill',
        common.HERE/'harness/fetch_offsets.cpp',
        common.HERE/'harness/fetch_payload_capture.cpp']
    def hashes():return {str(p.relative_to(common.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    report={'status':'RUNNING','source_sha256':hashes(),'cases':{},'scope':'independent frontend module oracle; no CPU/physical result'}
    try:
        gsim,cxx=common.setup(False)
        for width in (2,4):
            pair={}
            for enabled in (False,True):
                name=f'w{width}-'+('capture' if enabled else 'baseline');d=out/name;d.mkdir()
                params=(width,'stable-fault-metadata','aligned-fetch-pmp','raw-fetch-presence','parallel-fetch-tags','parallel-alignment',
                        *(('--independent-payload-capture',) if enabled else ()))
                common.run(['mill','-i','IonSoC.test.runMain','ooo.FetchOffsetsGsimMain',d,*params],log=d/'elaborate.log')
                common.run([gsim,'--threads=1','--dir='+str(d),d/'FetchOffsetsGsim.fir'],log=d/'generate.log')
                flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(d),
                       f'-DFETCH_WIDTH={width}','-DSTABLE_FAULT_METADATA=1']
                objects=[]
                for cpp in sorted(d.glob('FetchOffsetsGsim[0-9]*.cpp')):
                    obj=cpp.with_suffix('.o');objects.append(obj)
                    common.run([cxx,*flags,'-c',cpp,'-o',obj],log=cpp.with_suffix('.compile.log'))
                structure=capture_structure((d/'FetchOffsetsGsim.fir').read_text(),enabled)
                (d/'capture-structure.json').write_text(json.dumps(structure,indent=2)+'\n')
                results={}
                for harness in ('fetch_offsets','fetch_payload_capture'):
                    exe=d/harness
                    common.run([cxx,*flags,*objects,common.HERE/'harness'/(harness+'.cpp'),'-ldl','-o',exe],log=d/(harness+'-compile.log'))
                    modes=[[]] if harness=='fetch_offsets' else [['--seed',str(seed)] for seed in seeds]
                    for number,mode in enumerate(modes):
                        log=d/(harness+'-'+str(number)+'.log')
                        common.run([exe,*mode],log=log,timeout=120,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
                        results[harness+'-'+str(number)]=log.read_text()
                    negatives=[('--inject-mismatch','mixed-length instruction mismatch')] if harness=='fetch_offsets' else [
                        ('--inject-word','frontend independent generation/context instruction mismatch'),
                        ('--bypass-stale','frontend stale owner became visible'),
                        ('--bypass-invalidate','frontend ')]
                    for flag,anchor in negatives:
                        r=subprocess.run([exe,flag],text=True,capture_output=True,timeout=120,
                                         env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
                        (d/(harness+'-'+flag[2:]+'.log')).write_text(r.stdout+r.stderr)
                        assert r.returncode!=0 and anchor in r.stdout+r.stderr,(name,flag,r.stdout+r.stderr)
                pair[str(enabled)]={'results':results,'structure':structure,'model_directory':str(d.relative_to(common.ROOT)),
                    'artifacts_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in d.iterdir()
                        if p.is_file() and (p.suffix in ('.fir','.cpp','.h','.o','.log','.json') or p.name in ('fetch_offsets','fetch_payload_capture'))}};report['cases'][str(width)]=pair
                (out/'progress.json').write_text(json.dumps(report,indent=2)+'\n')
            assert pair['False']['results']==pair['True']['results'],'paired frontend cycle/witness counts changed'
        assert hashes()==report['source_sha256'],'source drift'
        report['status']='PASS'
    except BaseException as error:report['status']='FAIL';report['error']=str(error);raise
    finally:(out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
