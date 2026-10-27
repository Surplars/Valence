#!/usr/bin/env python3
"""Exact-generated-byte recovery of the second and final authorized CPU build.

Keep the failed two-DUT coordinator immutable. Its first DUT/log/byte traces are
reused, not rerun. Copy the already-generated second model's immutable source
bytes and compile once with a single scoped real-header gate. Never call GSIM.
"""
import argparse
from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
sys.dont_write_bytecode = True
import advisory_owner_cpu as cpu
import advisory_owner_bare_rom as bare

need, sha, read, save = cpu.need, cpu.sha, cpu.read, cpu.save
common, prior, raw = cpu.common, cpu.prior, cpu.raw


@contextmanager
def single_compile_gate():
    original = common.run
    raw.gate.install()
    installed = common.run
    try:
        yield
        need(common.run is installed, 'compiler gate replaced inside scoped build')
    finally:
        common.run = original


def gate_calibration():
    """Two consecutive mock builds exercise the REAL gate and restore its closure."""
    original = common.run
    calls = []
    with tempfile.TemporaryDirectory(prefix='a1-single-gate-') as name:
        root = Path(name)
        compiler = root / 'compiler'; compiler.write_text('mock compiler identity\n')
        def mock(command, **kwargs):
            command = [str(x) for x in command]
            calls.append(command)
            if '-o' in command:
                Path(command[command.index('-o') + 1]).write_text('mock output\n')
        common.run = mock
        try:
            for mode in ('owner', 'combined'):
                out = root / mode; out.mkdir()
                model, host = out / 'ExampleGsim0.cpp', out / 'host.cpp'
                model.write_text('model\n'); host.write_text('host\n')
                (out / 'ExampleGsim.h').write_text('header\n')
                with single_compile_gate():
                    common.run([compiler, '-std=c++20', '-I' + str(out), model, host, '-ldl', '-o', out / 'run'])
                need(common.run is mock, 'single-gate restoration failed')
                receipt = read(out / 'run-compile-receipt.json')
                need(receipt['syntax_pass'] and len(receipt['objects']) == 2 and
                     all(not x['reused'] for x in receipt['objects']), 'mock independent compile gate not exercised')
            with single_compile_gate():
                try:
                    common.run([compiler, '-c', model, '-o', out / 'forbidden.o'])
                except RuntimeError as error:
                    need(str(error) == 'exactly one independent host required for real-header API gate',
                         'wrong missing-host rejection')
                else:
                    raise RuntimeError('gate lost required independent host rejection')
            need(common.run is mock and sum('-fsyntax-only' in c for c in calls) == 2 and
                 sum('-c' in c for c in calls) == 4, 'two-build calibration command shape drift')
        finally:
            common.run = original
    return {'status': 'PASS_REAL_GATE_TWO_SEQUENTIAL_MOCK_BUILDS_AND_RESTORE',
            'builds': 2, 'syntax_checks': 2, 'object_compiles': 4,
            'missing_host_negative': 'EXPECTED_REJECTION', 'DUT_builds': 0}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tag', required=True)
    p.add_argument('--failed-receipt', type=Path, required=True)
    p.add_argument('--tool-receipt', type=Path, required=True)
    p.add_argument('--structure-receipt', type=Path, required=True)
    p.add_argument('--advisory-receipt', type=Path, required=True)
    p.add_argument('--owner-receipt', type=Path, required=True)
    p.add_argument('--owner-continuity-receipt', type=Path, required=True)
    p.add_argument('--build-run', action='store_true')
    args = p.parse_args()
    for key in vars(args):
        if key.endswith('_receipt'):
            setattr(args, key, getattr(args, key).resolve())
    need(cpu.re.fullmatch(r'[A-Za-z0-9_-]+', args.tag), 'fresh safe recovery tag')
    mock = gate_calibration()
    failed = read(args.failed_receipt)
    need(failed['schema'] == cpu.RESULT_SCHEMA and failed['status'] == 'FAIL' and
         failed['failure'] == 'RuntimeError: exactly one independent host required for real-header API gate' and
         failed['new_DUT_builds'] == 1 and failed['owner_only_exact'] is True and
         failed['owner_cycle_trace']['bytes_per_variant'] == 14382720 and
         failed['owner_cycle_trace']['status'] == 'PASS_OWNER_ONLY_EXACT_CYCLE_VALID_TRACES_AND_LOGS',
         'only exact diagnosed wrapper nesting failure is recoverable here')
    tools = prior.epoch.tool_binding(args.tool_receipt)
    need(failed['tools_before'] == tools and failed['inputs_before'] == cpu.inputs() and
         failed['inputs_unchanged'] and failed['tools_unchanged'], 'failed-run source/tool identity drift')
    original_args = copy.copy(args); original_args.tag = args.failed_receipt.parent.name
    _, emission, approval = cpu.reviewed_emission(original_args, tools)
    components = cpu.component_gate(args, Path(emission['compile_receipt']), tools)
    history_model, sealed, history = cpu.bind_history(tools)
    original = args.failed_receipt.parent
    owner = original / cpu.OWNER
    combined = original / cpu.CANDIDATE
    owner_record = failed['models'][cpu.OWNER]
    need(prior.verify_build(owner, tools['compiler']['command'], Path(owner_record['first_build']['host'])) ==
         owner_record['first_build'], 'sealed successful owner object drift')
    old_artifacts = {str(args.failed_receipt): sha(args.failed_receipt),
                     **{str(original / name): digest for name, digest in failed['artifacts_sha256'].items()}}
    need(cpu.row.unchanged_artifacts({'artifacts': old_artifacts}), 'failed-attempt artifact drift')
    need(not list(combined.glob('*.o')) and not (combined / 'run').exists() and
         not (combined / 'run-compile-receipt.json').exists(), 'combined already compiled; no extra DUT allowed')
    generated = sorted(combined.glob(raw.TOP + '[0-9]*.cpp'))
    need(generated and (combined / 'run-header-syntax.log').is_file(), 'combined generation/header syntax stage absent')
    if not args.build_run:
        print(json.dumps({'status': 'PASS_RECOVERY_PREFLIGHT_NO_BUILD', 'mock': mock}));return
    out = common.BUILD / args.tag; out.mkdir(exist_ok=False)
    model = out / cpu.CANDIDATE; model.mkdir()
    copied = {}
    for source in sorted(combined.iterdir()):
        if source.suffix in ('.cpp', '.h', '.fir', '.diff') or source.name in ('effective-config.json', 'effective-parameters.json'):
            target = model / source.name; shutil.copyfile(source, target)
            need(sha(source) == sha(target), 'generated source copy changed bytes')
            copied[str(target)] = sha(target)
    need({x.name for x in generated} == {x.name for x in model.glob(raw.TOP + '[0-9]*.cpp')}, 'generated TU set drift')
    adapters = copy.deepcopy(failed['models'][cpu.CANDIDATE]['host_adapters'])
    for kind in ('vm', 'load'):
        adapters[kind]['adapter'] = str(model / Path(adapters[kind]['adapter']).name)
        need(sha(adapters[kind]['adapter']) == adapters[kind]['adapter_sha256'], 'passive host copy drift')
    record = {'effective_parameters': cpu.row.effective(model), 'path': str(model), 'host_adapters': adapters}
    report = {'schema': 'advisory-owner-exact-generated-cpu-recovery-v1', 'status': 'RUNNING',
              'inputs': {**cpu.inputs(), str(Path(__file__).resolve().relative_to(common.ROOT)): sha(__file__)},
              'original_failure': {'receipt': str(args.failed_receipt), 'sha256': sha(args.failed_receipt),
                                   'preserved_failure': failed['failure']},
              'original_artifacts': old_artifacts, 'copied_source_bytes': copied,
              'tools': tools, 'mock': mock, 'emission_review_binding': approval, 'components': components,
              'owner_only_exact': failed['owner_only_exact'], 'owner_cycle_trace': failed['owner_cycle_trace'],
              'owner_trace_artifacts': failed['owner_trace_artifacts'],
              'models': {cpu.CONTROL: failed['models'][cpu.CONTROL], cpu.OWNER: owner_record, cpu.CANDIDATE: record},
              'model_paths': {cpu.CONTROL: str(history_model), cpu.OWNER: str(owner), cpu.CANDIDATE: str(model)},
              'new_DUT_generations_this_recovery': 0, 'total_DUT_generations_including_failed_attempt': 2,
              'new_DUT_builds_this_recovery': 0, 'total_DUT_builds_including_failed_attempt': 1,
              'reused_owner_runs_not_repeated': True}
    save(out / 'receipt.json', report)
    try:
        prior.candidate_abi_gate(model)
        cxx = tools['compiler']['command']
        sources = sorted(model.glob(raw.TOP + '[0-9]*.cpp'))
        host = Path(adapters['vm']['adapter'])
        with single_compile_gate():
            common.run([cxx, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-I' + str(model), *sources, host, '-ldl', '-o', model / 'run'],
                       log=model / 'compile.log', timeout=600)
        record['first_build'] = prior.verify_build(model, cxx, host)
        report['new_DUT_builds_this_recovery'] = 1
        report['total_DUT_builds_including_failed_attempt'] = 2
        save(out / 'receipt.json', report)
        common.run([model / 'run'], env=cpu.base.runtime_env(), log=model / 'test.log', timeout=180)
        record['second_host'] = prior.load_host(model, tools, record['first_build'], adapters['load'])
        common.run([model / 'load-host/run', '--trace'], env=cpu.base.runtime_env(), log=model / 'load-host/test.log', timeout=180)
        record.update(cpu.collect(model))
        record['negative'] = raw.negative(model)
        report['bare'] = bare.run({
            'control': {'path': history_model, 'first_build': sealed['first_build']},
            'owner_only': {'path': owner, 'first_build': owner_record['first_build']},
            'combined': {'path': model, 'first_build': record['first_build']},
        }, tools, out / 'bare')
        report['comparisons'] = prior.comparisons(report['models'][cpu.CONTROL], record)
        report['status'] = ('PASS_ADVISORY_OWNER_WITH_HOT_GAIN' if report['comparisons']['hot_improved'] and
                            not report['comparisons']['cycle_regressions'] else
                            'PASS_FUNCTIONAL_NO_UNREGRESSED_GAIN_NOT_PROMOTABLE')
    except BaseException as error:
        report.update(status='FAIL', failure=f'{type(error).__name__}: {error}');raise
    finally:
        report['source_and_tool_unchanged'] = all(sha(common.ROOT / p) == d for p, d in report['inputs'].items()) and prior.epoch.tool_binding(args.tool_receipt) == tools
        report['original_artifacts_unchanged'] = cpu.row.unchanged_artifacts({'artifacts': old_artifacts})
        report['copied_source_bytes_unchanged'] = cpu.row.unchanged_artifacts({'artifacts': copied})
        if not all(report[k] for k in ('source_and_tool_unchanged', 'original_artifacts_unchanged', 'copied_source_bytes_unchanged')):
            report['status'] = 'FAIL_SOURCE_TOOL_OR_ARTIFACT_DRIFT'
        report['artifacts'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*') if p.is_file() and p != out / 'receipt.json'}
        save(out / 'receipt.json', report)
    need(report['status'].startswith('PASS_'), report['status'])
    print(json.dumps({'status': report['status'], 'receipt': str(out / 'receipt.json')}))


if __name__ == '__main__':
    main()
