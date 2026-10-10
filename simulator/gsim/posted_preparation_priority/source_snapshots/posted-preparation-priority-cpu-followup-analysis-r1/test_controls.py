#!/usr/bin/env python3
"""Tiny helper controls only. No DUT, historical raw parser, or qualification."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import close_pair as a

positive = []
rejections = []


def reject(name, fn, reason):
    try:
        fn()
    except RuntimeError as e:
        assert reason in str(e), (name, str(e))
        rejections.append(dict(name=name, status='REJECTED', reason_contains=reason))
    else:
        raise AssertionError('escaped control: ' + name)


def mutation(value, name, edit, fn, reason):
    bad = copy.deepcopy(value)
    edit(bad)
    reject(name, lambda: fn(bad), reason)


def synthetic_identity():
    return dict(schema='posted-preparation-priority-cpu-case-v1',
                status='SCOPED_PASS_WITH_BOUNDARY_JOIN_UNKNOWN', side='off', case=6,
                new_execution=True, guest_changed=False, model_rebuilt=False,
                steps=[dict(exit=n, expected=n, guard=None) for n in (0, 0, 1)],
                checks={name: 'PASS' for name in a.pair.ORACLES},
                pins_path=a.CONTRACT['pins_path'], pins_sha256=a.CONTRACT['pins_sha256'])


r = synthetic_identity()
a.identity(r, 'off', 6)
positive.append('warm_OFF_identity_without_COPY_reproduction')
for name, key, value, reason in [
        ('wrong_side', 'side', 'on', 'terminal identity'),
        ('wrong_case', 'case', 0, 'terminal identity'),
        ('running_terminal', 'status', 'RUNNING', 'terminal identity'),
        ('guest_changed', 'guest_changed', True, 'terminal identity'),
        ('model_rebuilt', 'model_rebuilt', True, 'identity/model rebuild'),
        ('different_pins', 'pins_sha256', '0' * 64, 'exact pins changed'),
        ('different_pins_path', 'pins_path', '/synthetic/wrong', 'exact pins changed'),
        ('COPY_only_field', 'original_lru_on_reproduction', {}, 'COPY-only reproduction')]:
    mutation(r, name, lambda x, key=key, value=value: x.update({key: value}),
             lambda x: a.identity(x, 'off', 6), reason)
mutation(r, 'missing_actual_negative', lambda x: x['steps'].pop(),
         lambda x: a.identity(x, 'off', 6), 'trap negative missing')
mutation(r, 'wrong_negative_exit', lambda x: x['steps'][2].update(exit=0),
         lambda x: a.identity(x, 'off', 6), 'trap negative missing')
mutation(r, 'missing_full_fault_oracle', lambda x: x['checks'].pop('fault_trap_CSR_SP_GP'),
         lambda x: a.identity(x, 'off', 6), 'oracle missing')
reject('COPY_case_out_of_scope', lambda: a.identity(r, 'off', 19), 'only warm cases')
reject('bool_case_rejected', lambda: a.identity(r, 'off', False), 'only warm cases')

# All on-disk synthetic data remains under this analysis namespace and is
# destroyed after helper checks. None resembles a saved real terminal result.
with tempfile.TemporaryDirectory(prefix='tiny-controls-', dir=a.HERE) as d:
    folder = Path(d)
    names = {f'{prefix}.{name}.jsonl' for prefix in ('positive', 'trap-negative')
             for name in a.run.TRACE_ENV.values()} | {'positive.window.jsonl.lifetimes.jsonl',
                                                       'host', 'validation.resources.json'}
    for prefix in ('link', 'positive', 'trap-negative'):
        names.update({prefix + '.log', prefix + '.log.resources.json', prefix + '.log.resources.jsonl'})
    for name in names:
        (folder / name).write_text('synthetic tiny helper fixture\n')
    ar = {'artifacts': {name: a.sha(folder / name) for name in names}}
    a.artifact_inventory(ar, folder)
    positive.append('exact_all_raw_executable_log_inventory')
    raw = folder / 'positive.proof.jsonl'
    raw.write_text('altered synthetic helper bytes\n')
    reject('raw_digest_changed', lambda: a.artifact_inventory(ar, folder), 'artifact drift')
    raw.write_text('synthetic tiny helper fixture\n')
    mutation(ar, 'executable_removed_from_inventory', lambda x: x['artifacts'].pop('host'),
             lambda x: a.artifact_inventory(x, folder), 'native executable/log/resource artifact missing')
    mutation(ar, 'required_raw_removed_from_inventory', lambda x: x['artifacts'].pop(raw.name),
             lambda x: a.artifact_inventory(x, folder), 'inventory changed')
    (folder / 'unlisted.txt').write_text('synthetic')
    reject('extra_unlisted_artifact', lambda: a.artifact_inventory(ar, folder), 'inventory changed')

with tempfile.TemporaryDirectory(prefix='tiny-parser-', dir=a.HERE) as d:
    folder = Path(d)
    path = folder / 'validation.resources.json'
    q = dict(stage='validate', out=str(folder), side='off', case=6, measurement=str(path))
    resources = {'fresh_process': True}
    vals = {key: {} for key in a.pair.VALIDATION_KEYS}
    vals['result'] = {'ticks': 10, 'flush_tail': 2}
    vals['proof_trace'] = {'histograms': {1: 3, 10: 2, 2: 1}, 'unknown': [], 'witness_count': 0}
    record = json.loads(json.dumps(vals))
    pins = {'base': {'files': {name: 'f' * 64 for name in a.pair.PARSERS}}}
    raw = json.dumps(q)
    m = dict(schema='cpu-host-measured-stage-v1', status='PASS', stage='validate',
             actual_request=q, actual_stdin_text=raw,
             actual_stdin_sha256=hashlib.sha256(raw.encode()).hexdigest(),
             actual_process_argv=[a.sys.executable, '-B', str(a.HOST / 'stage_measure.py')],
             resources=resources, result_sha256=a.pair.digest_result(vals),
             parser_code_sha256=pins['base']['files'])

    def check_parser(mm, rr=None):
        rr = copy.deepcopy(record) if rr is None else rr
        path.write_text(json.dumps(mm))
        rr.update(measurement_path=str(path), measurement_sha256=a.sha(path), stage_resources=resources)
        return a.pair.measurement(rr, folder, 'off', 6, pins)

    check_parser(m)
    positive.append('frozen_warm_OFF_actual_parser_measurement_without_COPY_field')
    bad = copy.deepcopy(record)
    bad['result']['ticks'] += 1
    reject('tampered_primary_ticks_digest', lambda: check_parser(m, bad), 'result digest mismatch')
    bad = copy.deepcopy(record)
    bad['proof_trace']['unknown'] = [1]
    reject('tampered_full_parser_result_digest', lambda: check_parser(m, bad), 'result digest mismatch')
    for name, edit, reason in [
            ('wrong_parser_case', lambda x: x['actual_request'].update(case=0), 'invocation differs'),
            ('wrong_parser_side', lambda x: x['actual_request'].update(side='on'), 'invocation differs'),
            ('parser_failed', lambda x: x.update(status='FAIL'), 'invocation differs'),
            ('parser_stdin_digest', lambda x: x.update(actual_stdin_sha256='0' * 64), 'stdin digest changed'),
            ('parser_process_argv', lambda x: x['actual_process_argv'].append('--changed'), 'process/resources'),
            ('parser_source_digest', lambda x: x['parser_code_sha256'].update({'proof_trace.py': '0' * 64}), 'source mismatch'),
            ('parser_result_digest', lambda x: x.update(result_sha256='0' * 64), 'result digest mismatch')]:
        mutation(m, name, edit, check_parser, reason)

with tempfile.TemporaryDirectory(prefix='tiny-native-', dir=a.HERE) as d:
    folder = Path(d)
    log = folder / 'trap-negative.log'
    mp = folder / 'trap-negative.log.resources.json'
    rp = folder / 'trap-negative.log.resources.jsonl'
    log.write_text(a.CONTRACT['negative_exact_error'])
    rp.write_text('{"synthetic_helper_control":true}\n')
    argv = [str(folder / 'host'), str(a.HOST / 'guest.bin'), '6', '7', '--inject-trap']
    env = {key: str(folder / ('trap-negative.' + value + '.jsonl')) for key, value in a.run.TRACE_ENV.items()}
    q = dict(stage='command', cmd=argv, log=str(log), seconds=1800, cwd=str(a.HOST), expected=1,
             extra_env=env, artifact_limit_bytes=None, measurement=str(mp))
    raw = json.dumps(q)
    resources = {'fresh_process': True}
    m = dict(schema='cpu-host-measured-stage-v1', status='PASS', stage='command', actual_request=q,
             actual_stdin_text=raw, actual_stdin_sha256=hashlib.sha256(raw.encode()).hexdigest(),
             actual_process_argv=[a.sys.executable, '-B', str(a.HOST / 'stage_measure.py')], resources=resources)
    step = dict(argv=argv, exit=1, expected=1, guard=None, cwd=str(a.HOST), environment=env,
                log=str(log), log_sha256=a.sha(log), measurement_path=str(mp), resource_log=str(rp),
                resource_log_sha256=a.sha(rp), stage_resources=resources)

    def check_native(mm, ss=None):
        ss = copy.deepcopy(step) if ss is None else ss
        mp.write_text(json.dumps(mm))
        ss['measurement_sha256'] = a.sha(mp)
        return a.native_stage(ss, folder, 2, 'off', 6, {})

    check_native(m)
    positive.append('actual_negative_argv_exit_exact_error_and_measured_invocation')
    for name, edit, reason in [
            ('negative_wrong_expected_exit', lambda x: x['actual_request'].update(expected=0), 'measured invocation'),
            ('negative_wrong_guest_case_argv', lambda x: x['actual_request']['cmd'].__setitem__(2, '0'), 'measured invocation'),
            ('negative_wrong_environment', lambda x: x['actual_request']['extra_env'].pop('D_TRANSLATION_TRACE'), 'measured invocation'),
            ('negative_wrong_cwd', lambda x: x['actual_request'].update(cwd='/synthetic'), 'measured invocation'),
            ('negative_stdin_digest', lambda x: x.update(actual_stdin_sha256='0' * 64), 'stdin digest changed'),
            ('negative_process_argv', lambda x: x['actual_process_argv'].append('changed'), 'process/resources'),
            ('negative_failed_stage', lambda x: x.update(status='FAIL'), 'measured invocation')]:
        mutation(m, name, edit, check_native, reason)
    wrong = copy.deepcopy(step)
    wrong['exit'] = 0
    reject('negative_wrong_actual_exit', lambda: check_native(m, wrong), 'argv/exit/guard')
    wrong = copy.deepcopy(step)
    log.write_text(a.CONTRACT['negative_exact_error'] + 'other failure\n')
    wrong['log_sha256'] = a.sha(log)
    reject('negative_extra_error_text', lambda: check_native(m, wrong), 'negative exact error')

for name, off, on, expected in [
        ('equality', (10, 2), (10, 2), ('EQUAL', 'EQUAL', 'EQUAL', False)),
        ('both_gain', (10, 2), (9, 2), ('GAIN', 'GAIN', 'GAIN', True)),
        ('both_regression', (10, 2), (11, 2), ('REGRESSION', 'REGRESSION', 'REGRESSION', False)),
        ('ROI_gain_total_regression', (10, 2), (9, 4), ('GAIN', 'REGRESSION', 'MIXED', False)),
        ('ROI_regression_total_gain', (10, 2), (11, 0), ('REGRESSION', 'GAIN', 'MIXED', False)),
        ('ROI_equal_total_gain', (10, 2), (10, 1), ('EQUAL', 'GAIN', 'GAIN', False)),
        ('ROI_gain_total_equal', (10, 2), (9, 3), ('GAIN', 'EQUAL', 'GAIN', False))]:
    x = dict(ticks=off[0], flush_tail=off[1])
    y = dict(ticks=on[0], flush_tail=on[1])
    t = a.timing(x, y)
    assert (t['roi_status'], t['total_status'], t['performance_status'], t['strict_roi_and_total_gain']) == expected
    a.verify_timing(x, y, t)
    positive.append('timing_' + name)
    mutation(t, 'timing_summary_tamper_' + name, lambda z: z.update(total_cycles_saved=999),
             lambda z: a.verify_timing(x, y, z), 'timing classification/delta changed')
reject('bool_timing', lambda: a.timing(dict(ticks=True, flush_tail=0), dict(ticks=1, flush_tail=0)), 'integer cycle timing')
reject('negative_tail', lambda: a.timing(dict(ticks=1, flush_tail=-1), dict(ticks=1, flush_tail=0)), 'integer cycle timing')

# Exercise the unchanged bridge predicate with an explicitly synthetic upstream
# seam. This is a unit test, not execution of the complete case19 verifier.
with tempfile.TemporaryDirectory(prefix='tiny-followup-', dir=a.HERE) as d:
    folder = Path(d)
    gate_path = folder / 'synthetic-gate.json'
    pins_path = folder / 'synthetic-pins.json'
    pins = {'synthetic_helper_control': True}
    pins_path.write_text(json.dumps(pins))
    gate_path.write_text('{"synthetic_helper_control":true}\n')
    gate = dict(status='PASS_CASE19_NET_GAIN', case=19, permitted_followup_cases=[21, 18, 6, 0],
                pins_path=str(pins_path), pins_sha256='1' * 64)

    def check_bridge(g):
        with patch.object(a.pair, 'verify', return_value=g):
            return a.followup_bridge.verify(gate_path, pins, '1' * 64, 6)

    verified = check_bridge(gate)
    a.check_followup_record({'followup_bridge': verified}, verified, gate_path, a.sha(gate_path))
    positive.append('unchanged_followup_bridge_predicate_with_synthetic_upstream_seam')
    for name, key, value, reason in [
            ('followup_no_case19_gain', 'status', 'NO_CASE19_NET_GAIN', 'case19 net gain required'),
            ('followup_wrong_parent_case', 'case', 21, 'case19 net gain required'),
            ('followup_not_permitted', 'permitted_followup_cases', [21, 18, 0], 'case19 net gain required'),
            ('followup_different_pins', 'pins_sha256', '2' * 64, 'pins changed')]:
        mutation(gate, name, lambda x, key=key, value=value: x.update({key: value}), check_bridge, reason)
    for key, value in [('new_case_execution_required', False), ('prior_variant_gain_inherited', True),
                       ('verification', 'PASS_HISTORICAL_ONLY'), ('sha256', '0' * 64)]:
        mutation(verified, 'followup_contract_' + key, lambda x, key=key, value=value: x.update({key: value}),
                 lambda x: a.check_followup_record({'followup_bridge': x}, x, gate_path, a.sha(gate_path)),
                 'followup contract changed')
    bad = copy.deepcopy(verified)
    bad['sha256'] = '0' * 64
    reject('terminal_followup_differs', lambda: a.check_followup_record({'followup_bridge': bad}, verified, gate_path, a.sha(gate_path)),
           'actual warm followup bridge differs')

warm = dict(checks={'cross_interval_boundary_join': 'UNKNOWN', 'new_frontier_structural_effect': 'NO_STRUCTURAL_WITNESS'},
            boundary_join=dict(status='UNKNOWN_NOT_RECONSTRUCTED', end_offer_edge_raw_sample=None,
                               one_cycle_shift_not_used_to_fabricate_missing_sample=True),
            lru_trace=dict(status='PASS_ACTUAL_REGISTERED_REPLACEMENT_POLICY_AND_BUS', policy=True,
                           all_candidate_history_verified=True, admission_identity_joined=True),
            proof_trace=dict(status='NO_STRUCTURAL_WITNESS', witness_count=0), focused=None)
a.check_applicable_oracles(warm, 'off')
positive.append('warm_zero_proof_witness_is_applicable_and_boundary_stays_UNKNOWN')
mutation(warm, 'fabricated_boundary_sample', lambda x: x['boundary_join'].update(end_offer_edge_raw_sample={}),
         lambda x: a.check_applicable_oracles(x, 'off'), 'unknown endpoint fabricated')
mutation(warm, 'LRU_OFF_is_not_new_flag_OFF', lambda x: x['lru_trace'].update(policy=False),
         lambda x: a.check_applicable_oracles(x, 'off'), 'fixed LRU qualification missing')
mutation(warm, 'OFF_inherited_focused', lambda x: x.update(focused={}),
         lambda x: a.check_applicable_oracles(x, 'off'), 'OFF focused field')
mutation(warm, 'structural_count_tamper', lambda x: x['proof_trace'].update(witness_count=-1),
         lambda x: a.check_applicable_oracles(x, 'off'), 'invalid proof witness count')

print(json.dumps(dict(status='PASS_TINY_ANALYZER_HELPER_CONTROLS_NOT_DUT_QUALIFICATION',
                      synthetic_helpers_only=True, full_runtime_build_or_verify_called=False,
                      actual_warm_pairs_qualified=0, new_DUT_execution=False, raw_parsers_reexecuted=False,
                      positive_controls=positive, rejections=rejections,
                      positive_count=len(positive), rejected_count=len(rejections)), indent=2, sort_keys=True))
