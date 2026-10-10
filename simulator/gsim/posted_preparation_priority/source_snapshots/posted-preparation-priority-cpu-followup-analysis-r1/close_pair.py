#!/usr/bin/env python3
"""Read-only, digest-bound closure of actual postedPreparationPriority warm pairs.

No DUT or raw parser is executed here. The frozen runner's source/model checks
and complete case19 gate are deliberately called, not replaced with PASS labels.
"""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
HOST = BASE / 'posted-preparation-priority-cpu-host-r2'
CONTRACT_PATH = HERE / 'CONTRACT.json'
CONTRACT_SHA = 'ad1297aad385087a74c7726c07bfb2c54c61f59ca9f531171e2ae649e9673ff3'
SCHEMA = 'posted-preparation-priority-warm-immutable-terminal-pair-v1'
FUNCTIONAL_STATUS = 'PASS_BOTH_ORIGINAL_BYTE_FAULT_CSR_DRAIN_AND_NEGATIVES'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    def unique(pairs):
        require(len(pairs) == len({k for k, _ in pairs}), 'duplicate JSON key')
        return dict(pairs)
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def exact(a, b):
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def regular(path):
    require(stat.S_ISREG(Path(path).lstat().st_mode), 'regular non-symlink evidence required')


def contract():
    require(sha(CONTRACT_PATH) == CONTRACT_SHA, 'analysis contract pin changed')
    c = read(CONTRACT_PATH)
    require(c['schema'] == 'posted-preparation-priority-warm-followup-contract-v1'
            and c['cases'] == [0, 6, 18] and c['host_root'] == str(HOST),
            'analysis contract identity changed')
    # Check code before importing it; run.check subsequently checks the complete
    # source, tools, environment, guest, host, models, preflight, ABI and smokes.
    for name, digest in c['host_files'].items():
        require(Path(name).name == name, 'host dependency path changed')
        require(sha(HOST / name) == digest, 'frozen host dependency changed: ' + name)
    for path, digest in c['import_dependencies'].items():
        require(sha(path) == digest, 'frozen import dependency changed: ' + path)
    return c


CONTRACT = contract()
sys.path.insert(0, str(HOST))
import pair  # noqa: E402
import run  # noqa: E402
import followup_bridge  # noqa: E402
for module in (pair, run, followup_bridge):
    require(Path(module.__file__).resolve() == HOST / (module.__name__ + '.py'),
            'wrong frozen module imported: ' + module.__name__)


def verify_freeze(path, digest):
    path = Path(path).resolve()
    require(path == HERE / 'FREEZE.json' and sha(path) == digest,
            'analysis freeze pin changed')
    f = read(path)
    require(f['schema'] == 'posted-preparation-priority-warm-analysis-freeze-v1'
            and f['status'] == 'FROZEN_ANALYSIS_ONLY_NOT_DUT_QUALIFICATION'
            and f['contract_sha256'] == CONTRACT_SHA, 'analysis freeze contract changed')
    require(set(f['files']) == {'close_pair.py', 'CONTRACT.json', 'test_controls.py',
                                'README.md', 'controls-result.json'},
            'analysis freeze file inventory changed')
    for name, expected in f['files'].items():
        regular(HERE / name)
        require(sha(HERE / name) == expected, 'analysis frozen file changed: ' + name)
    contract()
    return dict(path=str(path), sha256=digest, contract_sha256=CONTRACT_SHA)


def identity(record, side, case):
    require(type(case) is int and case in CONTRACT['cases'], 'only warm cases 0, 6, 18')
    pair.identity(record, side, case)
    require(type(record['case']) is int and record.get('model_rebuilt') is False,
            'warm identity/model rebuild mismatch')
    require(record['pins_path'] == CONTRACT['pins_path']
            and record['pins_sha256'] == CONTRACT['pins_sha256'], 'warm exact pins changed')
    # The COPY-only baseline field is neither required nor silently inherited.
    require('original_lru_on_reproduction' not in record, 'unexpected COPY-only reproduction field')


def artifact_inventory(record, folder):
    for name in record['artifacts']:
        require(Path(name).name == name, 'terminal artifact path traversal')
        regular(folder / name)
    required = {'host', 'validation.resources.json'}
    for name in ('link', 'positive', 'trap-negative'):
        required.update({name + '.log', name + '.log.resources.json',
                         name + '.log.resources.jsonl'})
    require(required <= set(record['artifacts']), 'native executable/log/resource artifact missing')
    # Warm raw storage is unsupported by the frozen helper. Require every raw
    # file to exist; never treat a historical digest or missing file as bytes.
    return pair.artifacts(record, folder)


def native_stage(step, folder, index, side, case, pins):
    prefix = ('link', 'positive', 'trap-negative')[index]
    expected_exit = 1 if index == 2 else 0
    logfile = folder / (prefix + '.log')
    measurement_path = folder / (prefix + '.log.resources.json')
    resource_log = folder / (prefix + '.log.resources.jsonl')
    env = None if index == 0 else {
        key: str(folder / (prefix + '.' + value + '.jsonl'))
        for key, value in run.TRACE_ENV.items()
    }
    argv = (run.command(side, Path(pins['models'][side]['receipt']).parent, folder / 'host')
            if index == 0 else [str(folder / 'host'), str(HOST / 'guest.bin'),
                                  str(case), str(case + 1)]
            + (['--inject-trap'] if index == 2 else []))
    require(step['argv'] == argv and step['exit'] == step['expected'] == expected_exit
            and step['guard'] is None, 'actual native argv/exit/guard changed')
    require(step['cwd'] == str(HOST) and exact(step['environment'], env or {}),
            'actual native cwd/environment changed')
    for key, path in (('log', logfile), ('measurement_path', measurement_path),
                      ('resource_log', resource_log)):
        digest_key = 'measurement_sha256' if key == 'measurement_path' else key + '_sha256'
        require(step[key] == str(path) and sha(path) == step[digest_key],
                'actual native log/resource identity changed: ' + key)
    m = read(measurement_path)
    request = dict(stage='command', cmd=argv, log=str(logfile), seconds=1800,
                   cwd=str(HOST), expected=expected_exit, extra_env=env,
                   artifact_limit_bytes=None, measurement=str(measurement_path))
    require(m['schema'] == 'cpu-host-measured-stage-v1' and m['status'] == 'PASS'
            and m['stage'] == 'command' and exact(m['actual_request'], request)
            and exact(json.loads(m['actual_stdin_text']), request),
            'actual native measured invocation changed')
    require(hashlib.sha256(m['actual_stdin_text'].encode()).hexdigest() == m['actual_stdin_sha256'],
            'actual native stdin digest changed')
    require(m['actual_process_argv'] == [sys.executable, '-B', str(HOST / 'stage_measure.py')]
            and exact(m['resources'], step['stage_resources'])
            and m['resources']['fresh_process'] is True, 'actual native process/resources changed')
    negative_error = None
    if index == 2:
        negative_error = logfile.read_text()
        require(negative_error == CONTRACT['negative_exact_error'], 'actual negative exact error changed')
    return dict(argv=argv, exit=expected_exit, expected=expected_exit, guard=None,
                cwd=str(HOST), environment=env or {}, log=str(logfile), log_sha256=sha(logfile),
                measurement_path=str(measurement_path), measurement_sha256=sha(measurement_path),
                resource_log=str(resource_log), resource_log_sha256=sha(resource_log),
                actual_process_argv=m['actual_process_argv'], actual_request=m['actual_request'],
                actual_stdin_text=m['actual_stdin_text'], actual_stdin_sha256=m['actual_stdin_sha256'],
                resources=m['resources'], exact_negative_error=negative_error)


def check_followup_record(record, verified, gate_path, gate_sha):
    require(verified == dict(path=str(Path(gate_path).resolve()), sha256=gate_sha,
                            verification='PASS_SAME_PINS_FULL_NEW_CASE19_CLOSURE',
                            new_case_execution_required=True, prior_variant_gain_inherited=False),
            'full case19 followup contract changed')
    require(exact(record['followup_bridge'], verified), 'actual warm followup bridge differs')


def check_applicable_oracles(record, side):
    require(record['checks']['cross_interval_boundary_join'] == 'UNKNOWN'
            and record['boundary_join']['status'] == 'UNKNOWN_NOT_RECONSTRUCTED'
            and record['boundary_join']['end_offer_edge_raw_sample'] is None
            and record['boundary_join']['one_cycle_shift_not_used_to_fabricate_missing_sample'] is True,
            'warm unknown endpoint fabricated')
    lru = record['lru_trace']
    require(lru['status'] == 'PASS_ACTUAL_REGISTERED_REPLACEMENT_POLICY_AND_BUS'
            and lru['policy'] is True and lru['all_candidate_history_verified'] is True
            and lru['admission_identity_joined'] is True, 'fixed LRU qualification missing')
    require(record['checks']['new_frontier_structural_effect'] == record['proof_trace']['status'],
            'warm structural status changed')
    require(type(record['proof_trace']['witness_count']) is int
            and record['proof_trace']['witness_count'] >= 0, 'invalid proof witness count')
    if side == 'off':
        require(record['focused'] is None, 'warm OFF focused field must remain absent')
    else:
        gate = record['focused']
        require(gate['path'] == CONTRACT['focused_path'] and gate['sha256'] == CONTRACT['focused_sha256']
                and gate['contract_path'] == CONTRACT['focused_contract_path']
                and gate['contract_sha256'] == CONTRACT['focused_contract_sha256'],
                'fixed focused-v3 aggregate-r4 binding changed')
        require(exact(run.focus(gate['path'], gate['sha256'], gate['contract_path'],
                                gate['contract_sha256']), gate), 'actual ON focused qualification changed')


def one(path, digest, side, case, gate, gate_sha, verified_followup, checked_pins):
    regular(path)
    path = Path(path).resolve()
    require(path.name == 'receipt.json' and sha(path) == digest, 'terminal receipt pin changed')
    regular(path)
    record = read(path)
    identity(record, side, case)
    folder = path.parent
    count = artifact_inventory(record, folder)
    primary = run.parse((folder / 'positive.log').read_text(), 'on', case)
    require(exact(primary, record['result']) and exact(primary, record['positive_terminal_primary']),
            'independent primary reparse differs')
    stages = [native_stage(s, folder, i, side, case, checked_pins)
              for i, s in enumerate(record['steps'])]
    measured = pair.measurement(record, folder, side, case, checked_pins)
    raw_measurement = read(record['measurement_path'])
    require(raw_measurement['schema'] == 'cpu-host-measured-stage-v1', 'parser measurement schema changed')
    measured.update(actual_request=raw_measurement['actual_request'],
                    actual_stdin_text=raw_measurement['actual_stdin_text'],
                    resources=raw_measurement['resources'])
    check_followup_record(record, verified_followup, gate, gate_sha)
    check_applicable_oracles(record, side)
    return record, dict(path=str(path), sha256=digest, parser_execution=measured,
                        native_stages=stages, all_artifacts_hashed=count,
                        artifacts=record['artifacts'], raw_storage=None)


def timing(off, on):
    for r in (off, on):
        require(type(r['ticks']) is int and r['ticks'] > 0
                and type(r['flush_tail']) is int and r['flush_tail'] >= 0,
                'invalid integer cycle timing')
    values = dict(roi_cycles_saved=off['ticks'] - on['ticks'],
                  flush_tail_cycles_saved=off['flush_tail'] - on['flush_tail'],
                  total_cycles_saved=off['ticks'] + off['flush_tail'] - on['ticks'] - on['flush_tail'])
    classify = lambda delta: 'GAIN' if delta > 0 else 'EQUAL' if delta == 0 else 'REGRESSION'
    roi = values['roi_cycles_saved']
    total = values['total_cycles_saved']
    values.update(roi_status=classify(roi), flush_tail_status=classify(values['flush_tail_cycles_saved']),
                  total_status=classify(total), strict_roi_and_total_gain=roi > 0 and total > 0,
                  speedup_required_for_functional_pass=False)
    values['performance_status'] = ('EQUAL' if roi == total == 0 else
                                    'GAIN' if roi >= 0 and total >= 0 else
                                    'REGRESSION' if roi <= 0 and total <= 0 else 'MIXED')
    return values


def verify_timing(off, on, reported):
    require(exact(reported, timing(off, on)), 'timing classification/delta changed')
    return reported


def original_reference(case, current, raw_root=None):
    ref = CONTRACT['original_lru_on_references'][str(case)]
    path = Path(ref['path'])
    require(sha(path) == ref['sha256'], 'original LRU-ON reference receipt changed')
    old = read(path)
    require(old['side'] == 'on' and old['case'] == case, 'original LRU-ON reference identity differs')
    require(exact(old['result'], current['result']), 'complete OFF versus original LRU-ON primary differs')
    root = Path(raw_root).resolve() if raw_root else path.parent
    names = sorted({f'positive.{name}.jsonl' for name in run.TRACE_ENV.values()}
                   | {'positive.window.jsonl.lifetimes.jsonl'})
    require(len(names) == 10, 'original reference raw scope changed')
    raw = {}
    for name in names:
        regular(root / name)
        digest = sha(root / name)
        require(digest == old['artifacts'][name] == current['artifacts'][name],
                'actual original LRU-ON raw equality differs: ' + name)
        raw[name] = digest
    return dict(path=str(path), sha256=ref['sha256'], raw_root=str(root), logical_raw_sha256=raw,
                complete_primary_equal=True, all_ten_actual_positive_raw_equal=True,
                historical_PASS_inherited=False, new_DUT_qualification=False)


def measurements(record):
    r = record['result']
    proof = record['proof_trace']
    return dict(ticks=r['ticks'], flush_tail=r['flush_tail'], total=r['ticks'] + r['flush_tail'],
                axi=r['axi'], roi=r['roi'], tail=r['tail'], proof_summary=proof['summary'],
                witnesses=proof['witness_count'], structural_status=proof['status'],
                unknown=len(proof['unknown']), LRU=record['lru_trace']['windows'])


def build(case, off, off_sha, on, on_sha, gate, gate_sha, freeze, freeze_sha,
          compare_original=False, reference_raw_root=None):
    frozen = verify_freeze(freeze, freeze_sha)
    require(type(case) is int and case in CONTRACT['cases'], 'only warm cases 0, 6, 18')
    require(reference_raw_root is None or compare_original, 'reference root requires explicit reference comparison')
    # Reject missing, incomplete or wrong-side warm inputs before expensive
    # read-only parent closure. No report can precede two genuine terminal pins.
    for path, digest, side in ((off, off_sha, 'off'), (on, on_sha, 'on')):
        require(Path(path).is_file(), 'actual warm terminal receipt required')
        regular(path)
        path = Path(path).resolve()
        require(path.name == 'receipt.json' and path.is_file(), 'actual warm terminal receipt required')
        require(sha(path) == digest, 'terminal receipt pin changed')
        identity(read(path), side, case)
    # Full binding and full case19 gain verification are intentionally invoked.
    # Do not replace either with cached labels or skip the positive/negative raws.
    pins = run.check(CONTRACT['pins_path'], CONTRACT['pins_sha256'])
    require(set(pins['models']) == {'off', 'on'}, 'both actual models must be pinned')
    pair.pair_profiles(pins['base']['profiles']['off'], pins['base']['profiles']['on'])
    for side in ('off', 'on'):
        pair.profile(pins['base']['profiles'][side], side)
    gate = str(Path(gate).resolve())
    require(gate == CONTRACT['case19_gate_path'] and gate_sha == CONTRACT['case19_gate_sha256']
            and sha(gate) == gate_sha, 'full case19 followup gate pin changed')
    verified = followup_bridge.verify(gate, pins, CONTRACT['pins_sha256'], case)
    a, ea = one(off, off_sha, 'off', case, gate, gate_sha, verified, pins)
    b, eb = one(on, on_sha, 'on', case, gate, gate_sha, verified, pins)
    require(a['pins_path'] == b['pins_path'] and a['pins_sha256'] == b['pins_sha256'],
            'cross-side complete pins differ')
    x, y = a['result'], b['result']
    require(x['row'][:5] == y['row'][:5] and x['row'][7:] == y['row'][7:],
            'cross-side original guest workload shape differs')
    original = original_reference(case, a, reference_raw_root) if compare_original else None
    result = dict(schema=SCHEMA, status='PASS_FULL_WARM_FOLLOWUP_FUNCTIONAL_PAIR', case=case,
                  functional_status=FUNCTIONAL_STATUS, timing=timing(x, y),
                  pins_path=CONTRACT['pins_path'], pins_sha256=CONTRACT['pins_sha256'],
                  side_evidence={'off': ea, 'on': eb}, actual_case19_followup_gate=verified,
                  same_source_tools_host_pins_models_and_guest=True, focused=b['focused'],
                  original_lru_ON_reference=original, measurements={'off': measurements(a), 'on': measurements(b)},
                  boundary_join='UNKNOWN_NOT_RECONSTRUCTED',
                  translation_proof_witness_required_for_warm_functional_pass=False,
                  new_DUT_execution=False, raw_parsers_reexecuted=False,
                  independent_primary_log_reparsed=True,
                  parser_results_inherited_with_actual_invocation_and_result_digest=True,
                  full_original_oracles_and_actual_trap_negatives=True,
                  analysis_freeze=frozen, analyzer_sha256=sha(__file__))
    # Bind immutable top-level evidence again after all verification reads. All
    # artifacts are retained and indexed; no full raw validator is rerun here.
    for path, digest in ((off, off_sha), (on, on_sha), (gate, gate_sha),
                         (CONTRACT['pins_path'], CONTRACT['pins_sha256'])):
        require(sha(path) == digest, 'terminal/gate/pins changed during verification')
    return result


def verify(path, digest, freeze, freeze_sha):
    regular(path)
    path = Path(path).resolve()
    require(sha(path) == digest, 'warm pair receipt pin changed')
    record = read(path)
    require(record['schema'] == SCHEMA and record['analyzer_sha256'] == sha(__file__),
            'warm pair schema/analyzer changed')
    e = record['side_evidence']
    g = record['actual_case19_followup_gate']
    ref = record['original_lru_ON_reference']
    actual = build(record['case'], e['off']['path'], e['off']['sha256'],
                   e['on']['path'], e['on']['sha256'], g['path'], g['sha256'],
                   freeze, freeze_sha, ref is not None, None if ref is None else ref['raw_root'])
    require(exact(record, actual), 'closed warm pair inputs/results changed')
    return record


def write_fresh(path, result):
    path = Path(path).resolve()
    require(path.is_relative_to(HERE) and path.parent.is_dir(), 'output must be fresh in analysis namespace')
    with path.open('x') as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.write('\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    for action in ('close', 'verify', 'check-contract', 'check-gate'):
        q = sub.add_parser(action)
        q.add_argument('--freeze', default=str(HERE / 'FREEZE.json'))
        q.add_argument('--freeze-sha', required=True)
        if action == 'close':
            q.add_argument('--case', type=int, choices=CONTRACT['cases'], required=True)
            for name in ('off', 'off-sha', 'on', 'on-sha', 'gate', 'gate-sha', 'out'):
                q.add_argument('--' + name, required=True)
            q.add_argument('--compare-original-lru-on', action='store_true')
            q.add_argument('--reference-raw-root')
        elif action == 'check-gate':
            q.add_argument('--out', required=True)
        elif action == 'verify':
            q.add_argument('--receipt', required=True)
            q.add_argument('--sha256', required=True)
    a = p.parse_args()
    if a.action == 'close':
        r = build(a.case, a.off, a.off_sha, a.on, a.on_sha, a.gate, a.gate_sha,
                  a.freeze, a.freeze_sha, a.compare_original_lru_on, a.reference_raw_root)
        write_fresh(a.out, r)
        print(json.dumps(dict(status=r['status'], case=r['case'], timing=r['timing'],
                              path=str(Path(a.out).resolve()), sha256=sha(a.out)), indent=2))
    elif a.action == 'verify':
        r = verify(a.receipt, a.sha256, a.freeze, a.freeze_sha)
        print(json.dumps(dict(status=r['status'], case=r['case'], timing=r['timing'],
                              path=str(Path(a.receipt).resolve()), sha256=a.sha256), indent=2))
    elif a.action == 'check-gate':
        f = verify_freeze(a.freeze, a.freeze_sha)
        pins = run.check(CONTRACT['pins_path'], CONTRACT['pins_sha256'])
        gate = CONTRACT['case19_gate_path']
        require(sha(gate) == CONTRACT['case19_gate_sha256'], 'full case19 followup gate pin changed')
        g = followup_bridge.verify(gate, pins, CONTRACT['pins_sha256'], 0)
        check_followup_record({'followup_bridge': g}, g, gate, CONTRACT['case19_gate_sha256'])
        r = dict(schema='posted-preparation-priority-warm-analysis-readiness-v1',
                 status='PASS_FULL_CASE19_GATE_ONLY_WARM_PAIRS_PENDING',
                 actual_case19_followup_gate=g, analysis_freeze=f,
                 pins_sha256=CONTRACT['pins_sha256'], analyzer_sha256=sha(__file__),
                 actual_warm_pairs_qualified=0, new_DUT_execution=False, raw_parsers_reexecuted=False)
        write_fresh(a.out, r)
        print(json.dumps(dict(status=r['status'], path=str(Path(a.out).resolve()), sha256=sha(a.out)), indent=2))
    else:
        f = verify_freeze(a.freeze, a.freeze_sha)
        require(sha(CONTRACT['pins_path']) == CONTRACT['pins_sha256'], 'prepared runtime pins changed')
        require(sha(CONTRACT['focused_path']) == CONTRACT['focused_sha256'], 'prepared focused aggregate changed')
        print(json.dumps(dict(status='PASS_ANALYSIS_FREEZE_ONLY_NOT_DUT_QUALIFICATION',
                              analysis_freeze=f, actual_warm_pairs='NOT_CHECKED',
                              new_DUT_execution=False, raw_parsers_reexecuted=False), indent=2))


if __name__ == '__main__':
    main()
