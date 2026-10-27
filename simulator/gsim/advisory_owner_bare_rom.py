#!/usr/bin/env python3
"""Immutable Bare ROM, host-only traces over cached 51422/owner-only/combined DUTs.

API run(models, tools, out): models has control/owner_only/combined entries,
each with path and verified first_build. Caller must already pass current CPU
structure/components gates before building either new DUT. No DUT is built here.
"""
import argparse
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import buffered_return_flow_cpu as cpu
import buffered_return_flow_bare_rom as old_bare
import advisory_owner_trace as trace

R, need, sha = cpu.common.ROOT, cpu.need, cpu.sha
OLD = R / 'build/gsim/buffered-return-flow-bare-rom-20261025-r1'
OLD_SHA = '1e6690a5f5026af7d6dcca40858b872076f3e97ea88b3f65dbd97e9e034da234'
HOST = R / 'build/gsim/guarded-bare-rom-20261025-r1/historical/probe.cpp'
LABELS = ('control', 'owner_only', 'combined')


def history(tools):
    need(sha(OLD/'receipt.json') == OLD_SHA, 'sealed 51422 Bare receipt changed')
    prior = cpu.read(OLD/'receipt.json')
    need(prior['status'].startswith('PASS_') and prior['tools'] == tools,
         'qualified same-epoch Bare control required')
    files = {str(OLD/'receipt.json'): OLD_SHA, **prior['inputs_before'],
             **{str(OLD/p): d for p, d in prior['artifacts'].items()}}
    need(cpu.row.unchanged_artifacts({'artifacts': files}), 'historical Bare inputs/artifacts drift')
    need(str(HOST) in files and files[str(HOST)] == sha(HOST), 'original immutable Bare host binding missing')
    return prior, files


def run(models, tools, out):
    need(set(models) == set(LABELS), 'exact baseline/owner-only/combined models required')
    prior, bound = history(tools)
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    bound.update({str(Path(__file__).resolve()): sha(Path(__file__).resolve()),
                  str(Path(trace.__file__).resolve()): sha(Path(trace.__file__).resolve()),
                  str(trace.HEADER): sha(trace.HEADER)})
    report = {'schema': 'valence-advisory-owner-bare-host-only-v1', 'status': 'RUNNING',
              'new_DUT_compilations': 0, 'guest_rebuilds': 0, 'new_host_compilations': 0,
              'tools': tools, 'inputs': bound, 'models': {}, 'traces': {}}
    cpu.save(out/'receipt.json', report)
    try:
        for label in LABELS:
            model = Path(models[label]['path'])
            first = models[label]['first_build']
            need(cpu.row.unchanged_artifacts(first), 'verified cached DUT objects drift: ' + label)
            plan = trace.prepare(model, out/label, {'bare': HOST})
            traced = trace.run_prepared(plan, tools, first)
            report['traces'][label] = traced
            report['new_host_compilations'] += traced['new_host_compilations']
            log = Path(traced['runs']['bare']['functional_log'])
            report['models'][label] = old_bare.metrics(log)
            final = report['models'][label]['final']
            need(final['proof_query_accept'] == final['proof_query_offer'] == 0,
                 'fixed M-mode/SATP0 Bare guest must never offer/accept virtual proof query')
            cpu.save(out/'receipt.json', report)
        # Removing only our new trace summary must reproduce the sealed baseline
        # complete log, not merely selected cycle or result counters.
        control_log = Path(report['traces']['control']['runs']['bare']['functional_log'])
        need(control_log.read_bytes() == (OLD/'candidate/run.log').read_bytes(),
             '51422 immutable Bare replay changed')
        report['owner_only_exact'] = trace.compare_exact(report['traces']['control'], report['traces']['owner_only'])
        a, b = report['models']['control'], report['models']['combined']
        invariant = ('retired', 'oracle_loads', 'oracle_stores', 'source_read_ops', 'source_read_bytes',
                     'validation_byte_loads', 'physical_loads', 'physical_stores', 'physical_replies',
                     'store_local_completions', 'forwarded', 'proof_query_accept', 'proof_query_offer',
                     'nonretired_memory_starts')
        need(all(a['final'][key] == b['final'][key] for key in invariant),
             'combined Bare architectural/traffic/byte accounting changed')
        need(all(all(x[key] == y[key] for key in ('case','kind','retired','physical_loads','physical_stores'))
                 for x,y in zip(a['rois'],b['rois'])), 'combined Bare ROI architectural identity changed')
        report['combined_final_differences'] = cpu.row.differences(a['final'],b['final'])
        report['combined_roi_differences'] = [cpu.row.differences(x,y) for x,y in zip(a['rois'],b['rois'])]
        report['combined_valid_trace_exact'] = all(
            Path(left['path']).read_bytes() == Path(report['traces']['combined']['runs']['bare']['traces'][guest]['path']).read_bytes()
            for guest,left in report['traces']['control']['runs']['bare']['traces'].items())
        report['bare_zero_advisory_invariant'] = {'proof_query_accept':0,'proof_query_offer':0}
        report['status'] = 'PASS_OWNER_ONLY_EXACT_BARE_AND_COMBINED_FUNCTIONAL'
    except BaseException as error:
        report.update(status='FAIL', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        report['inputs_unchanged'] = cpu.row.unchanged_artifacts({'artifacts':bound})
        report['DUT_objects_unchanged'] = all(cpu.row.unchanged_artifacts(x['first_build']) for x in models.values())
        if not report['inputs_unchanged'] or not report['DUT_objects_unchanged']:
            report['status'] = 'FAIL_SOURCE_OR_CACHED_DUT_DRIFT'
        report['artifacts'] = {str(p.relative_to(out)):sha(p) for p in out.rglob('*')
                               if p.is_file() and p != out/'receipt.json'}
        cpu.save(out/'receipt.json',report)
    need(report['status'].startswith('PASS_'), report['status'])
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--models-plan', type=Path, required=True,
                    help='JSON models={control,owner_only,combined}, tool binding and approved CPU receipt')
    ap.add_argument('--tool-receipt', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--build-run', action='store_true')
    args = ap.parse_args()
    plan = cpu.read(args.models_plan)
    tools = cpu.epoch.tool_binding(args.tool_receipt)
    need(plan['tools'] == tools, 'model plan tool epoch mismatch')
    approved = Path(plan['cpu_receipt'])
    need(sha(approved) == plan['cpu_receipt_sha256'] and cpu.read(approved)['status'].startswith('PASS_'),
         'completed focused CPU approval required')
    history(tools)
    if not args.build_run:
        print('BARE_PREFLIGHT_ONLY_NO_BUILD_OR_RUN'); return
    result = run(plan['models'],tools,args.output)
    print(result['status'])


if __name__ == '__main__':
    main()
