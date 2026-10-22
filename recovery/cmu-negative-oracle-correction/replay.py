#!/usr/bin/env python3
"""Bounded, historical-RTL monitor replay, never current-source qualification.

Validate each immutable original receipt, its exact original TB, its emission
receipt and COMPLETE RTL file inventory, and its original simulator tool chain.
Compile only a corrected testbench against that frozen historical RTL. Current
production-source drift is disclosed, not silently accepted as current proof.
This does not invoke Mill, edit RTL, rewrite receipts, upload, or install tools.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HELPER = ROOT / 'simulator/cdc/test_runtime_epoch_boundary.py'
spec = importlib.util.spec_from_file_location('bounded_native_replay', HELPER)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def verify_hash(path, digest):
    require(path.is_file() and base.sha(path) == digest, 'hash mismatch: ' + str(path))


def replay(tag, info, output):
    receipt_path = ROOT / info['baseline_receipt']
    verify_hash(receipt_path, info['baseline_receipt_sha256'])
    old = json.loads(receipt_path.read_text())
    original_tb = HERE / tag / 'baseline_tb.source.sv'
    corrected_tb = HERE / tag / 'corrected_tb.source.sv'
    verify_hash(original_tb, old['source_sha256'][info['baseline_tb_path']])
    verify_hash(original_tb, info['baseline_tb_sha256'])
    verify_hash(corrected_tb, info['corrected_tb_sha256'])
    verify_hash(HELPER, old['source_sha256']['simulator/cdc/test_runtime_epoch_boundary.py'])
    # Reuse the historical compile command, substituting only output and TB.
    compile_cmd = next((c for c in old.get('commands', []) if '-s' in c), None)
    if compile_cmd is None:
        compile_cmd = next(c['command'] for c in old['cases'] if c['name'] == 'compile')
    compile_cmd = list(compile_cmd)
    historical_tb = str(ROOT / info['baseline_tb_path'])
    require(compile_cmd.count(historical_tb) == 1, 'missing/ambiguous original TB')
    rtl_paths = [Path(x) for x in compile_cmd if x.endswith('.sv') and x != historical_tb]
    require(rtl_paths and len({p.parent for p in rtl_paths}) == 1, 'invalid RTL directory inventory')
    emission_ref = old['emission_receipt']
    emission_path = Path(emission_ref['path'] if isinstance(emission_ref, dict) else emission_ref)
    emission_sha = (emission_ref['sha256'] if isinstance(emission_ref, dict)
                    else old['input_sha256'][str(emission_path)])
    verify_hash(emission_path, emission_sha)
    emission = json.loads(emission_path.read_text())
    require(emission['status'] == 'PASS_EMIT_ONLY', 'original emission did not pass')
    expected_rtl = emission['rtl_sha256']
    if 'rtl_sha256' in old:
        require(old['rtl_sha256'] == expected_rtl, 'receipt/emission RTL inventory mismatch')
    actual_rtl_paths = sorted(rtl_paths[0].parent.glob('*.sv'))
    require(set(rtl_paths) == set(actual_rtl_paths), 'historical compile omitted/added RTL file')
    actual_rtl = {p.name: base.sha(p) for p in actual_rtl_paths}
    require(actual_rtl == expected_rtl, 'historical RTL contents/inventory changed')
    for p in rtl_paths:
        if str(p) in old.get('input_sha256', {}):
            verify_hash(p, old['input_sha256'][str(p)])
    for tool, digest in old['tool_sha256'].items():
        verify_hash(Path(old['tools'][tool]), digest)
    drift = {}
    for name, digest in emission['source_sha256'].items():
        path = Path(name) if Path(name).is_absolute() else ROOT / name
        current = base.sha(path) if path.is_file() else None
        if current != digest:
            drift[name] = {'historical_sha256': digest, 'current_sha256': current}
    run_dir = output / tag
    run_dir.mkdir()
    binary = run_dir / 'corrected-monitor.vvp'
    compile_cmd[compile_cmd.index('-o') + 1] = str(binary)
    compile_cmd[compile_cmd.index(historical_tb)] = str(corrected_tb)
    if tag == 'r10':
        positive = ['+case=0', '+drain_cycles=64', '+cleanup_cycles=128']
        tests = [('positive-matched-control', positive, 'RUNTIME_EPOCH_COMPONENT_PASS', False),
                 ('negative-2', positive + ['+negative=2'], 'EPOCH_ORACLE_RECEIPT', True)]
        corruption = {'negative-2': 'observed_result_seen is replaced with false before the ordinary receipt predicate'}
    else:
        tests = [('positive-matched-control', [], 'CLOCK_RATE_CLEANUP_COMPONENT_PASS', False),
                 ('negative-completion', ['+wrong-completion'], 'controller prematurely completed/released cleanup', True),
                 ('negative-quiesce', ['+wrong-quiesce'], 'controller prematurely completed/released cleanup', True)]
        corruption = {'negative-completion': 'observedCompleted is incremented before the ordinary check_pending predicate',
                      'negative-quiesce': 'observedQuiesce is cleared before the same ordinary check_pending predicate'}
    inputs = {receipt_path: info['baseline_receipt_sha256'], emission_path: emission_sha,
              original_tb: info['baseline_tb_sha256'], corrected_tb: info['corrected_tb_sha256'],
              HERE / 'manifest.json': base.sha(HERE / 'manifest.json'), Path(__file__).resolve(): base.sha(__file__),
              HELPER: base.sha(HELPER), HERE / tag / 'monitor-only.patch': base.sha(HERE / tag / 'monitor-only.patch')}
    inputs.update({p: base.sha(p) for p in actual_rtl_paths})
    inputs.update({Path(path): old['tool_sha256'][tool] for tool, path in old['tools'].items()})
    report = dict(status='RUNNING', mode='HISTORICAL_RTL_CORRECTED_MONITOR_REPLAY',
                  scope='Only monitor sensitivity and one matched positive control; no current-source or broader regression claim',
                  baseline=info, original_emission_receipt={'path': str(emission_path), 'sha256': emission_sha},
                  original_emission_command=emission['command'], original_rtl_directory=str(rtl_paths[0].parent),
                  complete_original_rtl_inventory_sha256=expected_rtl, complete_rtl_inventory_verified=True,
                  current_production_source_qualified=False, current_source_differences=drift,
                  historical_tools=old['tools'], historical_tool_sha256=old['tool_sha256'],
                  corrupted_observations=corruption, input_sha256={str(p): h for p, h in inputs.items()}, cases=[])
    try:
        result = base.run(compile_cmd, run_dir / 'compile.log', 90)
        require(result['returncode'] == 0 and not result['timed_out'] and not result['disk_floor_breached'], 'compile failed')
        report['compile'] = dict(command=compile_cmd, log_sha256=base.sha(run_dir / 'compile.log'), **result)
        report['compiled_sha256'] = base.sha(binary)
        for label, plusargs, marker, negative in tests:
            command = [old['tools']['vvp'], str(binary), *plusargs]
            log = run_dir / (label + '.log')
            result = base.run(command, log, 90)
            content = log.read_text()
            accepted = (result['returncode'] != 0 if negative else result['returncode'] == 0)
            accepted &= not result['timed_out'] and not result['disk_floor_breached'] and marker in content
            if negative:
                accepted &= bool(re.search(r'FATAL: .*corrected_tb\.source\.sv:\d+: ' + re.escape(marker), content))
                accepted &= 'COMPONENT_PASS' not in content
            report['cases'].append(dict(label=label, command=command, expected_negative=negative,
                                         required_ordinary_checker_marker=marker, accepted=accepted,
                                         log_sha256=base.sha(log), **result))
            require(accepted, tag + ': unexpected ' + label + ' outcome: ' + content[-2000:])
        for path, digest in inputs.items():
            verify_hash(path, digest)
        require({p.name: base.sha(p) for p in rtl_paths[0].parent.glob('*.sv')} == expected_rtl,
                'RTL inventory drift during replay')
        require(base.sha(binary) == report['compiled_sha256'], 'compiled image changed during replay')
        report.update(status='PASS_HISTORICAL_RTL_CORRECTED_MONITOR_REPLAY', all_bound_inputs_unchanged=True,
                      original_receipt_unchanged=True, original_rtl_unchanged=True)
    except BaseException as error:
        report.update(status='FAIL', error=str(error))
        raise
    finally:
        report['logs_sha256'] = {p.name: base.sha(p) for p in run_dir.glob('*.log')}
        (run_dir / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    print(tag + ': ' + report['status'], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    require(bool(os.environ.get('VALENCE_CLOUD_ENV')), 'source scripts/cloud/env.sh first')
    output = args.output.resolve()
    require(not output.exists() and output.parent.is_dir(), 'fresh output with existing parent required')
    base.guard(output.parent)
    output.mkdir()
    manifest = json.loads((HERE / 'manifest.json').read_text())
    for tag, info in manifest.items():
        replay(tag, info, output)


if __name__ == '__main__':
    main()
