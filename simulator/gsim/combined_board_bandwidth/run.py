#!/usr/bin/env python3
"""One source-bound combined3554932 model, explicit staged build and bounded runs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import concurrent.futures
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = ROOT / 'build/combined-board-bandwidth-3554932'
MODEL = OUT / 'model'
GUEST = OUT / 'guest/copy'
BASE = '3554932ea0b1136ba9b41257385df0c1e8c5ff5c'
GSIM_SHA = 'f00067c6158db342927ad0d746109ad745298fd4ebe9707fd951998069587116'
NATIVE_SHA = '2392c8cd63f6b0d3746da5e00cdd6b86461e889c46bdeeb50d145cb7ad763cee'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def tracked():
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    return {n: sha(ROOT/n) for n in names if n and (ROOT/n).is_file()}

def save(state):
    (OUT/'execution-receipt.json').write_text(json.dumps(state, indent=2) + '\n')

def main():
    state_lock = threading.RLock()
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument('stage', choices=('generate', 'compile', 'run'))
    ap.add_argument('--gsim', type=Path, required=True)
    ap.add_argument('--cxx', type=Path, required=True)
    ap.add_argument('--native-audit', type=Path, required=True)
    args = ap.parse_args()
    # Preserve the clang++ executable basename; resolving to clang breaks C++ linkage.
    gsim, cxx = args.gsim.absolute(), args.cxx.absolute()
    assert sha(gsim) == GSIM_SHA and sha(args.native_audit) == NATIVE_SHA
    assert subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT).decode().strip() == BASE
    subprocess.run(['git','diff','--exit-code', BASE, '--','src/main','third_party'], cwd=ROOT, check=True)
    receipt = OUT/'execution-receipt.json'
    current = tracked()
    sources = {str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'src/test').rglob('*.scala'))}
    sources.update({str(Path(__file__).relative_to(ROOT)):sha(__file__)})
    if receipt.exists():
        state = json.loads(receipt.read_text())
        assert state['tracked_source_sha256'] == current, 'tracked source drift'
        assert state['test_source_sha256'] == sources, 'test/source adapter drift'
    else:
        state = {'schema':'combined3554932-fullboard-bandwidth-v1', 'status':'PREPARED',
            'base_commit':BASE, 'production_unchanged':True, 'qualification_inherited':False,
            'native_audit_sha256':NATIVE_SHA, 'tracked_source_sha256':current,
            'test_source_sha256':sources, 'commands':[], 'cases':{}, 'negative_controls':{},
            'service_law':{'clock_hz':100000000,'dut_shared_slots':4,'dut_write_credits':2,
                'host_read_credits':8,'host_write_credits':8,'AR_to_R_cycles':32,'R_beat_gap':1,
                'WLAST_to_B_cycles':32,'AR_hold':'cycle % 7 == 2','AW_hold':'cycle % 11 == 3',
                'W_hold':'cycle % 5 == 1','read_write_independent':True},
            'limits':['CPU/cache/common board fabric execution with explicit idle services.',
                'No MIG/DDR PHY/CDC or physical-clock simulation; no board measurement.',
                'No full Linux, complete ISA regression, NEMU or routed timing qualification.']}
    def guard():
        assert tracked() == current, 'tracked source changed during execution'
        assert {str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'src/test').rglob('*.scala'))} == {
            k:v for k,v in sources.items() if k.startswith('src/test/')}, 'test source changed'
    def command(name, argv, cwd=ROOT, anchor=None, negative=False, timeout=1200):
        guard()
        log = OUT/(name+('-final' if args.stage == 'run' else '')+'.log')
        assert not log.exists(), 'preserve prior command log: '+str(log)
        print(name, flush=True)
        started = time.time()
        with log.open('x') as stream:
            result = subprocess.run([str(a) for a in argv], cwd=cwd, stdout=stream,
                stderr=subprocess.STDOUT, timeout=timeout,
                env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        text = log.read_text()
        with state_lock:
            state['commands'].append({'name':name,'argv':list(map(str,argv)),'cwd':str(cwd),
                'exit':result.returncode,'seconds':time.time()-started,'log':str(log.relative_to(OUT)),
                'log_sha256':sha(log),'negative':negative})
            save(state)
        assert (result.returncode != 0 if negative else result.returncode == 0), text[-5000:]
        assert anchor is None or anchor in text, text[-5000:]
        guard()
        return text
    def model_inventory():
        return {p.name:sha(p) for p in sorted(MODEL.iterdir()) if p.is_file() and
            p.suffix in ('.fir','.h','.cpp','.o')}
    state['tools'] = {'gsim':{'path':str(gsim),'sha256':sha(gsim)},
        'cxx':{'path':str(cxx),'sha256':sha(cxx),
            'version':subprocess.check_output([cxx,'--version'],text=True).splitlines()[0]}}
    save(state)
    try:
        if args.stage == 'generate':
            assert 'PASS_COMBINED_BANDWIDTH_GSIM_NATIVE_MATCH' in (OUT/'emit.log').read_text()
            actual = json.loads((MODEL/'actual-combined-gsim.json').read_text())
            native = json.loads(args.native_audit.read_text())
            for key in ('core','profile','geometry','featureFlags'):
                assert actual[key] == native[key], key
            assert actual['nativeCommonCpuFabricMatch'] is True
            assert not list(MODEL.glob('BoardSocGsim*.cpp')), 'generation already exists'
            state['actual_model_configuration'] = actual
            state['actual_fabric_sha256'] = sha(MODEL/'actual-fabric.json')
            state['status'] = 'GENERATING'; save(state)
            command('generate',[gsim,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(MODEL),MODEL/'BoardSocGsim.fir'])
            assert (MODEL/'BoardSocGsim.h').is_file() and list(MODEL.glob('BoardSocGsim[0-9]*.cpp'))
            state['model_artifacts'] = model_inventory()
            state['status'] = 'MODEL_GENERATED_NOT_EXECUTED'
        elif args.stage == 'compile':
            assert state['model_artifacts'] == model_inventory(), 'generated model drift'
            host = HERE/'host'
            assert (host/'cpu_passive_bandwidth.cpp').is_file()
            state['host_source_sha256'] = {str(p.relative_to(host)):sha(p) for p in sorted(host.rglob('*')) if p.is_file()}
            expected = json.loads((ROOT/'simulator/gsim/ready_store_query77/inputs.json').read_text())
            assert sha(GUEST/'guest.bin') == expected['guest_generation']['copy']['expected_bin_sha256']
            assert sha(GUEST/'cpu_sv39_symbols.h') == expected['guest_generation']['copy']['expected_symbols_sha256']
            state['guest_sha256'] = sha(GUEST/'guest.bin')
            flags = expected['host_flags']
            includes = ['-I'+str(p) for p in (host,host/'harness',GUEST,MODEL)]
            state['host_flags'] = flags
            state['status'] = 'COMPILING'; save(state)
            units = sorted(MODEL.glob('BoardSocGsim[0-9]*.cpp'))
            objects = [unit.with_suffix('.o') for unit in units]
            def compile_unit(item):
                i,unit = item
                command('compile-parallel-'+str(i),[cxx,*flags,*includes,'-c',unit,'-o',objects[i]])
            # Three bounded jobs after verifying >8 GiB available RAM; the model
            # and sanitizer flags remain identical to the serial attempt.
            state['compile_jobs'] = 3; save(state)
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(compile_unit,enumerate(units)))
            command('link',[cxx,*flags,*includes,'-MMD','-MF',OUT/'host.d',
                host/'cpu_passive_bandwidth.cpp',*objects,'-ldl','-o',OUT/'run'])
            state['model_artifacts'] = model_inventory()
            state['executable_sha256'] = sha(OUT/'run')
            state['status'] = 'COMPILED_NOT_EXECUTED'
        else:
            assert state['model_artifacts'] == model_inventory(), 'model/object drift'
            assert sha(OUT/'run') == state['executable_sha256']
            host = HERE/'host'
            assert state['host_source_sha256'] == {str(p.relative_to(host)):sha(p) for p in sorted(host.rglob('*')) if p.is_file()}
            state['status'] = 'EXECUTING'; save(state)
            def execute_case(case):
                    op,label,mode=case
                    name=f'{label}-'+('sv39' if mode else 'bare')
                    directory=OUT/(name+'-final'); directory.mkdir()
                    text=command(name,[OUT/'run',GUEST/'guest.bin',mode,op,65536,2],cwd=directory,
                        anchor='CPU_SV39_PASS',timeout=1200)
                    lines=[l for l in text.splitlines() if l.startswith('CPU_SV39_RESULT ')]
                    assert len(lines)==1
                    data=dict(w.split('=',1) for w in lines[0].split()[1:])
                    row={k:float(v) if k=='payload_MiBps' else int(v) for k,v in data.items()}
                    assert row['bytes']==65536 and row['reps']==2 and row['mode']==mode and row['op']==op
                    row['payload_bytes']=131072
                    row['inclusive_cycles']=row['cycles']+row['clean_tail']
                    row['inclusive_MiBps']=12500000/row['inclusive_cycles']
                    with state_lock:
                        state['cases'][name]=row; save(state)
                    print(name, row['cycles'], row['clean_tail'], row['inclusive_MiBps'], flush=True)
            state['runtime_jobs']=3; save(state)
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(execute_case,[(op,label,mode)
                    for op,label in enumerate(('read','write','copy')) for mode in (0,1)]))
            for label in ('read','write','copy'):
                a,b=state['cases'][label+'-bare'],state['cases'][label+'-sv39']
                for key in ('retired','pc_hash','loads','stores','total_loads','total_stores'):
                    assert a[key]==b[key], ('Bare/Sv39 architectural drift',label,key)
            for inject,anchor,op,mode,size in [('read','CPU read data mismatch',0,1,4096),
                    ('memory','final copied/stored memory mismatch',2,1,4096),
                    ('trap','unexpected CPU trap cause',0,1,4096),
                    ('guard-commit','guard request token appeared in architectural commit stream',0,0,65536),
                    ('total-count','whole-program architectural memory instruction count',0,0,4096)]:
                name='negative-'+inject; directory=OUT/(name+'-final'); directory.mkdir()
                command(name,[OUT/'run',GUEST/'guest.bin',mode,op,size,1,'--inject-'+inject],
                    cwd=directory,anchor=anchor,negative=True,timeout=300)
                state['negative_controls'][inject]='REJECTED_AT_EXPECTED_ORACLE';save(state)
            state['status']='PASS_CURRENT_COMBINED_FULLBOARD_BANDWIDTH'
            state.pop('final_qualification_pending',None)
            state['guard_and_flush_oracles']='Full-token guard anti-retirement, cancellation/discard, whole-program counts, guard bytes, and BW_DONE write/B checks passed on all six final cases.'
        save(state)
    except Exception as error:
        state['status']='FAIL_'+args.stage.upper();state['error']=str(error);save(state);raise

if __name__=='__main__':
    main()
