#!/usr/bin/env python3
"""Bounded unchanged CPU/coherent-copy-DMA and S-mode/MPRV data-PMP checks.

Explicit completed history-ON/older-prefix-OFF and history-ON/prefix-ON receipts.
No profile rewriting, model generation, installation, reference build or NEMU.
--prepare reads/validates only; --execute builds guests/harnesses after admission;
--audit verifies terminal evidence without rebuilding or simulating.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.dont_write_bytecode = True
import binding as b
SCHEMA = 'valence-fetch-prefix-dma-pmp-qualification-v1'
PASS = 'PASS_FETCH_HISTORY_PREFIX_DMA_AND_DATA_PMP_OFF_ON'
LIMITS = [
    'Unchanged independent guest, driver, expected data and ownership/load/store/backing oracles.',
    'CPU executes coherent MemoryCopyDma MMIO, two dirty source/destination generations, scratch LD/SD while busy, denied AXI R error/drain/restart.',
    'Data PMP checks denied S-mode and M-mode MPRV=S reads with exact PC/cause/tval, forbidden physical requests, backing and owner drain.',
    'All CPU requests are executed instructions; no runtime injected CPU request stream.',
    'Four DMA and three PMP observer-only negatives per model are required; denied AXI R is real positive-path protocol error injection.',
    'Only older-prefix retirement differs. Fetch previous-packet, physical ingress, LSU4 and copy DMA line4/yield0 are fixed.',
    'No NEMU/full-ISA, denied stores/AMOs, arbitrary PMP/privilege schedule, packet DMA/MAC/CDC, Linux, FPGA timing/resources or physical board qualification.',
    'Cycles and occupancy are observations, not performance acceptance or speedup claims.',
    'Existing terminal RV64GC model smoke is provenance, not a new RV64GC run.',
]
ENV_KEYS = ('PATH', 'CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH', 'LIBRARY_PATH', 'LD_LIBRARY_PATH',
            'COMPILER_PATH', 'GCC_EXEC_PREFIX', 'RISCV_PREFIX', 'ASAN_OPTIONS', 'UBSAN_OPTIONS', 'PYTHONOPTIMIZE')
OVERRIDES = {'ASAN_OPTIONS': 'detect_leaks=0', 'UBSAN_OPTIONS': 'halt_on_error=1',
             'PYTHONDONTWRITEBYTECODE': '1', 'LC_ALL': 'C', 'SOURCE_DATE_EPOCH': '0'}


def contracts(out, guests, cxx, models, fresh):
    allowed = {}
    def add(name, command, products=(), expected=0, anchor=None):
        allowed[name] = {'command': list(map(str, command)), 'products': list(products),
                         'expected_exit': expected, 'anchor': anchor}
    if fresh:
        add('guest-build', [sys.executable, b.HERE / 'build_guests.py', '--out', guests],
            ['guests/manifest.json'], anchor=b.GUEST_PASS)
    for side, (_, model, objects) in models.items():
        for case in b.CASES:
            name = side + '-' + case
            binary = out / name
            add(name + '-link', b.link_command(case, cxx, model, objects, binary, guests), [name])
            argv = [binary, guests / case / 'guest.bin']
            if case == 'dma':
                argv += [guests / case / 'symbols.txt']
            add(name + '-run', argv, anchor=b.ANCHORS[case])
            for mode, anchor in b.NEGATIVES[case]:
                add(name + '-negative-' + mode, [*argv, '--inject-' + mode], expected=1, anchor=anchor)
    return allowed


def audit(out, state, allowed, guests, paths, versions, terminal=False):
    b.require(state.get('schema') == SCHEMA and b.exact(state.get('limitations'), LIMITS), 'result schema/scope drift')
    b.require(set(state.get('steps', {})) <= set(allowed), 'unexpected execution step')
    products, logs = {}, {}
    for name, step in state['steps'].items():
        contract = allowed[name]
        b.require(all(b.exact(step.get(k), contract[k]) for k in ('command', 'expected_exit', 'anchor')) and
                  type(step.get('actual_exit')) is int and step['actual_exit'] == contract['expected_exit'] and
                  step.get('status') == 'PASS' and step.get('cwd') == str(b.ROOT),
                  'execution command/exit/anchor/cwd drift: ' + name)
        b.require(set(step.get('artifacts', {})) == set(contract['products']), 'execution artifact set drift')
        for relative, digest in step['artifacts'].items():
            b.require(b.sha(b.contained(out, relative)) == digest, 'execution product drift: ' + relative)
            products[relative] = digest
        b.require(step.get('log') == name + '.log', 'execution log path drift')
        log = b.contained(out, step['log'])
        b.require(b.sha(log) == step.get('log_sha256'), 'execution log drift: ' + name)
        logs[name] = log.read_text()
        b.clean_log(logs[name], contract['anchor'], bool(contract['expected_exit']))
    if guests.exists():
        manifest = b.guest_audit(guests, paths, versions)
        b.require(b.exact(state.get('guest_manifest'), manifest), 'guest manifest/result disagreement')
        b.require(state.get('guest_manifest_sha256') == b.sha(guests / 'manifest.json'), 'guest manifest drift')
    else:
        b.require(not state.get('guest_manifest'), 'missing bound guest input')
    expected_cases = {side + '-' + case for side in ('off', 'on') for case in b.CASES}
    expected_negatives = {name + '-negative-' + mode for name in expected_cases
                         for mode, _ in b.NEGATIVES[name.split('-', 1)[1]]}
    b.require(set(state['cases']) <= expected_cases and set(state['negatives']) <= expected_negatives,
              'case/negative inventory drift')
    for name, result in state['cases'].items():
        case = name.split('-', 1)[1]
        b.require(name + '-link' in logs and name + '-run' in logs, 'case lacks fresh link/run')
        expected = {'metrics': b.metrics(case, logs[name + '-run']), 'status': 'PASS',
                    'guest_sha256': b.sha(guests / case / 'guest.bin'), 'binary_sha256': b.sha(out / name)}
        b.require(b.exact(result, expected), 'case/log disagreement: ' + name)
    for name, record in state['negatives'].items():
        b.require(name in logs and b.exact(record, {'status': 'REJECTED', 'expected_exit': 1,
                  'anchor': allowed[name]['anchor']}), 'negative/log disagreement')
    b.require(b.exact(products, state['artifacts']), 'complete result artifact inventory drift')
    if terminal:
        b.require(set(state['steps']) == set(allowed) and set(state['cases']) == expected_cases and
                  set(state['negatives']) == expected_negatives, 'incomplete terminal evidence')
        comparison = b.pmp.compare_results({side: state['cases'][side + '-pmp']['metrics'] for side in ('off', 'on')})
        b.require(b.exact(state.get('pmp_architectural_ab'), comparison), 'data-PMP A/B result drift')
        for case in b.CASES:
            b.require(state['cases']['off-' + case]['guest_sha256'] == state['cases']['on-' + case]['guest_sha256'],
                      'A/B guest bytes differ')
        expected_files = set(products) | {'receipt.json'} | {step['log'] for step in state['steps'].values()}
        if guests.is_relative_to(out):
            expected_files |= {p.relative_to(out).as_posix() for p in guests.rglob('*') if p.is_file()}
        actual = set()
        for path in out.rglob('*'):
            b.require(not path.is_symlink(), 'result symlink')
            if path.is_file():
                actual.add(path.relative_to(out).as_posix())
        b.require(actual == expected_files, 'complete result file inventory drift')


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in ('prepare', 'execute', 'audit'):
        mode.add_argument('--' + name, action='store_true')
    parser.add_argument('--off-receipt', required=True, type=Path)
    parser.add_argument('--on-receipt', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--guests', type=Path, help='Explicit portable bundle; otherwise build fresh once at execution')
    parser.add_argument('--cxx', default=os.environ.get('GSIM_CXX', 'clang++-19'))
    args = parser.parse_args()
    b.require(__debug__, 'optimized Python unsupported')
    source_binding = b.v.production_anchor(b.ROOT, b.PRODUCTION, b.HOST, b.TREE)
    cxx, compiler, paths, versions = b.toolchain(args.cxx)
    receipts = {'off': args.off_receipt.resolve(), 'on': args.on_receipt.resolve()}
    models, historical = b.model_pair(receipts, compiler)
    b.include_guard(models)
    out = args.out.resolve()
    b.require(out.is_relative_to(b.HERE) and out != b.HERE, 'output must be inside this isolated fixture')
    fresh = args.guests is None
    guests = (out / 'guests') if fresh else args.guests.resolve()
    b.require(guests != out and not out.is_relative_to(guests), 'guest and result outputs overlap')
    if not fresh:
        b.require(not guests.is_relative_to(out), 'explicit input guest bundle cannot be inside fresh output')
        b.guest_audit(guests, paths, versions)
    frozen = {str(path): b.sha(path) for path in [Path(cxx), Path(sys.executable), *paths.values(),
        *(b.HERE / name for name in ('run_fixture.py', 'binding.py', 'build_guests.py', 'source_lock.json'))]}
    environment = {key: os.environ.get(key) for key in ENV_KEYS}
    identity = {'schema': SCHEMA, 'limitations': LIMITS, 'source_binding': source_binding,
        'source_lock_sha256': b.sha(b.HERE / 'source_lock.json'), 'model_inputs': b.LOCK['model_inputs'],
        'models': {side: {'receipt': str(path), 'sha256': b.sha(path), 'plan': models[side][0]['plan'],
                          'historical_evidence': historical[side]} for side, path in receipts.items()},
        'host_compiler': {'driver': cxx, 'sha256': b.sha(cxx), 'version': compiler},
        'guest_tools': {key: {'path': str(paths[key]), **value} for key, value in versions.items()},
        'guests_path': str(guests), 'fresh_guests': fresh, 'frozen_files': frozen,
        'environment': environment, 'subprocess_overrides': OVERRIDES,
        'model_elaborations': 0, 'generated_model_compiles': 0, 'production_changes': 0}
    allowed = contracts(out, guests, cxx, models, fresh)
    if args.audit:
        state = json.loads((out / 'receipt.json').read_text())
        b.require(all(b.exact(state.get(key), value) for key, value in identity.items()), 'audit input identity drift')
        b.require(state.get('status') == PASS, 'audit requires completed qualification')
    else:
        b.require(not out.exists(), 'fresh output required; use --audit for completed evidence')
        out.mkdir(parents=True)
        state = {**identity, 'status': 'PREPARED_NOT_EXECUTED', 'steps': {}, 'artifacts': {},
                 'cases': {}, 'negatives': {}, 'guest_manifest': None, 'guest_manifest_sha256': None}
        if not fresh:
            state['guest_manifest'] = b.guest_audit(guests, paths, versions)
            state['guest_manifest_sha256'] = b.sha(guests / 'manifest.json')
    def save():
        (out / 'receipt.json').write_text(json.dumps(state, indent=2) + '\n')
    def guard():
        b.require(b.exact(b.preflight_sources(), b.LOCK), 'source lock changed')
        b.require(b.v.production_anchor(b.ROOT, b.PRODUCTION, b.HOST, b.TREE) == source_binding, 'production/host changed')
        b.require({key: os.environ.get(key) for key in ENV_KEYS} == environment, 'compiler/runtime environment changed')
        for path, digest in frozen.items():
            b.require(b.sha(path) == digest, 'frozen tool/runner changed: ' + path)
        checked, evidence = b.model_pair(receipts, compiler)
        b.require(checked == models and evidence == historical, 'model artifacts/history changed')
        b.include_guard(models, guests if guests.exists() else None)
        audit(out, state, allowed, guests, paths, versions)
    def step(name):
        guard()
        contract = allowed[name]
        log = out / (name + '.log')
        print('+', ' '.join(contract['command']), flush=True)
        began = time.monotonic()
        record = {key: contract[key] for key in ('command', 'expected_exit', 'anchor')}
        record.update({'cwd': str(b.ROOT), 'log': log.name, 'status': 'RUNNING'})
        try:
            with log.open('x') as stream:
                code = subprocess.run(contract['command'], cwd=b.ROOT, stdout=stream, stderr=subprocess.STDOUT,
                    timeout=900 if name.endswith('-link') else 300,
                    env={**os.environ, **OVERRIDES}).returncode
            record['actual_exit'] = code
            b.require(code == contract['expected_exit'], name + ' failed:\n' + log.read_text()[-6000:])
            b.clean_log(log.read_text(), contract['anchor'], bool(contract['expected_exit']))
            record['artifacts'] = {product: b.sha(b.contained(out, product)) for product in contract['products']}
            state['artifacts'].update(record['artifacts'])
            if name == 'guest-build':
                state['guest_manifest'] = b.guest_audit(guests, paths, versions)
                state['guest_manifest_sha256'] = b.sha(guests / 'manifest.json')
            record['status'] = 'PASS'
        except BaseException as error:
            record.update({'status': 'FAIL', 'error': str(error)})
            raise
        finally:
            record['seconds'] = time.monotonic() - began
            if log.exists():
                record['log_sha256'] = b.sha(log)
            state['steps'][name] = record
            save()
        guard()
        return log.read_text()
    guard()
    if args.audit:
        audit(out, state, allowed, guests, paths, versions, True)
        print('PASS_REVALIDATED_DMA_PMP_QUALIFICATION execution=0', out / 'receipt.json')
        return
    save()
    if args.prepare:
        print('PASS_SOURCE_MODEL_PROFILE_RECIPE_TOOL_BINDING_ONLY execution=0', out / 'receipt.json')
        return
    state['status'] = 'RUNNING'
    save()
    try:
        if fresh:
            step('guest-build')
        for side in ('off', 'on'):
            for case in b.CASES:
                name = side + '-' + case
                step(name + '-link')
                text = step(name + '-run')
                state['cases'][name] = {'status': 'PASS', 'metrics': b.metrics(case, text),
                    'guest_sha256': b.sha(guests / case / 'guest.bin'), 'binary_sha256': b.sha(out / name)}
                save()
                for mode, anchor in b.NEGATIVES[case]:
                    negative = name + '-negative-' + mode
                    step(negative)
                    state['negatives'][negative] = {'status': 'REJECTED', 'expected_exit': 1, 'anchor': anchor}
                    save()
        state['pmp_architectural_ab'] = b.pmp.compare_results({side: state['cases'][side + '-pmp']['metrics'] for side in ('off', 'on')})
        guard()
        audit(out, state, allowed, guests, paths, versions, True)
        state['status'] = PASS
        save()
    except BaseException as error:
        state.update({'status': 'FAIL', 'error': str(error)})
        save()
        raise
    print(PASS, out / 'receipt.json', flush=True)


if __name__ == '__main__':
    main()
