#!/usr/bin/env python3
"""Zero-DUT-build Bare ROM comparison using sealed 7daf119 and combined return-flow candidate objects."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import buffered_return_flow_cpu as cpu

R, common, need, sha = cpu.common.ROOT, cpu.common, cpu.need, cpu.sha
OLD = common.BUILD / 'buffered-third-rank-bare-rom-20261025-r1'
OLD_SHA = '3803363cdc16748ccfae436f9e0491c217b308be9c2c737c7851bdf627f8fb06'
HISTORY = common.BUILD / 'guarded-bare-rom-20261025-r1'
HISTORICAL = HISTORY / 'historical'


def metrics(path):
    text = path.read_text()
    cpu.base.check_log(text)
    final = [json.loads(x.split(' ', 1)[1]) for x in text.splitlines() if x.startswith('BOOTROM_PASS ')]
    rois = [json.loads(x.split(' ', 1)[1]) for x in text.splitlines() if x.startswith('BOOTROM_ROI ')]
    need(len(final) == 1 and len(rois) == 6, 'unique Bare guest PASS and six ROI records required')
    return {'final': final[0], 'rois': rois}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--cpu-receipt', type=Path, required=True)
    parser.add_argument('--tool-receipt', type=Path, required=True)
    parser.add_argument('--build-run', action='store_true')
    args = parser.parse_args()
    args.cpu_receipt = args.cpu_receipt.resolve()
    args.tool_receipt = args.tool_receipt.resolve()
    need(cpu.re.fullmatch(r'[A-Za-z0-9_-]+', args.tag), 'safe fresh output tag required')
    need(sha(OLD / 'receipt.json') == OLD_SHA, 'sealed 7daf119 Bare receipt changed')
    old, current = cpu.read(OLD / 'receipt.json'), cpu.read(args.cpu_receipt)
    tools = cpu.epoch.tool_binding(args.tool_receipt)
    need(old['status'] == 'PASS_EXACT_BUFFERED_BARE_ROM' and
         current['schema'] == cpu.RESULT_SCHEMA and current['status'].startswith('PASS_') and
         old['tools'] == current['tools_before'] == tools, 'same corrected epoch and actual candidate CPU PASS required')
    model = args.cpu_receipt.parent / cpu.CANDIDATE
    record = current['models'][cpu.CANDIDATE]
    first = cpu.verify_build(model, tools['compiler']['command'], Path(record['first_build']['host']))
    need(first == record['first_build'], 'candidate object content keys changed')
    files = {str(OLD / 'receipt.json'): OLD_SHA, str(args.cpu_receipt): sha(args.cpu_receipt),
             str(Path(__file__).resolve()): sha(Path(__file__).resolve())}
    files.update({str(OLD / p): d for p, d in old['artifacts'].items()})
    files.update(old['inputs_before'])
    files.update({str(args.cpu_receipt.parent / p): d for p, d in current['artifacts_sha256'].items()})
    need(cpu.row.unchanged_artifacts({'artifacts': files}), 'sealed historical/CPU/Bare artifacts changed')
    if not args.build_run:
        print('BARE_PREFLIGHT_PASS_NO_BUILD')
        return
    out = common.BUILD / args.tag
    out.mkdir(exist_ok=False)
    for label in ('control', 'candidate'):
        (out / label).mkdir()
    report = {'schema': 'buffered-return-flow-bare-host-only-v1', 'status': 'RUNNING', 'inputs_before': files,
              'tools': tools, 'models': {}, 'new_DUT_compilations': 0, 'guest_rebuilds': 0,
              'new_host_compilations': 0}
    save = lambda: cpu.save(out / 'receipt.json', report)
    save()
    try:
        common.run([OLD / 'candidate/run'], env=cpu.base.runtime_env(), log=out / 'control/run.log', timeout=180)
        need((out / 'control/run.log').read_bytes() == (OLD / 'candidate/run.log').read_bytes(), '7daf119 Bare replay changed')
        report['models']['control'] = metrics(out / 'control/run.log')
        flags = cpu.read(HISTORY / 'receipt.json')['flags']
        cxx = tools['compiler']['command']
        include = ['-I' + str(model), '-I' + str(R / 'simulator/gsim/harness')]
        host = HISTORICAL / 'probe.cpp'
        obj, binary = out / 'candidate/host.o', out / 'candidate/run'
        common.run([cxx, *flags, *include, '-fsyntax-only', host], log=out / 'candidate/syntax.log', timeout=180)
        common.run([cxx, *flags, *include, '-c', host, '-o', obj], log=out / 'candidate/compile.log', timeout=600)
        report['new_host_compilations'] = 1
        common.run([cxx, *flags, *first['DUT_objects'], obj, '-ldl', '-o', binary], log=out / 'candidate/link.log', timeout=600)
        common.run([binary], env=cpu.base.runtime_env(), log=out / 'candidate/run.log', timeout=180)
        report['models']['candidate'] = metrics(out / 'candidate/run.log')
        a, b = report['models']['control'], report['models']['candidate']
        invariant = ('retired', 'oracle_loads', 'oracle_stores', 'source_read_ops', 'source_read_bytes',
                     'validation_byte_loads', 'physical_loads', 'physical_stores', 'physical_replies',
                     'store_local_completions', 'forwarded', 'proof_query_accept', 'proof_query_offer',
                     'nonretired_memory_starts')
        need(all(a['final'][k] == b['final'][k] for k in invariant), 'Bare architectural/traffic/byte accounting changed')
        need(all(all(x[k] == y[k] for k in ('case', 'kind', 'retired', 'physical_loads', 'physical_stores'))
                 for x, y in zip(a['rois'], b['rois'])), 'Bare ROI architecture/memory identity changed')
        # This fixed Bare guest has no virtual advisory query path. These are
        # mode invariants, not freely varying scheduling/route measurements.
        need(all(m['final'][k] == 0 for m in (a, b)
                 for k in ('proof_query_accept', 'proof_query_offer')),
             'fixed Bare guest must issue no virtual advisory proof queries')
        report['bare_no_advisory_query_invariant'] = {'proof_query_accept': 0, 'proof_query_offer': 0}
        report['final_differences'] = cpu.row.differences(a['final'], b['final'])
        report['roi_differences'] = [cpu.row.differences(x, y) for x, y in zip(a['rois'], b['rois'])]
        report['all_full_logs_equal'] = (out / 'control/run.log').read_bytes() == (out / 'candidate/run.log').read_bytes()
        report['status'] = 'PASS_EXACT_BUFFERED_RETURN_FLOW_BARE_ROM' if a == b and report['all_full_logs_equal'] else 'PASS_RETURN_FLOW_BARE_FUNCTIONAL_WITH_REPORTED_DIFFERENCES'
    except BaseException as error:
        report.update(status='FAIL', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        report['inputs_unchanged'] = cpu.row.unchanged_artifacts({'artifacts': files})
        report['tools_unchanged'] = cpu.epoch.tool_binding(args.tool_receipt) == tools
        if not report['inputs_unchanged'] or not report['tools_unchanged']:
            report['status'] = 'FAIL_SOURCE_TOOL_ARTIFACT_DRIFT'
        report['artifacts'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*') if p.is_file() and p.name != 'receipt.json'}
        save()
    need(report['status'].startswith('PASS_'), report['status'])
    print(report['status'])


if __name__ == '__main__':
    main()
