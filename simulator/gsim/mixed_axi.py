#!/usr/bin/env python3
"""Bounded mixed bridge and real cache/home proofs; no CPU/physical claim."""
import argparse, hashlib, json, os, subprocess, shutil
from pathlib import Path
import run as common

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--tag',required=True); ap.add_argument('--reuse-tag'); ap.add_argument('--group',choices=['bridge','integration','all'],default='all'); args=ap.parse_args()
    out=common.BUILD/('mixed-axi-'+args.tag);out.mkdir(parents=True,exist_ok=False)
    paths=sorted((common.ROOT/'src').rglob('*.scala'))+sorted((common.HERE/'harness').glob('*mixed*'))+[common.HERE/'harness/coherent_cache_home.cpp',Path(__file__)]
    hashes=lambda:{str(p.relative_to(common.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    r={'status':'RUNNING','source_sha256':hashes(),'cases':{},'scope':'short GSIM; synthetic equal memory, no FPGA signoff'}
    try:
        gsim,cxx=common.setup(False)
        original_run=common.run
        def cached_run(command, **kwargs):
            command=list(map(str,command))
            cpp=[a for a in command if a.endswith('.cpp')]
            if command[0] != str(cxx) or not cpp or '-o' not in command:
                return original_run(command, **kwargs)
            executable=Path(command[command.index('-o')+1]); directory=executable.parent
            flags=command[1:command.index(cpp[0])]
            objects=[]
            for source in cpp:
                source=Path(source); obj=directory/(source.stem+'.o')
                compile_flags=flags if 'harness' in source.parts else [v for v in flags if not v.startswith('-D')]
                digest=hashlib.sha256(source.read_bytes()+repr([v if not v.startswith('-I') else '-I<model>' for v in compile_flags]).encode()).hexdigest()
                stamp=obj.with_suffix('.object-sha256')
                if not obj.exists() or not stamp.exists() or stamp.read_text()!=digest:
                    original_run([cxx,*compile_flags,'-c',source,'-o',obj],log=obj.with_suffix('.compile.log'))
                    stamp.write_text(digest)
                objects.append(obj)
            return original_run([cxx,'-fsanitize=address,undefined',*objects,'-ldl','-o',executable],**kwargs)
        common.run=cached_run
        cases=[]
        if args.group in ('bridge','all'):
            for slots,writes in ((4,0),(4,2),(8,4)):
                cases.append((f'bridge-s{slots}-w{writes}','ooo.TileLinkAxi4OutstandingGsimMain','TileLinkAxi4Bridge','tilelink_axi4_mixed.cpp',(slots,16,3,writes),{'REQUIRE_MIXED':1} if writes else {},'OUTSTANDING_ALL_PASS','--inject-data','independent TL data oracle mismatch'))
        if args.group in ('integration','all'):
            for m,w,mixed,slots in ((1,1,0,4),(2,1,0,4),(2,2,1,4),(4,4,1,8)):
                defines={'READ_MSHRS':m,'CACHE_LINES':64,'RESPONSE_ENTRIES':max(2,m),'MIXED_MODEL':1,'AXI_SLOTS':slots}
                if mixed: defines['MIXED_RTL']=1
                cases.append((f'cache-m{m}-w{w}-mixed{mixed}','ooo.CoherentCacheHomeGsimMain','CoherentCacheHomeGsim','coherent_cache_home.cpp',(m,64,max(2,m),1,w,mixed,slots),defines,'CACHE_HOME_PASS','--inject-mismatch','CPU independent byte oracle mismatch'))
        for name,entry,top,harness,parameters,defines,anchor,negative,error in cases:
            old=common.BUILD/('mixed-axi-'+str(args.reuse_tag))/name
            if args.reuse_tag and (old/(top+'.fir')).exists():
                prior=json.loads((old.parent/'receipt.json').read_text())
                assert all(r['source_sha256'][k]==v for k,v in prior['source_sha256'].items() if k.endswith('.scala')), 'reused RTL source drift'
                d=out/name;shutil.copytree(old,d)
                dependencies=[str((common.HERE/'harness'/harness).relative_to(common.ROOT))]
                if top=='TileLinkAxi4Bridge': dependencies += ['simulator/gsim/harness/tilelink_axi4_mixed_channels.cpp']
                dependencies += [k for k in prior['source_sha256'] if k.endswith('.h')]
                if name in prior['cases'] and all(prior['source_sha256'][k]==r['source_sha256'][k] for k in dependencies):
                    r['cases'][name]={**prior['cases'][name], 'reused_from':str(old), 'parameters':parameters}
                    (out/'progress.json').write_text(json.dumps(r,indent=2)+'\n')
                    print('REUSED_PASS',name,flush=True);continue
                common.run([cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                    *[f'-D{k}={v}' for k,v in defines.items()],'-I'+str(d),*sorted(d.glob(top+'[0-9]*.cpp')),
                    common.HERE/'harness'/harness,'-ldl','-o',d/'run'],log=d/'compile.log')
                common.run([d/'run'],log=d/'test.log',timeout=180,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
            else:
                d=common.test(gsim,cxx,str(out.relative_to(common.BUILD)/name),entry,top,harness,parameters=parameters,defines=defines,timeout=180)
            log=(d/'test.log').read_text();assert anchor in log
            if top == 'TileLinkAxi4Bridge' and parameters[-1] > 0:
                exe=d/'write-channels'
                common.run([cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                    f'-DAXI_SLOTS={parameters[0]}',f'-DWRITE_CREDITS={parameters[-1]}','-I'+str(d),
                    *sorted(d.glob(top+'[0-9]*.cpp')),common.HERE/'harness/tilelink_axi4_mixed_channels.cpp','-ldl','-o',exe],log=d/'channels-compile.log')
                common.run([exe],log=d/'channels.log',env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=120)
                assert 'QUEUED_WRITE_PASS' in (d/'channels.log').read_text()
                log += (d/'channels.log').read_text()
            bad=subprocess.run([str(d/'run'),negative],capture_output=True,text=True,timeout=180,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
            (d/'negative.log').write_text(bad.stdout+bad.stderr);assert bad.returncode!=0 and error in bad.stdout+bad.stderr
            if top == 'CoherentCacheHomeGsim':
                unsafe=subprocess.run([str(d/'run'),'--unsafe-cache-only-fence'],capture_output=True,text=True,timeout=180,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
                (d/'unsafe-fence-negative.log').write_text(unsafe.stdout+unsafe.stderr)
                assert unsafe.returncode!=0 and 'cache-only fence exposes stale instruction bytes' in unsafe.stdout+unsafe.stderr
            if top == 'TileLinkAxi4Bridge':
                for arg,msg in [('--bad-id','AXI R response has no live read owner'),
                    ('--bad-bid','AXI B response has no live write owner'),
                    ('--bad-last','AXI read ID or RLAST mismatch'),
                    ('--bad-last-late','AXI read ID or RLAST mismatch'),
                    ('--bad-boundary','TL-AXI address must be naturally aligned')]:
                    failed=subprocess.run([str(d/'run'),arg],capture_output=True,text=True,timeout=120,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
                    (d/(arg[2:]+'.log')).write_text(failed.stdout+failed.stderr)
                    assert failed.returncode != 0 and msg in failed.stdout+failed.stderr, arg
            r['cases'][name]={'status':'PASS','log':log,'negative':'PASS'}
            (out/'progress.json').write_text(json.dumps(r,indent=2)+'\n')
        assert hashes()==r['source_sha256'],'source drift';r['status']='PASS'
    except BaseException as e:r['status']='FAIL';r['error']=str(e);raise
    finally:(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
if __name__=='__main__':main()
