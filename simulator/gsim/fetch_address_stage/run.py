#!/usr/bin/env python3
"""Serial small real fetch/adapter proof; independent architecture regressions stay separate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / 'simulator/gsim'
sys.path.insert(0, str(HERE))
import run as common

TOP = 'FetchAddressStageGsim'
HOST = HERE / 'harness/fetch_address_stage.cpp'
WRAPPER = ROOT / 'src/test/scala/ooo/FetchAddressStageGsim.scala'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def capture_inputs():
    paths = sorted((ROOT / 'src/main/scala').rglob('*.scala')) + [WRAPPER, HOST, Path(__file__),
        ROOT / 'fpga/next/timing-batch-owner-row-profile.json', HERE / 'config/toolchain.json']
    return {str(p.relative_to(ROOT)): digest(p) for p in paths}

def results(log):
    rows = [json.loads(line[7:]) for line in log.splitlines() if line.startswith('RESULT ')]
    assert len({row['name'] for row in rows}) == len(rows), 'duplicate result name'
    return {row['name']: row for row in rows}

def compare(off, on):
    assert set(off) == {name for name in on if not name.startswith('prep_cancel_')}
    for name, row in off.items():
        assert row['events'] == on[name]['events'], (name, 'ordered event streams differ', row, on[name])
    a, b = off['cold_branch_hot']['metrics'], on['cold_branch_hot']['metrics']
    for metric in ('first_request', 'first_instruction', 'branch_latency'):
        assert b[metric] == a[metric] + 1, (metric, a[metric], b[metric])
    assert a['hot_ii'] == b['hot_ii'] == 1 and a['hot_cycles'] == b['hot_cycles'] == 32
    assert len([name for name in on if name.startswith('prep_cancel_')]) == 6
    assert a['reply_request_turnover'] > 0, 'baseline reply turnover witness missing'
    return {'ordered_event_cases': len(off), 'preparation_cancellation_cases': 6,
            'cold_request_added_cycles': 1, 'cold_instruction_added_cycles': 1,
            'cold_branch_added_cycles': 1, 'hot_ii': 1,
            'baseline_reply_turnover': a['reply_request_turnover'],
            'candidate_reply_turnover': b['reply_request_turnover'],
            'comparison': 'ordered event streams; no same-cycle equality requirement'}

def existing_toolchain():
    # Explicitly reuse activation. No setup(), make, install, download, or fallback.
    source = Path(os.environ['VALENCE_GSIM_SOURCE']).resolve()
    binary = source / 'build/gsim/gsim'
    assert binary.is_file(), binary
    lock = json.loads((HERE / 'config/toolchain.json').read_text())
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    assert revision == lock['revision'], (revision, lock['revision'])
    assert not subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=source, text=True)
    cxx, version = common.compiler()
    return binary, cxx, {'revision': revision, 'binary_sha256': digest(binary), 'compiler': version}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', default='fetch-address-stage-r1')
    ap.add_argument('--build-run', action='store_true')
    ap.add_argument('--reuse-off-elaboration', action='store_true')
    ap.add_argument('--reuse-models', action='store_true')
    a = ap.parse_args()
    if not a.build_run:
        print(json.dumps({'status':'PREFLIGHT_ONLY','models':3,'serial':True,'full_cpu':False,
            'models_detail':['OFF frontend+adapter','ON frontend+adapter','OFF frontend+adapter+permission+reservoir'],
            'estimated_state_bits_per_model':'frontend roughly 14000 plus adapter <1000; architectural adds reservoir/hints',
            'timing':'unmeasured; model runtime is not FPGA performance'}, indent=2))
        return
    output = common.BUILD / a.tag
    output.mkdir(parents=True, exist_ok=True)
    report = {'status':'RUNNING','source_sha256':capture_inputs(),'models':{},
              'architecture_regressions':{},'scope':'module behavior; no complete CPU, synthesis, routed timing, or board claim'}
    try:
        gsim,cxx,report['toolchain'] = existing_toolchain()
        for name,parameters in [('off',[]),('on',['--staged']),('architecture',['--architectural'])]:
            directory=output/name;directory.mkdir(exist_ok=True)
            reuse = a.reuse_models and (directory/(TOP+'.fir')).is_file()
            if not (reuse or (name=='off' and a.reuse_off_elaboration)):
                common.run(['mill','-i','IonSoC.test.runMain','ooo.FetchAddressStageGsimMain',directory,*parameters],
                           log=directory/'elaborate.log')
            else:
                frozen=json.loads((output/'source-freeze.json').read_text())
                assert all(digest(ROOT/path)==sha for path,sha in frozen.items()), 'elaborated source drift'
                assert (directory/(TOP+'.fir')).is_file()
            if not (reuse and (directory/(TOP+'.h')).is_file()):
                common.run([gsim,'--threads=1','--dir='+str(directory),directory/(TOP+'.fir')],log=directory/'generate.log')
            flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(directory)]
            objects=[]
            for cpp in sorted(directory.glob(TOP+'[0-9]*.cpp')):
                obj=cpp.with_suffix('.o');objects.append(obj)
                if not (reuse and obj.is_file()):
                    common.run([cxx,*flags,'-c',cpp,'-o',obj],log=cpp.with_suffix('.compile.log'))
            exe=directory/'run'
            common.run([cxx,*flags,*objects,HOST,'-ldl','-o',exe],log=directory/'host-compile.log')
            env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
            if name=='architecture':
                for case in ('cnop16','straddle32'):
                    run=subprocess.run([exe,'--architecture',case],text=True,capture_output=True,timeout=60,env=env)
                    (directory/(case+'.log')).write_text(run.stdout+run.stderr)
                    assert run.returncode in (0,42), (case,run.returncode,run.stderr)
                    line=next(line for line in run.stdout.splitlines() if line.startswith('ARCH '))
                    finding=json.loads(line[5:]);finding['status']='PASS' if run.returncode==0 else 'CONFIRMED_EXISTING_FAILURE'
                    report['architecture_regressions'][case]=finding
            else:
                args=['--staged'] if name=='on' else []
                common.run([exe,*args],log=directory/'test.log',timeout=90,env=env)
                report['models'][name]=results((directory/'test.log').read_text())
                negative=subprocess.run([exe,*args,'--inject-mask'],text=True,capture_output=True,timeout=60,env=env)
                (directory/'negative-mask.log').write_text(negative.stdout+negative.stderr)
                assert negative.returncode!=0 and 'negative physical-mask oracle mutation detected' in negative.stderr
            (output/'progress.json').write_text(json.dumps(report,indent=2)+'\n')
        report['paired']=compare(report['models']['off'],report['models']['on'])
        assert capture_inputs()==report['source_sha256'],'source drift during qualification'
        report['timing_stage_status']='PASS'
        report['status']='TIMING_PASS_WITH_SEPARATE_ARCHITECTURE_RESULTS'
    except BaseException as error:
        report['status']='FAIL';report['error']=str(error);raise
    finally:
        (output/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':
    main()
