#!/usr/bin/env python3
"""Scoped exact RAW PMP publication gates. Each heavy stage requires an explicit grant."""
import argparse, hashlib, json, os, subprocess, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT.parent / 'gates-r1'
TOOLS = ROOT.parent.parent / 'toolchain'
MILL = TOOLS / 'bin/mill'
GSIM = TOOLS / 'gsim-src/build/gsim/gsim'
CXX = TOOLS / 'sysroot/usr/bin/clang++-19'
CASES = [('8-live',8,False,'both',3), ('8-registered',8,True,'posted',2),
         ('16-live',16,False,'precheck',1), ('16-registered',16,True,'both',3)]
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def inputs():
    paths = sorted((ROOT/'src').rglob('*.scala')) + sorted((ROOT/'simulator/gsim/harness').glob('pmp_*'))
    paths += [Path(__file__), ROOT/'build.mill', ROOT/'.mill-version']
    return {str(p.relative_to(ROOT)):sha(p) for p in paths}
def run(label, argv, expected=0, anchor=None):
    assert inputs() == receipt['inputs'], 'source drift'
    path = OUT / (label + '.log'); assert not path.exists(), 'preserve prior log'
    start=time.monotonic()
    with path.open('x') as log:
        proc=subprocess.Popen(list(map(str,argv)), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                              env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        _,status,usage=os.wait4(proc.pid,0); proc.returncode=os.waitstatus_to_exitcode(status)
    content=path.read_text(); row={'label':label,'argv':list(map(str,argv)),'exit':proc.returncode,
        'seconds':time.monotonic()-start,'max_rss_KiB':usage.ru_maxrss,'log_sha256':sha(path)}
    receipt['commands'].append(row); save()
    assert proc.returncode==expected and (anchor is None or anchor in content),(row,content[-4000:])
    print(label,content[-300:].strip(),flush=True)
def save(): (OUT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
ap=argparse.ArgumentParser(); ap.add_argument('stage',choices=['freeze','compile','models','native'])
a=ap.parse_args()
if a.stage=='freeze':
    OUT.mkdir(exist_ok=False)
    receipt={'status':'SOURCE_FROZEN','inputs':inputs(),'commands':[],'cases':CASES,
        'native':False,'physical_qualification':False,'cpu_acceptance':'PENDING',
        'tools':{str(p):sha(p) for p in [MILL,GSIM,CXX]}}
    save(); print('FROZEN',sha(OUT/'receipt.json')); raise SystemExit
receipt=json.loads((OUT/'receipt.json').read_text())
grant=json.loads((ROOT.parent/'run-grant.json').read_text())
assert a.stage in grant['allowed_stages'] and grant['runner_sha256']==sha(__file__),'missing/mismatched grant'
if a.stage=='compile':
    run('scala-focused',[MILL,'-i','-j','1','IonSoC.test.testOnly','ooo.PublishedPmpChangesSpec','ooo.RegisteredPmpRegionsSpec'])
elif a.stage=='models':
    for name,n,registered,mode,flags in CASES:
        model=OUT/name; model.mkdir()
        run(name+'-emit',[MILL,'-i','-j','1','IonSoC.test.runMain','ooo.PmpCsrPublicationGsimMain',model,
            f'entries={n}',f'boundary={mode}',*(['registered'] if registered else [])])
        top='PmpCsrPublicationGsim'
        run(name+'-generate',[GSIM,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(model),model/(top+'.fir')])
        run(name+'-compile',[CXX,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
            f'-DPMP_ENTRIES={n}',f'-DPMP_BOUNDARY={flags}','-I'+str(model),*sorted(model.glob(top+'[0-9]*.cpp')),
            ROOT/'simulator/gsim/harness/pmp_csr_publication.cpp','-ldl','-o',model/'run'])
        run(name+'-run',[model/'run'],anchor='PMP boundary PASS')
        for mutant in range(1,6):
            run(name+f'-mutant-{mutant}',[model/'run',f'--mutant={mutant}'],expected=1,anchor='PMP boundary differential mismatch')
    model=OUT/'waveform';model.mkdir();top='PmpChangeWaveformGsim'
    run('waveform-emit',[MILL,'-i','-j','1','IonSoC.test.runMain','ooo.PmpChangeWaveformGsimMain',model])
    run('waveform-generate',[GSIM,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(model),model/(top+'.fir')])
    run('waveform-compile',[CXX,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
        '-I'+str(model),*sorted(model.glob(top+'[0-9]*.cpp')),ROOT/'simulator/gsim/harness/pmp_change_waveform.cpp',
        '-ldl','-o',model/'run'])
    run('waveform-run',[model/'run'],anchor='PMP waveform PASS')
    for mutant in range(1,6):
        run(f'waveform-mutant-{mutant}',[model/'run',str(mutant)],expected=1,anchor='PMP waveform differential mismatch')
    receipt['status']='FOCUSED_GATES_PASS';save()
else:
    raise SystemExit('native stage not prepared')
