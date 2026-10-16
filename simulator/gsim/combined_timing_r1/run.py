#!/usr/bin/env python3
"""One source-bound combined-timing-r1 model; staged build and matched bounded runs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import concurrent.futures
import threading
import time
import shutil

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = MODEL = GUEST = None
HOST = ROOT / 'simulator/gsim/combined_board_bandwidth/host'
BASE = '3554932ea0b1136ba9b41257385df0c1e8c5ff5c'
GSIM_SHA = 'f00067c6158db342927ad0d746109ad745298fd4ebe9707fd951998069587116'
BASELINE_SHA = 'a90307f521c178d4e84a5b0e5cc2eb07c4d1ada8945239af00ccc8827fb62d89'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def tracked():
    tracked_names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    new_names = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z'],
        cwd=ROOT).decode().split('\0')
    prefixes = ('src/', 'third_party/', 'simulator/gsim/', 'docs/recovery/combined-timing-r1/')
    names = set(tracked_names) | {n for n in new_names if n.startswith(prefixes)}
    return {n: sha(ROOT/n) for n in sorted(names) if n and (ROOT/n).is_file() and
        '__pycache__' not in Path(n).parts and not n.endswith('.pyc')}

def head():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()

def host_hashes():
    return {str(p.relative_to(HOST)): sha(p) for p in sorted(HOST.rglob('*')) if p.is_file()}

def save(state):
    tmp = OUT/'execution-receipt.json.tmp'
    tmp.write_text(json.dumps(state, indent=2) + '\n')
    tmp.replace(OUT/'execution-receipt.json')

def main():
    if not __debug__:
        raise RuntimeError('Do not run this source-bound runner with Python optimization')
    global OUT, MODEL, GUEST
    state_lock = threading.RLock()
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument('stage', choices=('generate', 'compile', 'run'))
    ap.add_argument('--gsim', type=Path, required=True)
    ap.add_argument('--cxx', type=Path, required=True)
    ap.add_argument('--native-audit', type=Path, required=True)
    ap.add_argument('--output-root', type=Path, required=True)
    ap.add_argument('--baseline-receipt', type=Path, required=True)
    ap.add_argument('--baseline-guest-dir', type=Path,
        help='Defaults to baseline receipt directory / guest/copy; reuse original binary and symbols only')
    args = ap.parse_args()
    OUT = args.output_root.absolute()
    MODEL, GUEST = OUT/'model', OUT/'guest/copy'
    OUT.mkdir(parents=True, exist_ok=True)
    # Preserve the clang++ executable basename; resolving to clang breaks C++ linkage.
    gsim, cxx = args.gsim.absolute(), args.cxx.absolute()
    assert sha(gsim) == GSIM_SHA, 'unexpected GSIM binary'
    assert sha(args.baseline_receipt) == BASELINE_SHA, 'not the frozen saved355 final receipt'
    baseline = json.loads(args.baseline_receipt.read_text())
    assert baseline['base_commit'] == BASE and baseline['status'] == 'PASS_CURRENT_COMBINED_FULLBOARD_BANDWIDTH'
    assert host_hashes() == baseline['host_source_sha256'], 'historical host/oracle drift'
    input_name = 'simulator/gsim/ready_store_query77/inputs.json'
    assert sha(ROOT/input_name) == baseline['tracked_source_sha256'][input_name], 'original inputs manifest drift'
    expected = json.loads((ROOT/input_name).read_text())
    assert expected['host_flags'] == baseline['host_flags'], 'compiler flags differ from saved355'
    assert sha(cxx) == baseline['tools']['cxx']['sha256'], 'compiler differs from saved355'
    native_sha = sha(args.native_audit)
    receipt = OUT/'execution-receipt.json'
    current = tracked()
    current_head = head()
    sources = {str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'src/test').rglob('*.scala'))}
    sources.update({str(Path(__file__).relative_to(ROOT)):sha(__file__)})
    if receipt.exists():
        state = json.loads(receipt.read_text())
        assert state['source_commit'] == current_head, 'HEAD changed after staging began'
        assert state['native_audit_sha256'] == native_sha, 'native audit drift'
        assert state['baseline_receipt_sha256'] == sha(args.baseline_receipt), 'baseline receipt drift'
        assert state['tracked_source_sha256'] == current, 'tracked source drift'
        assert state['test_source_sha256'] == sources, 'test/source adapter drift'
    else:
        state = {'schema':'combined-timing-r1-fullboard-bandwidth-v1', 'status':'PREPARED',
            'baseline_commit':BASE, 'source_commit':current_head,
            'dirty_source_snapshot':subprocess.check_output(['git','status','--porcelain=v1'],cwd=ROOT,text=True),
            'baseline_receipt_sha256':BASELINE_SHA, 'baseline_receipt_path':str(args.baseline_receipt.absolute()),
            'production_unchanged':False, 'qualification_inherited':False,
            'native_audit_sha256':native_sha, 'tracked_source_sha256':current,
            'test_source_sha256':sources, 'commands':[], 'cases':{}, 'negative_controls':{},
            'service_law':{'clock_hz':100000000,'dut_shared_slots':4,'dut_write_credits':2,
                'host_read_credits':8,'host_write_credits':8,'AR_to_R_cycles':32,'R_beat_gap':1,
                'WLAST_to_B_cycles':32,'AR_hold':'cycle % 7 == 2','AW_hold':'cycle % 11 == 3',
                'W_hold':'cycle % 5 == 1','read_write_independent':True},
            'limits':['CPU/cache/common board fabric execution with explicit idle services.',
                'No MIG/DDR PHY/CDC or physical-clock simulation; no board measurement.',
                'No full Linux, complete ISA regression, NEMU or routed timing qualification.']}
    assert state['service_law'] == baseline['service_law'], 'service law differs from saved355'
    def evidence_inventory():
        paths = [OUT/'emit.log', OUT/'emission-source-snapshot.json', MODEL/'BoardSocGsim.fir',
            MODEL/'BoardSocGsim.hardware.fir', MODEL/'emission.json',
            MODEL/'actual-combined-timing-gsim.json', MODEL/'actual-fabric.json']
        return {str(p.relative_to(OUT)):sha(p) for p in paths}
    if 'emission_evidence_sha256' in state:
        assert state['emission_evidence_sha256'] == evidence_inventory(), 'emission evidence drift'
    def guard():
        assert head() == current_head, 'HEAD changed during execution'
        assert sha(args.native_audit) == native_sha, 'native audit changed'
        assert sha(args.baseline_receipt) == BASELINE_SHA, 'baseline receipt changed'
        assert sha(gsim) == GSIM_SHA and sha(cxx) == baseline['tools']['cxx']['sha256'], 'tool drift'
        assert host_hashes() == baseline['host_source_sha256'], 'host drift'
        if 'emission_evidence_sha256' in state:
            assert state['emission_evidence_sha256'] == evidence_inventory(), 'emission evidence drift'
        if 'guest_symbols_sha256' in state:
            assert sha(GUEST/'guest.bin') == state['guest_sha256'], 'guest drift'
            assert sha(GUEST/'cpu_sv39_symbols.h') == state['guest_symbols_sha256'], 'guest symbols drift'
        assert tracked() == current, 'tracked source changed during execution'
        assert {str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'src/test').rglob('*.scala'))} == {
            k:v for k,v in sources.items() if k.startswith('src/test/')}, 'test source changed'
    def command(name, argv, cwd=ROOT, anchor=None, negative=False, timeout=1200):
        guard()
        log = OUT/(name+('-final' if args.stage == 'run' else '')+'.log')
        assert not log.exists(), 'preserve prior command log: '+str(log)
        print(name, flush=True)
        started = time.time()
        result = None
        error = None
        try:
            with log.open('x') as stream:
                result = subprocess.run([str(a) for a in argv], cwd=cwd, stdout=stream,
                    stderr=subprocess.STDOUT, timeout=timeout,
                    env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        except BaseException as exc:
            error = exc
        finally:
            with state_lock:
                state['commands'].append({'name':name,'argv':list(map(str,argv)),'cwd':str(cwd),
                    'exit':None if result is None else result.returncode,
                    'error':None if error is None else repr(error),
                    'seconds':time.time()-started,'log':str(log.relative_to(OUT)),
                    'log_sha256':sha(log) if log.exists() else None,'negative':negative})
                save(state)
        if error is not None:
            raise error
        text = log.read_text()
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
            assert state['status'] == 'PREPARED', 'generation requires a new prepared receipt'
            emission_source = json.loads((OUT/'emission-source-snapshot.json').read_text())
            assert emission_source == {'source_commit':current_head, 'tracked_source_sha256':current}, \
                'board emission source snapshot differs from current source'
            emission = json.loads((MODEL/'emission.json').read_text())
            assert emission['schema'] == 'combined-timing-r1-chirrtl-entry-v1'
            assert emission['top'] == 'BoardSocGsim' and emission['arm'] == 'candidate'
            assert emission['chirrtlSha256'] == sha(MODEL/'BoardSocGsim.fir'), 'emitted CHIRRTL hash drift'
            assert emission['hardwareChirrtlSha256'] == sha(MODEL/'BoardSocGsim.hardware.fir'), \
                'normalized CHIRRTL hash drift'
            assert 'PASS_COMBINED_TIMING_R1_BOARD_CHIRRTL candidate=true' in (OUT/'emit.log').read_text()
            actual = json.loads((MODEL/'actual-combined-timing-gsim.json').read_text())
            native = json.loads(args.native_audit.read_text())
            for key in ('core','profile','fieldOrder','geometry','featureFlags','clockHz','counts'):
                assert actual[key] == native[key], key
            assert actual['schema'] == 'combined-timing-r1-platform-actual-v1'
            assert native['schema'] == 'combined-timing-r1-native-actual-v1'
            assert actual['coreFields'] == native['coreFields'] == 179
            assert actual['profileFields'] == native['profileFields'] == 96
            for key in ('registeredHomeRequestBoundary', 'projectedRequestHead',
                    'factorPreparedStorePool', 'proofBankControlDecoupling'):
                assert actual['featureFlags'][key] is True, key
            original_guest = args.baseline_guest_dir or args.baseline_receipt.parent/'guest/copy'
            for name, expected_key in (('guest.bin','expected_bin_sha256'),
                    ('cpu_sv39_symbols.h','expected_symbols_sha256')):
                wanted = expected['guest_generation']['copy'][expected_key]
                assert sha(original_guest/name) == wanted, 'historical guest mismatch: '+name
                GUEST.mkdir(parents=True, exist_ok=True)
                if (GUEST/name).exists():
                    assert sha(GUEST/name) == wanted, 'staged guest drift: '+name
                else:
                    shutil.copyfile(original_guest/name, GUEST/name)
            assert sha(GUEST/'guest.bin') == baseline['guest_sha256']
            state['guest_sha256'] = sha(GUEST/'guest.bin')
            state['guest_symbols_sha256'] = sha(GUEST/'cpu_sv39_symbols.h')
            state['baseline_guest_directory'] = str(original_guest.absolute())
            assert not list(MODEL.glob('BoardSocGsim*.cpp')), 'generation already exists'
            state['emission_evidence_sha256'] = evidence_inventory()
            state['actual_model_configuration'] = actual
            state['actual_fabric_sha256'] = sha(MODEL/'actual-fabric.json')
            state['status'] = 'GENERATING'; save(state)
            command('generate',[gsim,'--threads=1','--cpp-max-size-KB=1024','--dir='+str(MODEL),MODEL/'BoardSocGsim.fir'])
            assert (MODEL/'BoardSocGsim.h').is_file() and list(MODEL.glob('BoardSocGsim[0-9]*.cpp'))
            state['model_artifacts'] = model_inventory()
            state['status'] = 'MODEL_GENERATED_NOT_EXECUTED'
        elif args.stage == 'compile':
            assert state['status'] == 'MODEL_GENERATED_NOT_EXECUTED', 'compile stage is out of order'
            assert state['model_artifacts'] == model_inventory(), 'generated model drift'
            host = HOST
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
            # Preserve the saved355 three-job limit and exact sanitizer/compiler flags.
            state['compile_jobs'] = 3; save(state)
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(compile_unit,enumerate(units)))
            command('link',[cxx,*flags,*includes,'-MMD','-MF',OUT/'host.d',
                host/'cpu_passive_bandwidth.cpp',*objects,'-ldl','-o',OUT/'run'])
            state['model_artifacts'] = model_inventory()
            state['executable_sha256'] = sha(OUT/'run')
            state['status'] = 'COMPILED_NOT_EXECUTED'
        else:
            assert state['status'] == 'COMPILED_NOT_EXECUTED', 'run stage is out of order'
            assert state['model_artifacts'] == model_inventory(), 'model/object drift'
            assert sha(OUT/'run') == state['executable_sha256']
            host = HOST
            assert state['host_source_sha256'] == {str(p.relative_to(host)):sha(p) for p in sorted(host.rglob('*')) if p.is_file()}
            assert sha(GUEST/'guest.bin') == state['guest_sha256'] == baseline['guest_sha256']
            assert sha(GUEST/'cpu_sv39_symbols.h') == state['guest_symbols_sha256']
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
            assert set(state['cases']) == set(baseline['cases']), 'six-case set mismatch'
            assert state['negative_controls'] == baseline['negative_controls'], 'five-control set mismatch'
            comparison = {}
            for name, row in state['cases'].items():
                old = baseline['cases'][name]
                assert set(row) == set(old), ('result metric schema drift', name)
                for key in ('bytes','reps','mode','op','retired','pc_hash','loads','stores',
                        'total_loads','total_stores','payload_bytes','lsu_capacity'):
                    assert row[key] == old[key], ('saved355 architectural/traffic drift',name,key)
                comparison[name] = {key: {'baseline':old[key], 'candidate':row[key],
                    'delta':row[key]-old[key],
                    'ratio':None if old[key] == 0 else row[key]/old[key]} for key in sorted(row)}
            state['saved355_comparison'] = comparison
            state['performance_pass_thresholds'] = None
            (OUT/'comparison-saved355.json').write_text(json.dumps(comparison,indent=2)+'\n')
            state['status']='PASS_CURRENT_COMBINED_TIMING_R1_BOARD_BANDWIDTH'
            state.pop('final_qualification_pending',None)
            state['guard_and_flush_oracles']='Full-token guard anti-retirement, cancellation/discard, whole-program counts, guard bytes, and BW_DONE write/B checks passed on all six final cases.'
        save(state)
    except BaseException as error:
        state['status']='FAIL_'+args.stage.upper();state['error']=str(error);save(state);raise

if __name__=='__main__':
    try:
        main()
    except BaseException as error:
        # Include validation failures before stage execution; never truncate command logs.
        if OUT is not None:
            path = OUT/'execution-receipt.json'
            failure = {'error':repr(error), 'time_unix':time.time()}
            if path.exists():
                state = json.loads(path.read_text())
                state['status_before_failure'] = state.get('status')
                state['status'] = 'FAIL_VALIDATION_OR_EXECUTION'
                state['latest_failure'] = failure
                save(state)
            else:
                (OUT/('validation-failure-'+str(time.time_ns())+'.json')).write_text(
                    json.dumps(failure,indent=2)+'\n')
        raise
