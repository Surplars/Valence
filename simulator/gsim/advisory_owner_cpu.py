#!/usr/bin/env python3
"""Bounded advisory/owner batch: three FIR exports, exactly two fresh CPU DUTs.

OFF permits exactly 13 reviewed generated diagnostic locator relocations from
sealed 51422f5; all other normalized bytes are exact (not raw FIR equality).
Owner-only must be cycle/valid trace exact, separately from combined performance. No build before independent
structure and both actual component approvals. Historical artifacts stay sealed.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
sys.dont_write_bytecode = True
import buffered_return_flow_cpu as prior

common, raw, row, base = prior.common, prior.raw, prior.row, prior.base
need, sha, read, save = prior.need, prior.sha, prior.read, prior.save
CONTROL = prior.CANDIDATE
OWNER = 'full-r1-m3-ordered-owner-ready'
CANDIDATE = 'full-r1-m3-advisory-owner'
PROFILES = (CONTROL, OWNER, CANDIDATE)
MAIN = 'soc.core.ooo.AdvisoryOwnerCpuGsimMain'
REFERENCE = common.BUILD / 'buffered-return-flow-cpu-20261025-r1/receipt.json'
REFERENCE_SHA = 'a816fa84eac57ab3f64d576a998b85db3ed31cc4f031c7c8d882c7604174ff9c'
COMMIT = '51422f567dd8d15d72373ea4984d13ab3ed3650e'
COMMIT_BINDING = common.ROOT / 'build/buffered-return-flow-final-20261025-r1/commit-binding.json'
SOURCE = common.ROOT / 'src/test/scala/platform/AdvisoryOwnerCpuGsim.scala'
EMIT_SCHEMA = 'advisory-owner-frozen-cpu-emission-v1'
RESULT_SCHEMA = 'advisory-owner-two-new-cpu-v1'
STRUCTURE_GATES = {'fullchain_scc', 'no_live_reply_to_completion', 'no_consumer_ready_to_physical_ready',
                   'index_all_consumers', 'no_late_issue_or_va_to_mask_or_selector',
                   'ordered_owner_ready_isolation', 'off_fir_diagnostic_relocation_exact', 'unchanged_capacity'}


def inputs():
    paths = [Path(__file__), SOURCE, common.HERE / 'advisory_owner_trace.py',
             common.HERE / 'harness/advisory_owner_trace.h', common.HERE / 'advisory_owner_bare_rom.py',
             common.HERE / 'test_advisory_owner_trace.py', common.HERE / 'advisory_owner_off_fir.py']
    return {**prior.inputs(), **{str(p.relative_to(common.ROOT)): sha(p) for p in paths}}


def bind_history(tools):
    need(sha(REFERENCE) == REFERENCE_SHA, 'sealed 51422 CPU receipt drift')
    old = read(REFERENCE)
    need(old['status'] == 'PASS_FOCUSED_BUFFERED_RETURN_FLOW_WITH_HOT_GAIN' and
         old['tools_before'] == tools and tools['gsim']['epoch_receipt_sha256'] == prior.EPOCH_SHA,
         'sealed corrected epoch control required')
    binding = read(COMMIT_BINDING)
    need(binding['status'] == 'PASS_PRECOMMIT_VALIDATION_TO_FINAL_SOURCE_EQUALITY' and
         binding['final_commit'] == COMMIT, 'sealed source-to-commit binding required')
    compile_path = common.ROOT / binding['compile_receipt']
    need(sha(compile_path) == binding['compile_receipt_sha256'], 'historical compile receipt drift')
    compiled = read(compile_path)
    historical = {str(Path(p).relative_to(common.ROOT)): d for p, d in compiled['sourceInputs'].items()}
    historical.update(binding['changed_inputs'])
    for name, digest in historical.items():
        blob = subprocess.check_output(['git', 'show', COMMIT + ':' + name], cwd=common.ROOT)
        need(hashlib.sha256(blob).hexdigest() == digest, 'historical committed input mismatch: ' + name)
    model, record = REFERENCE.parent / CONTROL, old['models'][CONTROL]
    artifacts = {str(REFERENCE): REFERENCE_SHA, str(COMMIT_BINDING): sha(COMMIT_BINDING),
                 str(compile_path): sha(compile_path),
                 **{str(REFERENCE.parent / p): d for p, d in old['artifacts_sha256'].items()}}
    need(row.unchanged_artifacts({'artifacts': artifacts}), 'sealed CPU artifact drift')
    need(prior.verify_build(model, tools['compiler']['command'], Path(record['first_build']['host'])) == record['first_build'],
         'sealed CPU object/header/content key mismatch')
    need(row.unchanged_artifacts(record['second_host']), 'sealed second host drift')
    need([x['work_cycles'] for x in record['cases']] == [625, 867] and
         [x['roi_work_cycles'] for x in record['load_cases']] == [359, 358], 'sealed cycles drift')
    return model, record, {'artifacts': artifacts, 'qualified_commit': COMMIT,
                          'historical_compile_identity_preserved': True,
                          'scope': 'immutable baseline objects, newly linked passive trace hosts only'}


def parameter_gate(models, sealed):
    for kind in ('config', 'core'):
        off = models[CONTROL][kind]
        old = sealed['effective_parameters'][kind]
        flags = {'registeredAdvisoryExclusion', 'orderedLsuResponseReady'}
        need(set(off) == set(old) | flags and all(off[k] == v for k, v in old.items()) and
             all(off[k] == 'false' for k in flags), 'OFF parameters changed: ' + kind)
        need(row.differences(off, models[OWNER][kind]) == {'orderedLsuResponseReady': ['false', 'true']},
             'owner-only parameter isolation: ' + kind)
        need(row.differences(models[OWNER][kind], models[CANDIDATE][kind]) ==
             {'registeredAdvisoryExclusion': ['false', 'true']}, 'combined parameter isolation: ' + kind)
    return {'owner_only': ['orderedLsuResponseReady'], 'combined_adds': ['registeredAdvisoryExclusion'],
            'all_other_parameters_exact': True}


def inventory(a_path, b_path):
    _, a = prior.modules(a_path)
    _, b = prior.modules(b_path)
    # This is an inventory, not a substitute for reviewed cone/last-connect checks.
    return {'added': sorted(set(b) - set(a)), 'removed': sorted(set(a) - set(b)),
            'changed': sorted(k for k in set(a) & set(b) if a[k] != b[k]),
            'module_hashes': {k: hashlib.sha256(v).hexdigest() for k, v in b.items()}}


def emit(args, tools, history_model, sealed, history):
    need(args.compile_receipt is not None, 'unified public compile receipt required')
    compiled = row.scala.verify_receipt(args.compile_receipt, common.ROOT)
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    before = inputs()
    report = {'schema': EMIT_SCHEMA, 'status': 'RUNNING', 'inputs': before, 'tools': tools,
              'history_binding': history, 'compile_receipt': str(args.compile_receipt),
              'compile_sha256': sha(args.compile_receipt), 'new_DUT_builds': 0}
    save(out / 'emit-receipt.json', report)
    try:
        for profile in PROFILES:
            target = out / profile
            target.mkdir()
            common.run(['java', '-cp', os.pathsep.join(compiled['runClasspathEntries']), MAIN, target, profile],
                       log=target / 'elaborate.log')
            row.scala.verify_receipt(args.compile_receipt, common.ROOT)
        a = row.normalize_fir((history_model / (raw.TOP + '.fir')).read_bytes())
        b = row.normalize_fir((out / CONTROL / (raw.TOP + '.fir')).read_bytes())
        delta = out / 'disabled-control.diff'
        delta.write_text('' if a == b else ''.join(difflib.unified_diff(a.decode().splitlines(True), b.decode().splitlines(True))))
        import advisory_owner_off_fir as off_fir
        report['disabled_control_gate'] = off_fir.validate(
            (history_model / (raw.TOP + '.fir')).read_bytes(),
            (out / CONTROL / (raw.TOP + '.fir')).read_bytes())
        report['disabled_control_gate']['diff_sha256'] = sha(delta)
        report['parameter_gate'] = parameter_gate({p: row.effective(out / p) for p in PROFILES}, sealed)
        report['cache_gates'] = {p: raw.cache_gate(out / CONTROL, out / p) for p in (OWNER, CANDIDATE)}
        report['module_inventories'] = {p: inventory(out / CONTROL / (raw.TOP + '.fir'), out / p / (raw.TOP + '.fir'))
                                        for p in (OWNER, CANDIDATE)}
        report['status'] = 'PASS_FROZEN_FIR_AWAIT_INDEPENDENT_STRUCTURE_REVIEW'
    except BaseException as error:
        report.update(status='FAIL', failure=f'{type(error).__name__}: {error}')
        raise
    finally:
        report['inputs_unchanged'] = inputs() == before
        report['artifacts'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*')
                               if p.is_file() and p.name != 'emit-receipt.json'}
        save(out / 'emit-receipt.json', report)
    need(report['inputs_unchanged'], 'source drift during emission')
    return report


def reviewed_emission(args, tools):
    out = common.BUILD / args.tag
    path = out / 'emit-receipt.json'
    emission = read(path)
    need(emission['schema'] == EMIT_SCHEMA and
         emission['status'] == 'PASS_FROZEN_FIR_AWAIT_INDEPENDENT_STRUCTURE_REVIEW' and
         emission['inputs_unchanged'] is True and emission['inputs'] == inputs() and emission['tools'] == tools,
         'successful unchanged emission required')
    compile_path = Path(emission['compile_receipt'])
    need(sha(compile_path) == emission['compile_sha256'], 'emission compile receipt drift')
    row.scala.verify_receipt(compile_path, common.ROOT)
    review = read(args.structure_receipt)
    need(review['schema'] == 'valence-advisory-owner-structure-v1' and
         review['status'] == 'PASS_ADVISORY_OWNER_SOURCE_AND_STRUCTURE' and
         review['emit_receipt_sha256'] == sha(path) and review['compile_receipt_sha256'] == sha(compile_path),
         'exact independent structure approval required')
    need(STRUCTURE_GATES <= set(review['gates']) and all(review['gates'][k] == 'PASS' for k in STRUCTURE_GATES),
         'all independent structure gates required')
    need(review['inputs'] and all(sha(common.ROOT / p) == d for p, d in review['inputs'].items()),
         'review source drift')
    artifacts = {str(path): sha(path), str(compile_path): sha(compile_path),
                 str(args.structure_receipt): sha(args.structure_receipt),
                 **{str(out / p): d for p, d in emission['artifacts'].items()},
                 **{str(args.structure_receipt.parent / p): d for p, d in review['artifacts'].items()}}
    need(row.unchanged_artifacts({'artifacts': artifacts}), 'emission/review artifact drift')
    return out, emission, {'artifacts': artifacts, 'independent_structure_pass': True}


def component_gate(args, compile_path, tools):
    # Independent current-batch receipts, never the abstract protocol model alone.
    result = {}
    for kind, path, schema, status in (
        ('advisory', args.advisory_receipt, 'valence-advisory-exclusion-components-v1', 'PASS_ADVISORY_EXCLUSION_COMPONENTS'),
        ('owner', args.owner_receipt, 'valence-ordered-owner-chain-v1', 'PASS_ORDERED_OWNER_CHAIN')):
        need(path is not None, 'actual ' + kind + ' component receipt required')
        r = read(path)
        need(r.get('schema') == schema and r.get('status') == status and r.get('inputs_unchanged') is True,
             'actual component gate failed: ' + kind)
        need(r['tool_epoch'] == tools, 'component tool epoch mismatch: ' + kind)
        continuity = None
        if r['compile_receipt_sha256'] != sha(compile_path):
            need(kind == 'owner' and args.owner_continuity_receipt is not None,
                 'component compile epoch mismatch without exact owner continuity')
            continuity_path = args.owner_continuity_receipt
            continuity = read(continuity_path)
            need(continuity.get('schema') == 'valence-ordered-owner-compile-continuity-v1' and
                 continuity.get('status') == 'PASS_EXACT_FIR_SOURCE_TOOL_CONTINUITY' and
                 continuity['compile_receipt_sha256'] == sha(compile_path) and
                 continuity['original_receipt_sha256'] == sha(path) and
                 continuity['original_compile_receipt_sha256'] == r['compile_receipt_sha256'] and
                 continuity['tool_epoch'] == tools and
                 continuity['all_component_inputs_exact'] is True and
                 continuity['all_fir_bytes_exact'] is True and
                 continuity['new_DUT_builds'] == 0,
                 'explicit owner component continuity qualification failed')
        need(r['inputs'] and all(sha(common.ROOT / p) == d for p, d in r['inputs'].items()), 'component inputs drift')
        artifacts = {str(path): sha(path), **{str(path.parent / p): d for p, d in r['artifacts'].items()}}
        if continuity is not None:
            artifacts[str(continuity_path)] = sha(continuity_path)
            artifacts.update({str(continuity_path.parent / p): d for p, d in continuity['artifacts'].items()})
            need(continuity['inputs'] and all(sha(common.ROOT / p) == d for p, d in continuity['inputs'].items()),
                 'owner continuity source/input drift')
        need(r['artifacts'] and row.unchanged_artifacts({'artifacts': artifacts}), 'component artifact drift')
        result[kind] = {'artifacts': artifacts}
    return result


def collect(model):
    value = prior.candidate_vm_metrics(model)
    log = model / 'load-host/test.log'
    value['load_cases'] = raw.parse(log, 'LOAD_SUPPLY_METRIC ', raw.LOAD_CASES, 'LOAD_SUPPLY_PASS')
    value['proof_metrics'] = raw.parse(log, 'ELASTIC_PROOF_METRIC ', raw.LOAD_CASES, 'LOAD_SUPPLY_PASS')
    value['load_owners'] = prior.load_owners(log)
    value['vm_source_lifetime'] = prior.observer_metrics(model / 'test.log', raw.VM_CASES)
    value['vm_return_index'] = prior.return_observer_metrics(model / 'test.log', raw.VM_CASES)
    value['load_source_lifetime'] = prior.observer_metrics(log, raw.LOAD_CASES)
    value['load_return_index'] = prior.return_observer_metrics(log, raw.LOAD_CASES)
    return value


def build_run(args, tools, history_model, sealed, history):
    import advisory_owner_trace as trace
    import advisory_owner_bare_rom as bare
    out, emission, approval = reviewed_emission(args, tools)
    components = component_gate(args, Path(emission['compile_receipt']), tools)
    need(not (out / 'receipt.json').exists(), 'fresh attempt only; retain failures')
    before = inputs()
    report = {'schema': RESULT_SCHEMA, 'status': 'RUNNING', 'inputs_before': before, 'tools_before': tools,
              'history_binding': history, 'emission_review_binding': approval, 'components': components,
              'models': {}, 'new_DUT_builds': 0, 'hardware_guest_runs': 0,
              'limits': 'focused CPU comparisons; no full regression, Linux, physical timing or ISA compliance claim'}
    base.save_receipt(out, report)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        control = out / CONTROL
        (control / 'load-host').mkdir()
        for name, binary, flags in [('test.log', history_model / 'run', []),
                                    ('load-host/test.log', history_model / 'load-host/run', ['--trace'])]:
            common.run([binary, *flags], env=base.runtime_env(), log=control / name, timeout=180)
            need((control / name).read_bytes() == (history_model / name).read_bytes(), 'sealed baseline replay drift')
        report['models'][CONTROL] = collect(control)
        for key, value in report['models'][CONTROL].items():
            need(json.loads(json.dumps(value)) == sealed[key], 'baseline metric replay drift: ' + key)
        report['hardware_guest_runs'] += 4
        for profile in (OWNER, CANDIDATE):
            model = out / profile
            adapters = prior.host_adapters(model)
            record = {'effective_parameters': row.effective(model), 'host_adapters': adapters}
            report['models'][profile] = record
            record['first_build'] = prior.build_candidate(model, tools, adapters)
            report['new_DUT_builds'] += 1
            base.save_receipt(out, report)
            common.run([model / 'run'], env=base.runtime_env(), log=model / 'test.log', timeout=180)
            record['second_host'] = prior.load_host(model, tools, record['first_build'], adapters['load'])
            common.run([model / 'load-host/run', '--trace'], env=base.runtime_env(), log=model / 'load-host/test.log', timeout=180)
            record.update(collect(model))
            record['negative'] = raw.negative(model)
            report['hardware_guest_runs'] += 4
            if profile == OWNER:
                for name in ('test.log', 'load-host/test.log'):
                    need((model / name).read_bytes() == (control / name).read_bytes(), 'owner-only full original log mismatch: ' + name)
                for key, value in report['models'][CONTROL].items():
                    need(value == record[key], 'owner-only cycle/owner/metric regression: ' + key)
                traces = {}
                for label, source_model, source_record in [('control', history_model, sealed), ('owner', model, record)]:
                    sources = {'vm': Path(source_record['first_build']['host']),
                               'load': Path(read(REFERENCE)['host_adapters']['load']['adapter']) if label == 'control'
                               else Path(adapters['load']['adapter'])}
                    plan = trace.prepare(source_model, out / ('exact-trace-' + label), sources=sources)
                    traces[label] = trace.run_prepared(plan, tools, source_record['first_build'])
                report['owner_cycle_trace'] = trace.compare_exact(traces['control'], traces['owner'])
                report['owner_trace_artifacts'] = traces
                report['owner_only_exact'] = True
                base.save_receipt(out, report)
        report['bare'] = bare.run({
            'control': {'path': history_model, 'first_build': sealed['first_build']},
            'owner_only': {'path': out / OWNER, 'first_build': report['models'][OWNER]['first_build']},
            'combined': {'path': out / CANDIDATE, 'first_build': report['models'][CANDIDATE]['first_build']},
        }, tools, out / 'bare')
        report['hardware_guest_runs'] += 3
        report['comparisons'] = prior.comparisons(report['models'][CONTROL], report['models'][CANDIDATE])
        report['status'] = ('PASS_ADVISORY_OWNER_WITH_HOT_GAIN' if report['comparisons']['hot_improved']
                            and not report['comparisons']['cycle_regressions'] else
                            'PASS_FUNCTIONAL_NO_UNREGRESSED_GAIN_NOT_PROMOTABLE')
    except BaseException as error:
        report.update(status='FAIL', failure=f'{type(error).__name__}: {error}')
        raise
    finally:
        report['inputs_unchanged'] = inputs() == before
        report['tools_unchanged'] = prior.epoch.tool_binding(args.tool_receipt) == tools
        checks = [report['inputs_unchanged'], report['tools_unchanged'], row.unchanged_artifacts(history), row.unchanged_artifacts(approval)]
        checks += [row.unchanged_artifacts(x) for x in components.values()]
        for model in report['models'].values():
            checks += [row.unchanged_artifacts(model.get(key, {})) for key in ('first_build', 'second_host')]
        if not all(checks):
            report['status'] = 'FAIL_SOURCE_TOOL_OR_ARTIFACT_DRIFT'
        report['artifacts_sha256'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*')
                                     if p.is_file() and p.name not in ('receipt.json', 'receipt.json.tmp')}
        base.save_receipt(out, report)
    need(report['status'].startswith('PASS_'), report['status'])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    for name in ('tool', 'compile', 'structure', 'advisory', 'owner'):
        parser.add_argument('--' + name + '-receipt', type=Path, required=name == 'tool')
    parser.add_argument('--owner-continuity-receipt', type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--emit', action='store_true')
    modes.add_argument('--build-run', action='store_true')
    args = parser.parse_args()
    for name in ('tool', 'compile', 'structure', 'advisory', 'owner'):
        key = name + '_receipt'
        if getattr(args, key) is not None:
            setattr(args, key, getattr(args, key).resolve())
    if args.owner_continuity_receipt is not None:
        args.owner_continuity_receipt = args.owner_continuity_receipt.resolve()
    need(re.fullmatch(r'[A-Za-z0-9_-]+', args.tag), 'safe fresh tag required')
    tools = prior.epoch.tool_binding(args.tool_receipt)
    history_model, sealed, history = bind_history(tools)
    raw.host_source_gate()
    if args.emit:
        result = emit(args, tools, history_model, sealed, history)
    elif args.build_run:
        need(args.structure_receipt is not None, 'independent structure required')
        result = build_run(args, tools, history_model, sealed, history)
    else:
        result = {'status': 'PREFLIGHT_ONLY', 'new_DUT_builds': 0}
    print(json.dumps({'status': result['status'], 'new_DUT_builds': result.get('new_DUT_builds', 0)}, indent=2))


if __name__ == '__main__':
    main()
