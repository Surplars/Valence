#!/usr/bin/env python3
"""Direct explicit-model, qualified-guest, cached-NEMU gate; read-only unless --run.

Only harness links and bounded integer simulations are supported. No generator,
model-object compile, reference build, download, install, or old hot receipt.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SCHEMA = 'valence-fetch-prefix-nemu-v1'
PASS = 'PASS_CURRENT_SOURCE_HISTORY_ON_PREFIX_OFF_ON_NEMU'
PRODUCTION = '2288c7f008e9d6440e8a28e339da28152b54892a'
HOST = '7c8b7bb800ed4fa3768c23eee9f608d3192391f2'
TREE = 'c6e69b6b539bc36285b602a39fae32cb76ea012c'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(path):
    import hashlib
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def dependencies(repo):
    require(repo == ROOT, 'runner and --repo must be in the same relocated source tree')
    pins = load(HERE / 'lineage.json')
    require((pins['production_commit'], pins['host_commit'], pins['production_tree']) ==
            (PRODUCTION, HOST, TREE), 'fixture production anchors changed')
    for relative, digest in pins['retained_source_sha256'].items():
        require(sha(repo / relative) == digest, 'retained checker/validator source drift: ' + relative)
    sys.path.insert(0, str(repo / 'simulator/gsim'))
    import run as common
    import fpga_next_board as board
    import build_cpu_hot_bandwidth as guests
    import cpu_hot_bandwidth as hot
    import cpu_retire_prefix_nemu as nemu
    validation = module('fetch_prefix_strict_validation', repo / pins['validator'])
    require(common.ROOT.resolve() == repo and nemu.HERE == repo / 'simulator/gsim', 'imported source root mismatch')
    return pins, common, board, guests, hot, nemu, validation


class Inputs:
    def __init__(self, repo, off, on, guest, reference, compiler):
        self.root = Path(repo).resolve()
        self.pins, self.common, self.board, self.guests, self.hot, self.nemu, self.validation = dependencies(self.root)
        self.files = {}
        self.reference = Path(reference).resolve()
        self.manifest = Path(guest).resolve()
        self.receipts = {'off': Path(off).resolve(), 'on': Path(on).resolve()}
        require(self.receipts['off'] != self.receipts['on'], 'distinct explicit OFF/ON receipts required')
        self.binding = self.validation.production_anchor(self.root, PRODUCTION, HOST, TREE)
        self.board_inputs = self.board.source_inventory()
        for name, digest in self.board_inputs.items():
            self.add(self.root / name, digest)
        for name, digest in self.pins['retained_source_sha256'].items():
            self.add(self.root / name, digest)
        self.fixture_files = {p.name for p in HERE.iterdir() if p.is_file()}
        for name in self.fixture_files:
            self.add(HERE / name)
        driver = shutil.which(str(compiler))
        require(driver, 'existing attested compiler required; no installation supported')
        self.cxx = Path(driver).absolute()  # Preserve clang++ argv[0], not resolved clang.
        require(re.fullmatch(r'clang\+\+(?:-[0-9]+)?', self.cxx.name), 'clang++ driver spelling required')
        self.compiler_target = self.cxx.resolve()
        self.compiler_sha256 = self.pins['compiler']['sha256']
        self.compiler_version = self.pins['compiler']['version']
        self.add(self.cxx, self.compiler_sha256)
        self.models = {}
        for label, receipt in self.receipts.items():
            self.add(receipt, self.pins['model_receipt_sha256'][label])
            state, model, objects = self.validation.validate_model(receipt, self.board_inputs,
                self.compiler_version, self.common.LOCK, older_prefix=label == 'on')
            for relative, digest in state['artifacts'].items():
                self.add(self.validation.contained(receipt.parent, relative), digest)
            for record in state['steps'].values():
                require(record['status'] == 'PASS' and record['actual_exit'] == record['expected_exit'],
                        'model checkpoint step not complete')
                self.add(self.validation.contained(receipt.parent, record['log']), record['log_sha256'])
            self.models[label] = {'model': model, 'objects': objects, 'receipt': receipt, 'state': state}
        self.add(self.manifest, self.pins['guest_manifest_sha256'])
        guest_state, self.cases = self.guests.load_manifest(self.manifest, self.root)
        for item in guest_state['sources'].values():
            self.add(self.guests.contained(self.manifest.parent, item['path']), item['sha256'])
        for case in self.nemu.CASES:
            for name, digest in self.cases[case]['artifacts'].items():
                self.add(self.cases[case]['directory'] / name, digest)
        expected_logs = {case + '/' + step + '.log' for case in self.nemu.CASES
                         for step in ('assemble', 'link', 'binary', 'symbols')}
        records = guest_state['commands']
        require(len(records) == 24 and {x['log'] for x in records} == expected_logs,
                'qualified guest build command inventory mismatch')
        for record in records:
            require(record['exit'] == 0, 'failed qualified guest build command')
            self.add(self.guests.contained(self.manifest.parent, record['log']), record['log_sha256'])
        # Reuse the unchanged audited validators, without the old performance
        # receipt constructor or its old-source/profile assumptions.
        self.nemu.Inputs.validate_checker(self)
        self.nemu.Inputs.validate_reference(self)
        self.scope = {**self.nemu.SCOPE, 'fetch_previous_packet': True,
                      'older_prefix_pair': ['off', 'on'], 'lsu_entries': 4,
                      'physical_load_ingress_flow': True,
                      'performance_comparison_claim': False}
        self.snapshot = {'files': dict(sorted(self.files.items())), 'source_binding': self.binding,
            'model_receipts': {k: str(v) for k, v in self.receipts.items()},
            'guest_manifest': str(self.manifest), 'reference_cache': str(self.reference),
            'compiler': str(self.cxx), 'compiler_resolved': str(self.compiler_target),
            'model_plans': {k: v['state']['plan'] for k, v in self.models.items()}}
        self.guard()

    def add(self, path, expected=None):
        return self.nemu.Inputs.add(self, path, expected)

    def guard(self):
        require(self.validation.production_anchor(self.root, PRODUCTION, HOST, TREE) == self.binding,
                'production/host binding changed')
        require(self.cxx.resolve() == self.compiler_target, 'compiler target changed')
        require(self.board.source_inventory() == self.board_inputs, 'model source inventory changed')
        require({p.name for p in HERE.iterdir() if p.is_file()} == self.fixture_files, 'fixture file inventory changed')
        require({p.name for p in self.nemu.BUNDLE.iterdir() if p.is_file()} == self.checker_inventory,
                'checker file inventory changed')
        source = self.reference / 'nemu-src'
        actual = {p.relative_to(self.reference).as_posix() for p in source.rglob('*')
                  if p.is_file() and not p.is_relative_to(source / 'build')}
        actual |= {'reference-used.json', 'nemu-src/build/riscv64-nemu-interpreter-so'}
        require(actual == self.reference_inventory, 'reference source/config file inventory changed')
        for record in self.models.values():
            model, objects = self.validation.model_files(record['receipt'].parent, record['state']['artifacts'])
            require((model, objects) == (record['model'], record['objects']), 'complete model directory changed')
        for path, digest in self.files.items():
            require(Path(path).is_file() and sha(path) == digest, 'input changed: ' + path)

    def command(self, label, case, out):
        model = self.models[label]
        return [str(self.cxx), *self.nemu.flags(label, case, model['model'], self.cases[case]['directory']),
                '-DFETCH_PREVIOUS_PACKET=1', '-I' + str(self.root / 'simulator/gsim/harness'),
                '-I' + str(self.nemu.BUNDLE), str(out / 'observer.cpp'), *map(str, model['objects']),
                '-ldl', '-o', str(out / label / case / 'run')]

    def negatives(self, label):
        return {**{'nemu-' + k: v for k, v in self.nemu.NEGATIVES.items()},
                **self.nemu.negative_modes(label)}


def negative_check(text, exit_code, anchor):
    require(exit_code == 1 and anchor in text and 'NEMU_PASS' not in text and 'HOT_PASS' not in text,
            'negative did not fail at its required checker')


def positive(inputs, text, case):
    counters = inputs.nemu.nemu_counters(text)
    measured = inputs.hot.parse(text)
    op, size = case.split('-')
    result, terminal = measured['result'], measured['pass']
    require((result['op'], result['buffer_bytes'], result['reps']) == (op, int(size), 4), 'hot case profile drift')
    require(result['board_measurement'] == 0 and result['negative_oracle_checks'] > 0, 'hot oracle coverage missing')
    require(terminal['terminal_live_owners'] == terminal['terminal_start'] == 0 and
            terminal['complete_owner_drain'] == 1, 'terminal owner drain missing')
    return counters, measured


def audit(inputs, out, state, *, terminal=False):
    inputs.guard()
    require(state['schema'] == SCHEMA and state['inputs'] == inputs.snapshot and state['scope'] == inputs.scope,
            'receipt input/schema/scope drift')
    require(all(state[k] == v for k, v in inputs.nemu.ZERO_COUNTERS.items()), 'forbidden rebuild/resynchronization claim')
    require(state['execution_compiler'] == {'command': [str(inputs.cxx), '--version'],
            'version': inputs.compiler_version, 'sha256': inputs.compiler_sha256}, 'execution compiler drift')
    generated = out / 'observer.cpp'
    require(generated.read_text() == inputs.nemu.instrument((inputs.root / 'simulator/gsim/harness/cpu_retire_prefix_hot.cpp').read_text())
            and sha(generated) == state['generated_observer_sha256'], 'generated observer drift')
    allowed = {}
    for label in inputs.nemu.LABELS:
        for case in inputs.nemu.CASES:
            key = label + '-' + case
            binary = out / label / case / 'run'
            base = [str(binary), str(inputs.cases[case]['directory'] / 'guest.bin'), str(inputs.so)]
            allowed[key + '-link'] = (inputs.command(label, case, out), 0, None, {str(binary.relative_to(out))})
            allowed[key + '-run'] = (base, 0, 'NEMU_PASS', set())
            if case == 'read-4096':
                for mode, anchor in inputs.negatives(label).items():
                    allowed[label + '-negative-' + mode] = ([*base, '--inject-' + mode], 1, anchor, set())
    require(set(state['steps']) <= set(allowed), 'unexpected receipt step')
    for name, record in state['steps'].items():
        command, expected, anchor, products = allowed[name]
        require(record['command'] == command and record['exit'] == expected and set(record['artifacts']) == products,
                'step command/exit/product inventory drift: ' + name)
        log = inputs.validation.contained(out, record['log'])
        require(sha(log) == record['log_sha256'], 'step log drift: ' + name)
        text = log.read_text()
        for path, digest in record['artifacts'].items():
            require(sha(inputs.validation.contained(out, path)) == digest, 'step artifact drift: ' + name)
        if expected:
            negative_check(text, expected, anchor)
        elif anchor:
            require(anchor in text, 'positive anchor missing')
    require(set(state['cases']) == {n[:-4] for n in state['steps'] if n.endswith('-run')}, 'case/step inventory drift')
    for key, record in state['cases'].items():
        label, case = key.split('-', 1)
        text = (out / state['steps'][key + '-run']['log']).read_text()
        counters, hot = positive(inputs, text, case)
        require(record == {'nemu': counters, 'hot': hot,
                'binary_sha256': sha(out / label / case / 'run'),
                'guest_sha256': sha(inputs.cases[case]['directory'] / 'guest.bin')}, 'case receipt/log drift')
    if terminal:
        require(state['status'] == PASS and set(state['steps']) == set(allowed), 'incomplete terminal proof')
        inputs.nemu.compare_pairs(state['cases'])


def run(inputs, out, *, resume=False, variant=None, case=None):
    print('Execution: 12 serial harness links, 12 positive runs, 26 negative runs maximum; 300-second per-step limit.', flush=True)
    print('Tools: attested clang++19 + cached model objects + cached pinned NEMU; no generator or reference build.', flush=True)
    print('Estimate: 3–8 minutes, 150–300 MB outputs; integer physical M-mode, DMA idle; no performance claim.', flush=True)
    compiler_check = inputs.nemu.verify_execution_compiler(inputs)
    out = Path(out).resolve()
    require(not out.is_relative_to(HERE), 'execution output must be separate from frozen source fixture')
    require(not out.exists() or resume, 'fresh output required, or use --resume')
    require(not resume or (out / 'receipt.json').is_file(), 'resume receipt missing')
    out.mkdir(parents=True, exist_ok=True)
    receipt = out / 'receipt.json'
    generated = out / 'observer.cpp'
    contents = inputs.nemu.instrument((inputs.root / 'simulator/gsim/harness/cpu_retire_prefix_hot.cpp').read_text())
    if resume:
        state = load(receipt)
        audit(inputs, out, state)
    else:
        generated.write_text(contents)
        state = {'schema': SCHEMA, 'status': 'PREPARED', 'inputs': inputs.snapshot,
                 'scope': inputs.scope, 'reference': inputs.used,
                 'execution_compiler': compiler_check, 'generated_observer_sha256': sha(generated),
                 **inputs.nemu.ZERO_COUNTERS, 'steps': {}, 'cases': {}}
    def save():
        temporary = receipt.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(state, indent=2) + '\n')
        temporary.replace(receipt)
    def step(name, command, expected=0, anchor=None, products=()):
        audit(inputs, out, state)
        if name in state['steps']:
            return (out / state['steps'][name]['log']).read_text()
        path = out / (name + '.log')
        retry = 0
        while path.exists():
            retry += 1
            path = out / (name + '.retry' + str(retry) + '.log')
        print('+', ' '.join(map(str, command)), flush=True)
        start = time.monotonic()
        with path.open('x') as stream:
            result = subprocess.run(list(map(str, command)), cwd=inputs.root, stdout=stream,
                stderr=subprocess.STDOUT, timeout=300, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        text = path.read_text()
        record = {'command': list(map(str, command)), 'exit': result.returncode,
                  'seconds': time.monotonic() - start, 'log': path.name, 'log_sha256': sha(path),
                  'artifacts': {str(p.relative_to(out)): sha(p) for p in products if p.is_file()}}
        if result.returncode != expected or (anchor and anchor not in text) or len(record['artifacts']) != len(products):
            state.setdefault('failed_steps', []).append(record)
            save()
            raise RuntimeError(name + ' failed:\n' + text[-6000:])
        if expected:
            negative_check(text, result.returncode, anchor)
        inputs.guard()
        state['steps'][name] = record
        # A positive run and its parsed case must be saved atomically by caller.
        if not name.endswith('-run'):
            save()
        return text
    try:
        state['status'] = 'RUNNING'; state.pop('error', None); save()
        for label in inputs.nemu.LABELS:
            if variant and label != variant:
                continue
            for name in inputs.nemu.CASES:
                if case and name != case:
                    continue
                key = label + '-' + name
                binary = out / label / name / 'run'
                binary.parent.mkdir(parents=True, exist_ok=True)
                step(key + '-link', inputs.command(label, name, out), products=(binary,))
                base = [str(binary), str(inputs.cases[name]['directory'] / 'guest.bin'), str(inputs.so)]
                text = step(key + '-run', base, anchor='NEMU_PASS')
                counters, hot = positive(inputs, text, name)
                state['cases'][key] = {'nemu': counters, 'hot': hot, 'binary_sha256': sha(binary),
                                      'guest_sha256': sha(inputs.cases[name]['directory'] / 'guest.bin')}
                save(); print(key, inputs.nemu.line(text, 'NEMU_PASS'), flush=True)
                if name == 'read-4096':
                    for mode, anchor in inputs.negatives(label).items():
                        step(label + '-negative-' + mode, [*base, '--inject-' + mode], expected=1, anchor=anchor)
        expected = 24 + sum(len(inputs.negatives(label)) for label in inputs.nemu.LABELS)
        state['status'] = PASS if len(state['cases']) == 12 and len(state['steps']) == expected else 'PARTIAL_PASS'
        audit(inputs, out, state, terminal=state['status'] == PASS)
        save()
    except BaseException as error:
        state['status'] = 'FAIL'; state['error'] = str(error); save(); raise
    print(state['status'], receipt, flush=True)
    return state


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, default=ROOT)
    p.add_argument('--off-receipt', required=True, type=Path)
    p.add_argument('--on-receipt', required=True, type=Path)
    p.add_argument('--guest-manifest', required=True, type=Path)
    p.add_argument('--reference-cache', required=True, type=Path)
    p.add_argument('--compiler', default=os.environ.get('GSIM_CXX', 'clang++-19'))
    p.add_argument('--out', type=Path)
    p.add_argument('--run', action='store_true')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--audit', action='store_true')
    p.add_argument('--variant', choices=('off', 'on'))
    p.add_argument('--case', choices=tuple(f'{op}-{size}' for size in (4096, 8192) for op in ('read', 'write', 'copy')))
    a = p.parse_args(argv)
    require(not (a.run and a.audit), '--run and --audit are mutually exclusive')
    require(not (a.run or a.audit) or a.out, '--run/--audit requires --out')
    require(not a.resume or a.run, '--resume requires --run')
    print('Preflight: source/model/guest/checker/NEMU-cache hashes only; compiler/model/reference execution=0.', flush=True)
    inputs = Inputs(a.repo, a.off_receipt, a.on_receipt, a.guest_manifest, a.reference_cache, a.compiler)
    if a.audit:
        audit(inputs, a.out.resolve(), load(a.out / 'receipt.json'), terminal=True)
        print('PASS_TERMINAL_RECEIPT_AUDIT')
    elif a.run:
        run(inputs, a.out, resume=a.resume, variant=a.variant, case=a.case)
    else:
        print(json.dumps({'status': 'PASS_INPUT_PREFLIGHT_ONLY', 'input_files': len(inputs.files),
            'positive_cases': 12, 'negative_cases': 26, 'scope': inputs.scope,
            'simulation_run': False, 'compiler_invoked': False, 'output_estimate_mb': [150, 300],
            'execution_estimate_minutes': [3, 8]}, indent=2))


if __name__ == '__main__':
    main()
