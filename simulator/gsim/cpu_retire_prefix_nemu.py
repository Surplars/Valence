#!/usr/bin/env python3
"""Replay the qualified current older-prefix OFF/ON hot pair with the unchanged independent NEMU architecture checker.

Validation is read-only. --run explicitly enables serial harness-only links and
short simulations; no model generator, model compiler, reference build or install
is called. Every input is supplied or reached through the supplied flow receipt.
"""
import argparse
import hashlib
import importlib
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
BUNDLE = HERE / 'harness/board_hot_nemu'
SCHEMA = 'valence-older-prefix-board-hot-nemu-v1'
PASS = 'PASS_SOURCE_MATCHED_OLDER_PREFIX_BOARD_HOT_NEMU'
CASES = tuple(f'{op}-{size}' for size in (4096, 8192) for op in ('read', 'write', 'copy'))
LABELS = ('off', 'on')
SHARED = {'dma_line_transfers': True, 'dma_line_entries': 4, 'dma_line_yield_cycles': 0}
NEGATIVES = {'pc': 'NEMU PC mismatch', 'gpr': 'NEMU GPR mismatch', 'memory': 'NEMU memory mismatch'}
FLOW_NEGATIVES = {
    'physical-fingerprint': 'physical request fingerprint corruption',
    'route': 'physical ingress route prediction mismatch',
    'virtual-enqueue': 'raw virtual enqueue route mismatch',
    'checked-enqueue': 'raw checked enqueue route mismatch',
    'authorization': 'independent checked payload/permission mismatch',
    'private-metadata': 'physical authorization metadata mismatch',
    'return-token': 'backend return full-token lineage corruption',
    'reserve-guard': 'test-only capacity guard differs from production'}
SCOPE = {
    'dma': 'CONFIGURED BUT IDLE', 'dma_line_entries': 4, 'dma_line_yield_cycles': 0,
    'concurrent_dma_nemu_claim': False,
    'pc_boundary': 'Every retired guest instruction individually before one independent NEMU step.',
    'gpr_boundary': 'All 32 GPRs after each entire retirement edge, including dual-lane edges.',
    'memory': 'Every byte of [0x80200000, 0x80600040), including code and zero gaps, after fences and DDR write drain.',
    'initialization': 'Independently specified ROM effects and RAM seeds; never DUT-derived state.',
    'limits': ['Integer physical M-mode guests only; no CSR/FP/VM architectural coverage.',
               'Fixed ROM PCs and integer effects checked independently; UART MMIO store not executed in NEMU.',
               'No intermediate per-lane GPR snapshot on dual-retire edges.',
               'No concurrent CPU/DMA NEMU, real board, Linux, Vivado, routed timing or full regression claim.']}
ZERO_COUNTERS = {'model_rebuilds': 0, 'model_object_compiles': 0, 'rtl_changes': 0,
                 'reference_rebuilds': 0, 'reference_resynchronizations': 0}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def contained(base, relative):
    part = Path(relative)
    require(not part.is_absolute() and '..' not in part.parts, 'unsafe relative path: ' + str(part))
    result = (base / part).resolve()
    require(result.is_relative_to(base.resolve()), 'path escapes base: ' + str(part))
    return result


def line(text, prefix):
    matches = [item for item in text.splitlines() if item.startswith(prefix + ' ')]
    require(len(matches) == 1, 'missing/duplicate ' + prefix)
    return matches[0]


def nemu_counters(text):
    fields = line(text, 'NEMU_PASS').split()[1:]
    require(all(item.count('=') == 1 for item in fields), 'malformed NEMU counter')
    result = dict(item.split('=', 1) for item in fields)
    expected = {'guest_pc_checks', 'boot_pc_checks', 'guest_retire_edges', 'dual_retire_edges',
                'guest_gpr_edges', 'boot_gpr_edges', 'gpr_value_checks', 'final_memory_bytes',
                'guest_pc_trace', 'reference_resynchronizations', 'gpr_boundary',
                'independent_lane_intermediate_gpr', 'speculative_requests_stepped'}
    require(len(result) == len(fields) and set(result) == expected, 'NEMU counter inventory drift')
    for key in expected - {'gpr_boundary'}:
        require(re.fullmatch('[0-9]+', result[key]) is not None, 'invalid NEMU counter: ' + key)
    n = {key: int(value) for key, value in result.items() if key != 'gpr_boundary'}
    require(n['reference_resynchronizations'] == n['speculative_requests_stepped'] == 0, 'reference resynchronization/speculative step')
    require(result['gpr_boundary'] == 'post_entire_retire_edge' and n['independent_lane_intermediate_gpr'] == 0,
            'unsupported GPR observation boundary')
    require(n['guest_pc_checks'] > 0 and n['guest_gpr_edges'] == n['guest_retire_edges'] > 0, 'guest GPR coverage gap')
    require(0 <= n['dual_retire_edges'] <= n['guest_retire_edges'], 'invalid dual-retire edge count')
    require(n['guest_pc_checks'] == n['guest_retire_edges'] + n['dual_retire_edges'], 'instruction PC coverage gap')
    require(n['boot_pc_checks'] == 5 and 3 <= n['boot_gpr_edges'] <= 5, 'boot coverage gap')
    require(n['gpr_value_checks'] == 32 * (n['guest_gpr_edges'] + n['boot_gpr_edges']), 'not all 32 GPRs checked')
    require(n['final_memory_bytes'] == 0x400040, 'incomplete final RAM coverage')
    line(text, 'HOT_PASS')
    return result



def negative_modes(label):
    result = dict(FLOW_NEGATIVES)
    if label in LABELS:
        result.update({'upper-live': 'slot live owner appeared or was prematurely released',
                       'upper-token': 'slot full-token generation or position changed'})
    return result


def instrument(source):
    def replace(old, new):
        nonlocal source
        require(source.count(old) == 1, 'NEMU instrumentation anchor drift: ' + old[:70])
        source = source.replace(old, new)
    replace('#include <limits>', '#include <limits>\n#include "board_nemu_observer.h"')
    replace('struct Observer {\n    Test *test=nullptr;', 'struct Observer {\n    board_nemu::Observer nemu;\n    Test *test=nullptr;')
    replace('    void sample(SBoardSocGsim &d) {', '    void sample(SBoardSocGsim &d) {\n        nemu.sample(d);')
    replace('check(argc==2||argc==3,"usage: cpu_flow_bandwidth guest.bin [--inject-physical-fingerprint]");',
            'check(argc==3||argc==4,"usage: cpu_flow_bandwidth guest.bin nemu.so [--inject-nemu-{pc,gpr,memory}]");')
    replace('    if(argc==3) {\n        injection=argv[2];', '    if(argc==4) {\n        injection=argv[3];')
    replace('const std::array<std::string,10> modes', 'const std::array<std::string,13> modes')
    replace('"--inject-upper-live","--inject-upper-token","--inject-reserve-guard"};',
            '"--inject-upper-live","--inject-upper-token","--inject-reserve-guard",\n            "--inject-nemu-pc","--inject-nemu-gpr","--inject-nemu-memory"};')
    replace('    check(!image.empty()&&image.size()<0x10000,"guest image bounds");',
            '    check(!image.empty()&&image.size()<0x10000,"guest image bounds");\n    observer.nemu.initialize(image,argv[2],injection);')
    replace('    observer.verify();observer.report();return 0;',
            '    // Apply the final observed retirement edge, as in the historical independent checker.\n    test.tick();\n    observer.nemu.verifyMemory(test);\n    observer.verify();observer.report();observer.nemu.report();return 0;')
    return source


def audit(path, inputs):
    """Rehash and independently reparse every terminal proof before accepting it."""
    inputs.guard()
    state = load(path); out = Path(path).parent
    require(state['status'] == PASS and state['inputs'] == inputs.snapshot, 'terminal input/status mismatch')
    require(state.get('execution_compiler') == {'command': [str(inputs.cxx), '--version'],
            'version': inputs.compiler_version, 'sha256': inputs.compiler_sha256}, 'terminal compiler check drift')
    require(state['scope'] == SCOPE and all(state[k] == v for k,v in ZERO_COUNTERS.items()), 'terminal scope drift')
    generated = out / 'observer.cpp'
    require(sha(generated) == state['generated_observer_sha256'] and
            generated.read_text() == instrument((HERE/'harness/cpu_retire_prefix_hot.cpp').read_text()), 'instrumentation drift')
    expected_steps = set()
    for label in LABELS:
        for case in CASES:
            key = label + '-' + case
            for kind in ('link', 'run'): expected_steps.add(key + '-' + kind)
            record = state['cases'][key]
            binary = out / label / case / 'run'
            require(record['binary_sha256'] == sha(binary), 'executable drift')
            require(state['steps'][key+'-link']['command'] == inputs.command(label,case,out), 'link command drift')
            require(state['steps'][key+'-run']['command'] == [str(binary),str(inputs.cases[case]['directory']/'guest.bin'),str(inputs.so)], 'run command drift')
            text = contained(out,state['steps'][key+'-run']['log']).read_text()
            require(nemu_counters(text) == record['nemu'], 'NEMU receipt/log drift')
            require(line(text,'HOT_RESULT') == inputs.original_results[key], 'hot result changed')
            require(record['guest_sha256'] == sha(inputs.cases[case]['directory']/'guest.bin'), 'guest drift')
        for mode, anchor in NEGATIVES.items():
            name = label+'-negative-nemu-'+mode; expected_steps.add(name)
            text=contained(out,state['steps'][name]['log']).read_text()
            require(state['steps'][name]['exit']==1 and anchor in text and 'NEMU_PASS' not in text, 'negative did not reject')
            require(state['steps'][name]['command']==[str(out/label/'read-4096/run'),str(inputs.cases['read-4096']['directory']/'guest.bin'),str(inputs.so),'--inject-nemu-'+mode], 'negative command drift')
    require(set(state['steps']) == expected_steps, 'terminal step inventory drift')
    for name,record in state['steps'].items():
        require(sha(contained(out,record['log'])) == record['log_sha256'], 'log drift')
        for file,digest in record['artifacts'].items(): require(sha(contained(out,file)) == digest, 'product drift')
        require(record['exit'] == (1 if '-negative-' in name else 0), 'step exit drift')
    compare_pairs(state['cases'])
    totals={key:sum(int(case['nemu'][key]) for case in state['cases'].values()) for key in
            ('guest_pc_checks','guest_gpr_edges','dual_retire_edges','gpr_value_checks','final_memory_bytes')}
    (out/'verified-summary.json').write_text(json.dumps({'status':PASS,'receipt_sha256':sha(path),'cases':12,'negative_controls':6,'totals':totals,'scope':SCOPE},indent=2)+'\n')


def flags(label, case, model, guest):
    op, size = case.split('-')
    return ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
            '-DBACKEND_OWNER_COUNT=4', '-DUART_DIVISOR=1', '-DBOARD_CPU_HZ=100000000', '-DBOARD_UART_BAUD=460800', '-DUART_EXTRA_STOP_BITS=0',
            '-DDDR_MODEL=1', '-DBOARD_DDR_BYTES=2147483648ULL', '-DDDR_MULTI_ID_MODEL=1', '-DDDR_BENCHMARK_MODEL=1',
            '-DDDR_READ_CREDITS=8', '-DDDR_READ_LATENCY=32', '-DDDR_READ_BEAT_GAP=1', '-DBOARD_CYCLE_LIMIT=300000ULL',
            '-DHOT_BYTES=' + size, '-DHOT_REPS=4', '-DHOT_SB_ENTRIES=2',
            '-DHOT_OP=' + str({'read': 0, 'write': 1, 'copy': 2}[op]),
            '-DPHYSICAL_INGRESS_FLOW=1', '-I' + str(model), '-I' + str(guest)]


class Inputs:
    def __init__(self, root, flow_receipt, reference_cache, *, recorded_root=None, compiler=None):
        self.root = Path(root).resolve()
        self.flow_path = Path(flow_receipt).resolve()
        self.reference = Path(reference_cache).resolve()
        self.recorded_root = Path(recorded_root).resolve() if recorded_root else self.root
        self.compiler_override = Path(compiler).absolute() if compiler else None
        self.files = {}
        sys.path.insert(0, str(self.root / 'simulator/gsim'))
        self.flow = importlib.import_module('cpu_retire_prefix_board')
        self.guests = self.flow.guests
        self.board = self.flow.board
        require(self.flow.common.ROOT.resolve() == self.root, 'imported flow runner belongs to a different source root')
        self.validate()

    def resolve(self, recorded):
        path = Path(recorded)
        if path.is_absolute():
            require(path.is_relative_to(self.recorded_root), 'recorded input outside source root: ' + str(path))
            return contained(self.root, path.relative_to(self.recorded_root))
        return contained(self.root, path)

    def add(self, path, expected=None):
        path = Path(path).resolve()
        require(path.is_file(), 'missing input: ' + str(path))
        digest = sha(path)
        require(expected is None or digest == expected, 'input hash mismatch: ' + str(path))
        require(str(path) not in self.files or self.files[str(path)] == digest, 'conflicting input hash: ' + str(path))
        self.files[str(path)] = digest
        return digest

    def input_map(self, mapping):
        for relative, digest in mapping.items():
            self.add(contained(self.root, relative), digest)

    def step(self, directory, record, *, expected=0, anchor=None, model=False):
        require(record.get('actual_exit' if model else 'exit') == expected, 'upstream step exit mismatch')
        if model:
            require(record.get('status') == 'PASS' and record.get('expected_exit') == expected, 'incomplete model step')
        log = contained(directory, record['log'])
        self.add(log, record['log_sha256'])
        text = log.read_text()
        require(not anchor or anchor in text, 'upstream step missing anchor: ' + str(log))
        for path, digest in record.get('artifacts', {}).items():
            self.add(self.resolve(path), digest)
        return text

    def normalized_command(self, command):
        # Only compare original commands; never execute commands copied from receipts.
        result = []
        for index, token in enumerate(command):
            if index == 0:
                result.append(str(self.cxx))
            elif token.startswith('-I'):
                result.append('-I' + str(self.resolve(token[2:])))
            elif token.startswith('/'):
                result.append(str(self.resolve(token)))
            else:
                result.append(token)
        return result

    def validate(self):
        self.add(self.flow_path)
        state = load(self.flow_path)
        require(state.get('schema') == 'valence-cpu-retire-prefix-board-v1' and
                state.get('status') == 'PASS_SOURCE_MATCHED_CPU_OLDER_PREFIX_BOARD', 'completed source-matched older-prefix OFF/ON hot receipt required')
        require(state.get('inputs') == self.flow.inventory(), 'flow source inventory drift')
        self.input_map(state['inputs'])
        request = state.get('model_request', {})
        require(set(request) == {'shared_options', 'reuse_tag'} and request['shared_options'] == SHARED,
                'explicit integrated depth4/yield0 model profile required')
        reuse_tag = request['reuse_tag']
        require(reuse_tag is None or re.fullmatch('[A-Za-z0-9_-]+', reuse_tag) is not None,
                'invalid model reuse tag')
        guest_input = state.get('guest_input', {})
        require(guest_input.get('kind') == 'fresh_source_build', 'fresh guest manifest required; historical recovery is not accepted')
        manifest = self.resolve(guest_input['path'])
        self.add(manifest, guest_input['sha256'])
        guest_state, self.cases = self.guests.load_manifest(manifest, self.root)
        for record in guest_state['sources'].values():
            self.add(contained(manifest.parent, record['path']), record['sha256'])
        for case in CASES:
            for name, digest in self.cases[case]['artifacts'].items():
                self.add(self.cases[case]['directory'] / name, digest)
        require(len(guest_state.get('commands', [])) == 24, 'incomplete fresh guest build evidence')
        for record in guest_state['commands']:
            require(record.get('exit') == 0, 'failed guest build command')
            self.add(contained(manifest.parent, record['log']), record['log_sha256'])
        host = state['host_compiler']
        self.original_cxx = state['steps']['off-read-4096-link']['command'][0]
        driver = shutil.which(self.original_cxx) if not self.compiler_override else str(self.compiler_override)
        require(driver is not None, 'missing recorded C++ driver; supply exact --compiler')
        # Keep the clang++ driver spelling: resolving its symlink to clang loses
        # C++ argv[0] semantics and automatic libstdc++ linkage. Hash the target.
        self.cxx = self.compiler_override or Path(driver).absolute()
        self.add(self.cxx, host['sha256'])
        self.compiler_target = self.cxx.resolve()
        self.compiler_sha256 = host['sha256']
        if not self.compiler_override:
            require(self.cxx.resolve() == Path(host['path']).resolve(), 'host compiler target mismatch')
        self.compiler_version = state['compiler']
        require(set(state.get('models', {})) == set(LABELS), 'incomplete older-prefix OFF/ON model pair')
        require(set(state.get('cases', {})) == set(LABELS), 'incomplete older-prefix OFF/ON hot cases')
        board_inputs = self.board.source_inventory()
        self.models, self.original_results = {}, {}
        for label in LABELS:
            record = state['models'][label]
            require(record.get('origin') == ('explicit_reuse' if reuse_tag else 'built_for_this_run'),
                    'model origin disagrees with the frozen upstream request')
            path = self.resolve(record['receipt'])
            self.add(path, record['receipt_sha256'])
            model_state, model, objects = self.flow.validate_model(path, 1, board_inputs,
                                                                 state['compiler'], lsu_entries=4, load_order_older_retire=(label == 'on'), **SHARED)
            require(record.get('inputs') == model_state['inputs'] and record.get('plan') == model_state['plan'],
                    'flow/model receipt mismatch')
            self.input_map(model_state['inputs'])
            for relative, digest in model_state['artifacts'].items():
                self.add(contained(path.parent, relative), digest)
            for item in model_state['steps'].values():
                self.step(path.parent, item, expected=item['expected_exit'], model=True)
            if reuse_tag is None:
                # The upstream hot runner may build its exact-source pair before
                # qualifying it. Validate that creation receipt too; this NEMU
                # runner itself still only links already-frozen model objects.
                prefix = 'fpga-next-board-cpu-retire-prefix-' + label + '-'
                require(path.parent.name.startswith(prefix), 'unexpected fresh model directory')
                tag = path.parent.name[len(prefix):]
                require(re.fullmatch('[A-Za-z0-9_-]+', tag) is not None, 'invalid fresh model tag')
                model_step = state['steps'][label + '-model']
                expected_command = ['python3', '-B', str(self.root / 'simulator/gsim/fpga_next_board.py'),
                    '--tag', 'cpu-retire-prefix-' + label + '-' + tag, '--variant', 'selected', '--jobs', '1',
                    '--smoke-only', '--dma-line-transfers', '--dma-line-entries', '4', '--lsu-entries', '4',
                    '--physical-load-ingress-flow']
                if label == 'on':
                    expected_command.append('--load-order-older-retire')
                actual_command = [str(self.resolve(x)) if x.startswith('/') else x for x in model_step['command']]
                require(actual_command in (expected_command, expected_command + ['--resume']),
                        'fresh model build command/profile drift')
                require({self.resolve(p): h for p, h in model_step.get('artifacts', {}).items()} ==
                        {path: record['receipt_sha256']}, 'fresh model receipt artifact drift')
                self.step(self.flow_path.parent, model_step, anchor='PASS_FPGA_NEXT_BOARD_SMOKE')
            else:
                require(path.parent.name == 'fpga-next-board-cpu-retire-prefix-' + label + '-' + reuse_tag,
                        'model path does not match explicit reuse tag')
            self.models[label] = {'model': model, 'objects': objects, 'receipt': path}
            require(set(state['cases'][label]) == set(CASES), 'incomplete hot case set')
            for case in CASES:
                directory = self.cases[case]['directory']
                key = label + '-' + case
                binary = self.flow_path.parent / label / case / 'run'
                link = state['steps'][key + '-link']
                expected = [str(self.cxx), *flags(label, case, model, directory),
                            str(self.root / 'simulator/gsim/harness/cpu_retire_prefix_hot.cpp'),
                            *map(str, objects), '-ldl', '-o', str(binary)]
                require(self.normalized_command(link['command']) == expected, 'hot link configuration drift: ' + key)
                # The original compiler token must resolve to the attested executable unless explicitly remapped.
                original_compiler = Path(link['command'][0])
                require(str(original_compiler) == self.original_cxx, 'hot compiler driver changed across cases')
                if not self.compiler_override:
                    require(Path(shutil.which(str(original_compiler)) or original_compiler).resolve() == self.cxx.resolve(),
                            'unattested hot compiler executable')
                self.step(self.flow_path.parent, link)
                require({self.resolve(p): h for p, h in link.get('artifacts', {}).items()} ==
                        {binary: state['cases'][label][case]['binary_sha256']}, 'hot binary artifact binding drift')
                run = state['steps'][key + '-run']
                require([str(self.resolve(p)) for p in run['command']] == [str(binary), str(directory / 'guest.bin')],
                        'hot run input binding drift')
                require(run.get('artifacts') == {}, 'unexpected hot run artifacts')
                text = self.step(self.flow_path.parent, run, anchor='HOT_PASS')
                require(state['cases'][label][case]['guest_sha256'] == sha(directory / 'guest.bin'), 'hot guest binding drift')
                require(self.flow.parse(text)['result'] == state['cases'][label][case]['result'], 'hot result receipt/log drift')
                self.original_results[key] = line(text, 'HOT_RESULT')
            for mode, anchor in negative_modes(label).items():
                negative = state['steps'][label + '-negative-' + mode]
                expected = [str(self.flow_path.parent / label / 'read-4096/run'),
                            str(self.cases['read-4096']['directory'] / 'guest.bin'), '--inject-' + mode]
                actual = [str(self.resolve(p)) if not p.startswith('--') else p for p in negative['command']]
                require(actual == expected and negative.get('artifacts') == {}, 'hot negative input binding drift')
                text = self.step(self.flow_path.parent, negative, expected=1, anchor=anchor)
                require('HOT_PASS' not in text, 'upstream hot negative unexpectedly passed')
        expected_steps = {f'{label}-{case}-{step}' for label in LABELS for case in CASES for step in ('link', 'run')}
        expected_steps |= {f'{label}-negative-{mode}' for label in LABELS for mode in negative_modes(label)}
        if reuse_tag is None:
            expected_steps |= {label + '-model' for label in LABELS}
        require(set(state['steps']) == expected_steps, 'unexpected/missing fresh flow step set')
        self.state = state
        self.validate_checker()
        self.validate_reference()
        for path in (Path(__file__).resolve(), HERE / 'cpu_flow_board_nemu.py'):
            self.add(path)
        self.snapshot = {'files': dict(sorted(self.files.items())), 'flow_receipt': str(self.flow_path),
                         'reference_cache': str(self.reference), 'source_root': str(self.root),
                         'recorded_root': str(self.recorded_root), 'compiler': str(self.cxx), 'compiler_resolved': str(self.cxx.resolve()),
                         'model_request': request, 'guest_manifest': str(manifest)}

    def validate_checker(self):
        path = BUNDLE / 'checker_provenance.json'
        self.add(path)
        provenance = load(path)
        require(provenance.get('schema') == 'valence-board-hot-nemu-checker-provenance-v1', 'checker provenance schema mismatch')
        expected = set(provenance['checker_files']) | {'checker_provenance.json', 'reference_cache_manifest.json'}
        require({p.name for p in BUNDLE.iterdir() if p.is_file()} == expected, 'checker source inventory drift')
        self.checker_inventory = expected
        # Historical two-owner passive headers are archived but are not compiled.
        # Current four-owner headers are already bound through the qualified hot receipt.
        for name, digest in provenance['checker_files'].items():
            self.add(contained(BUNDLE, name), digest)
        for name in ('board_nemu_observer.h', 'reference.h'):
            require(provenance['checker_files'][name] == provenance['historical_checker_files'][name],
                    'verified NEMU checker was modified')

    def validate_reference(self):
        manifest_path = BUNDLE / 'reference_cache_manifest.json'
        self.add(manifest_path)
        manifest = load(manifest_path)
        require(manifest.get('schema') == 'valence-board-hot-nemu-reference-cache-v1', 'reference cache manifest schema mismatch')
        for name, digest in manifest['files'].items():
            self.add(contained(self.reference, name), digest)
        source = self.reference / 'nemu-src'
        actual = {p.relative_to(self.reference).as_posix() for p in source.rglob('*')
                  if p.is_file() and not p.is_relative_to(source / 'build')}
        actual |= {'reference-used.json', 'nemu-src/build/riscv64-nemu-interpreter-so'}
        require(actual == set(manifest['files']), 'reference source/config inventory drift')
        self.reference_inventory = actual
        lock_path = self.root / 'simulator/gsim/config/reference-lock.json'
        config_path = self.root / 'simulator/gsim/config/rv64-integer-ref_defconfig'
        self.add(lock_path); self.add(config_path)
        lock, used = load(lock_path), load(self.reference / 'reference-used.json')
        require(all(used.get(key) == value for key, value in lock.items()), 'reference lock/attestation mismatch')
        require(used['config_sha256'] == sha(config_path), 'reference requested config mismatch')
        require(used['resolved_config_sha256'] == sha(source / '.config'), 'reference resolved config mismatch')
        self.so = source / 'build/riscv64-nemu-interpreter-so'
        require(used['library_sha256'] == sha(self.so), 'reference library attestation mismatch')
        for name, digest in lock['resources'].items():
            self.add(contained(source / 'resource', name), digest)
        self.used = used

    def guard(self):
        require(self.cxx.resolve() == self.compiler_target and sha(self.cxx) == self.compiler_sha256,
                'C++ driver target changed during replay')
        require(self.flow.inventory() == self.state['inputs'], 'flow source inventory changed during replay')
        require(self.board.source_inventory() == self.state['models']['off']['inputs'], 'board source inventory changed during replay')
        require({p.name for p in BUNDLE.iterdir() if p.is_file()} == self.checker_inventory, 'checker inventory changed during replay')
        source = self.reference / 'nemu-src'
        current = {p.relative_to(self.reference).as_posix() for p in source.rglob('*')
                   if p.is_file() and not p.is_relative_to(source / 'build')}
        current |= {'reference-used.json', 'nemu-src/build/riscv64-nemu-interpreter-so'}
        require(current == self.reference_inventory, 'reference inventory changed during replay')
        for name, digest in self.files.items():
            require(Path(name).is_file() and sha(name) == digest, 'input changed during replay: ' + name)

    def command(self, label, case, out):
        model = self.models[label]
        return [str(self.cxx), *flags(label, case, model['model'], self.cases[case]['directory']),
                '-I' + str(HERE / 'harness'), '-I' + str(BUNDLE),
                str(out / 'observer.cpp'), *map(str, model['objects']),
                '-ldl', '-o', str(out / label / case / 'run')]


def compare_pairs(cases):
    require(set(cases) == {label + '-' + case for label in LABELS for case in CASES}, 'incomplete NEMU case set')
    for case in CASES:
        off, on = cases['off-' + case], cases['on-' + case]
        require(off['guest_sha256'] == on['guest_sha256'], 'older-prefix OFF/ON guest differs')
        for key in ('guest_pc_checks', 'guest_pc_trace', 'final_memory_bytes'):
            require(off['nemu'][key] == on['nemu'][key], 'older-prefix OFF/ON NEMU trace/coverage differs: ' + case + '/' + key)


def verify_execution_compiler(inputs):
    """Execute only the already hash-validated C++ driver before any link/run."""
    inputs.guard()
    require(re.fullmatch(r'clang\+\+(?:-[0-9]+)?', inputs.cxx.name) is not None,
            'execution requires the attested clang++ driver spelling, not resolved clang')
    command = [str(inputs.cxx), '--version']
    result = subprocess.run(command, cwd=inputs.root, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=30)
    require(result.returncode == 0 and result.stdout.splitlines() and
            result.stdout.splitlines()[0] == inputs.compiler_version,
            'live C++ compiler version differs from qualified model/hot compiler')
    inputs.guard()
    return {'command': command, 'version': inputs.compiler_version,
            'sha256': inputs.compiler_sha256}


def run(inputs, out, *, resume=False, variant=None, case=None):
    compiler_check = verify_execution_compiler(inputs)
    out = Path(out).resolve()
    require(not out.exists() or resume, 'output exists; use a fresh output or strict --resume')
    require(not out.is_relative_to(BUNDLE), 'output cannot be inside checker source bundle')
    path = out / 'receipt.json'
    generated = out / 'observer.cpp'
    contents = instrument((HERE / 'harness/cpu_retire_prefix_hot.cpp').read_text())
    require(not resume or path.is_file(), '--resume requires this runner\'s existing receipt')
    out.mkdir(parents=True, exist_ok=True)
    if generated.exists():
        require(generated.read_text() == contents, 'generated observer drift')
    else:
        generated.write_text(contents)
    generated_hash = sha(generated)
    if path.exists():
        state = load(path)
        require(state.get('schema') == SCHEMA and state.get('inputs') == inputs.snapshot, 'resume input/schema drift')
        require(state.get('scope') == SCOPE and all(state.get(k) == v for k, v in ZERO_COUNTERS.items()), 'resume scope drift')
        require(state.get('execution_compiler') == compiler_check, 'resume execution compiler drift')
    else:
        state = {'schema': SCHEMA, 'status': 'PREPARED', 'inputs': inputs.snapshot, 'reference': inputs.used,
                 'execution_compiler': compiler_check,
                 'scope': SCOPE, 'generated_observer_sha256': generated_hash, **ZERO_COUNTERS, 'steps': {}, 'cases': {}, 'negatives': {}}

    def save():
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(state, indent=2) + '\n')
        temporary.replace(path)

    def step(name, command, expected=0, anchor=None, products=()):
        inputs.guard()
        require(sha(generated) == generated_hash == state['generated_observer_sha256'], 'generated observer changed')
        for record in state['steps'].values():
            require(sha(contained(out, record['log'])) == record['log_sha256'], 'earlier log changed')
            for artifact_name, digest in record['artifacts'].items():
                require(sha(contained(out, artifact_name)) == digest, 'earlier product changed')
        command = list(map(str, command))
        if name in state['steps']:
            record = state['steps'][name]
            require(record['command'] == command and record['exit'] == expected, 'resume command/exit drift')
            log = contained(out, record['log'])
            require(sha(log) == record['log_sha256'], 'resume log drift')
            require(set(record['artifacts']) == {str(p.relative_to(out)) for p in products}, 'resume product set drift')
            for artifact_name, digest in record['artifacts'].items():
                require(sha(contained(out, artifact_name)) == digest, 'resume product drift')
            text = log.read_text()
            require(not anchor or anchor in text, 'resume log anchor drift')
            return text
        log = out / (name + '.log')
        index = 0
        while log.exists():
            index += 1
            log = out / f'{name}.retry{index}.log'
        print('+', ' '.join(command), flush=True)
        start = time.monotonic()
        exit_code, failure = None, None
        try:
            with log.open('x') as stream:
                result = subprocess.run(command, cwd=inputs.root, stdout=stream, stderr=subprocess.STDOUT,
                                        timeout=300, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
            exit_code = result.returncode
        except BaseException as error:
            failure = repr(error)
        text = log.read_text() if log.exists() else ''
        record = {'command': command, 'exit': exit_code, 'seconds': time.monotonic() - start,
                  'log': log.name, 'log_sha256': sha(log),
                  'artifacts': {str(p.relative_to(out)): sha(p) for p in products if p.is_file()}}
        if failure or exit_code != expected or (anchor and anchor not in text) or len(record['artifacts']) != len(products):
            record['error'] = failure or 'exit/anchor/product mismatch'
            state.setdefault('failed_steps', []).append(record)
            save()
            raise RuntimeError(name + ': ' + record['error'] + '\n' + text[-6000:])
        inputs.guard()
        state['steps'][name] = record
        save()
        return text

    try:
        state['status'] = 'RUNNING'; state.pop('error', None); save()
        for label in LABELS:
            if variant and variant != label:
                continue
            for guest_case in CASES:
                if case and case != guest_case:
                    continue
                key = label + '-' + guest_case
                directory = inputs.cases[guest_case]['directory']
                binary = out / label / guest_case / 'run'
                binary.parent.mkdir(parents=True, exist_ok=True)
                step(key + '-link', inputs.command(label, guest_case, out), products=(binary,))
                text = step(key + '-run', [binary, directory / 'guest.bin', inputs.so], anchor='NEMU_PASS')
                counters = nemu_counters(text)
                require(line(text, 'HOT_RESULT') == inputs.original_results[key], 'hot measurement changed: ' + key)
                measured = inputs.flow.parse(text)
                previous = inputs.state['cases'][label][guest_case]
                require(all(measured[name] == previous[name] for name in ('result', 'pipeline', 'distributions', 'performance')),
                        'hot observer metrics changed: ' + key)
                state['cases'][key] = {'nemu': counters, 'binary_sha256': sha(binary),
                                      'guest_sha256': sha(directory / 'guest.bin'), 'hot_result_exactly_unchanged': True}
                save()
                print(key, line(text, 'NEMU_PASS'), flush=True)
                if guest_case == 'read-4096':
                    for mode, anchor in NEGATIVES.items():
                        name = label + '-negative-nemu-' + mode
                        text = step(name, [binary, directory / 'guest.bin', inputs.so, '--inject-nemu-' + mode], expected=1, anchor=anchor)
                        require('NEMU_PASS' not in text, 'negative unexpectedly passed')
                        state['negatives'][name] = {'expected_exit': 1, 'required_anchor': anchor}
                        save()
        inputs.guard()
        require(sha(generated) == generated_hash, 'final generated observer drift')
        if len(state['cases']) == 12 and len(state['negatives']) == 6:
            compare_pairs(state['cases'])
            state['status'] = PASS
        else:
            state['status'] = 'PARTIAL_PASS'
        save()
        if state['status'] == PASS:
            audit(path, inputs)
    except BaseException as error:
        state['status'] = 'FAIL'; state['error'] = str(error); save(); raise
    print(state['status'], path, flush=True)
    return state


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=HERE.parents[1])
    parser.add_argument('--flow-receipt', required=True, type=Path)
    parser.add_argument('--reference-cache', required=True, type=Path)
    parser.add_argument('--recorded-root', type=Path, help='Old source-root prefix, only when relocating the complete receipt tree')
    parser.add_argument('--compiler', type=Path, help='Relocated compiler executable; exact attested executable SHA-256 is still required')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--run', action='store_true', help='Enable serial harness links and simulations after preflight')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--variant', choices=LABELS)
    parser.add_argument('--case', choices=CASES)
    args = parser.parse_args(argv)
    if args.run and not args.out:
        parser.error('--run requires --out')
    if args.resume and not args.run:
        parser.error('--resume requires --run')
    return args


def main():
    args = arguments()
    inputs = Inputs(args.root, args.flow_receipt, args.reference_cache, recorded_root=args.recorded_root, compiler=args.compiler)
    if args.run:
        run(inputs, args.out, resume=args.resume, variant=args.variant, case=args.case)
    else:
        print(json.dumps({'status': 'PASS_INPUT_PREFLIGHT_ONLY', 'input_files': len(inputs.files),
                          'cases': 12, 'checker_negatives_planned': 6, 'scope': SCOPE,
                          'simulation_run': False, 'compiler_invoked': False}, indent=2))


if __name__ == '__main__':
    main()
