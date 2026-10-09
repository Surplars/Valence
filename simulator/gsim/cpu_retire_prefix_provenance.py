#!/usr/bin/env python3
"""Read-only, fail-closed evidence closure shared by older-prefix extensions.

Receipts supply hashes and observations, never executable command recipes.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import cpu_retire_prefix_board as hot
import build_cpu_hot_bandwidth as guests
import fpga_next_board as board
import run as common

if not __debug__:
    raise RuntimeError('qualification requires Python assertions enabled; do not use -O/PYTHONOPTIMIZE')

require, sha, contained = guests.require, guests.sha, guests.contained
LABELS = ('off', 'on')
CASES = guests.CASES
SHARED = dict(dma_line_transfers=True, dma_line_entries=4, dma_line_yield_cycles=0)
SANITIZERS = ('ERROR: AddressSanitizer', 'runtime error:', 'SUMMARY: UndefinedBehaviorSanitizer',
              'SUMMARY: AddressSanitizer', 'LeakSanitizer')
CXX_FLAGS = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
BOARD_FLAGS = ['-DBACKEND_OWNER_COUNT=4', '-DUART_DIVISOR=1', '-DBOARD_CPU_HZ=100000000',
               '-DBOARD_UART_BAUD=460800', '-DUART_EXTRA_STOP_BITS=0', '-DDDR_MODEL=1',
               '-DBOARD_DDR_BYTES=2147483648ULL', '-DDDR_MULTI_ID_MODEL=1', '-DDDR_BENCHMARK_MODEL=1',
               '-DDDR_READ_CREDITS=8', '-DDDR_READ_LATENCY=32', '-DDDR_READ_BEAT_GAP=1']
NEGATIVES = {
    'physical-fingerprint': 'physical request fingerprint corruption',
    'route': 'physical ingress route prediction mismatch',
    'virtual-enqueue': 'raw virtual enqueue route mismatch',
    'checked-enqueue': 'raw checked enqueue route mismatch',
    'authorization': 'independent checked payload/permission mismatch',
    'private-metadata': 'physical authorization metadata mismatch',
    'return-token': 'backend return full-token lineage corruption',
    'reserve-guard': 'test-only capacity guard differs from production',
    'upper-live': 'slot live owner appeared or was prematurely released',
    'upper-token': 'slot full-token generation or position changed'}


def load(path):
    return json.loads(Path(path).read_text())


def clean_log(text, anchor=None, negative=False):
    require(not any(token in text for token in SANITIZERS), 'sanitizer diagnostic in proof log')
    require(anchor is None or anchor in text, 'missing required log anchor: ' + str(anchor))
    if negative:
        require(not any(token in text for token in ('HOT_PASS', 'RV64GC_BOARD_PASS',
                'FETCH_PERMISSION_BOARD_PASS', 'VIRTUAL_BOARD_PASS')), 'negative control reported success')


def quote_dependencies():
    """Names resolved relative to generated observers before explicit -I paths."""
    names = {'BoardSocGsim.h', 'cpu_hot_bandwidth_symbols.h', 'virtual_load_guest_symbols.h'}
    for path in (common.HERE / 'harness').iterdir():
        if path.is_file() and path.suffix in ('.h', '.cpp'):
            names.update(re.findall(r'^\s*#include\s+"([^"\n]+)"', path.read_text(), re.M))
    return names


def hot_flags(case, model, guest):
    op, size = case.split('-')
    return [*CXX_FLAGS, *BOARD_FLAGS, '-DBOARD_CYCLE_LIMIT=300000ULL', '-DHOT_BYTES=' + size,
            '-DHOT_REPS=4', '-DHOT_SB_ENTRIES=2', '-DHOT_OP=' + str(('read', 'write', 'copy').index(op)),
            '-DPHYSICAL_INGRESS_FLOW=1', '-I' + str(model), '-I' + str(guest)]


def gc_command(cxx, model, objects, output, source=None, extra=(), virtual=False):
    defines = [flag for flag in BOARD_FLAGS if not virtual or flag != '-DDDR_BENCHMARK_MODEL=1']
    return list(map(str, [cxx, *CXX_FLAGS, *defines, '-DBOARD_CYCLE_LIMIT=12000000ULL', *extra,
            '-I' + str(model), source or common.HERE / 'harness/rv64gc_board.cpp', *objects, '-ldl', '-o', output]))


def cached_step(out, state, name, argv, products=(), expected=0, anchor=None):
    """Revalidate a saved step against its source-defined contract, including products."""
    record = state['steps'][name]
    require(record.get('command') == list(map(str, argv)), 'cached command drift: ' + name)
    require(record.get('expected_exit') == expected and record.get('actual_exit') == expected
            and record.get('status') == 'PASS', 'cached exit/status drift: ' + name)
    require(record.get('anchor') == anchor, 'cached anchor contract drift: ' + name)
    required = {str(Path(p).relative_to(out)) for p in products}
    require(set(record.get('artifacts', {})) == required, 'cached product inventory drift: ' + name)
    for relative, digest in record['artifacts'].items():
        product = contained(out, relative)
        require(state['artifacts'].get(relative) == digest and sha(product) == digest,
                'cached product hash drift: ' + relative)
    log = contained(out, record['log'])
    require(sha(log) == record['log_sha256'], 'cached log drift: ' + name)
    text = log.read_text()
    clean_log(text, anchor, expected != 0)
    return text


class HotInputs:
    """Validate the complete qualified hot run before any subprocess is allowed."""
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.files = {}
        self.add(self.path)
        self.state = state = load(self.path)
        require(state.get('schema') == 'valence-cpu-retire-prefix-board-v1' and
                state.get('status') == 'PASS_SOURCE_MATCHED_CPU_OLDER_PREFIX_BOARD', 'qualified hot receipt required')
        require(state.get('inputs') == hot.inventory(), 'hot source inventory drift')
        for name, digest in state['inputs'].items():
            self.add(contained(common.ROOT, name), digest)
        self.board_inputs = board.source_inventory()
        request = state.get('model_request', {})
        require(set(request) == {'reuse_tag', 'shared_options'} and request['shared_options'] == SHARED,
                'hot model request drift')
        tag = request['reuse_tag']
        require(tag is None or re.fullmatch('[A-Za-z0-9_-]+', tag), 'invalid reuse tag')
        require(set(state.get('models', {})) == set(LABELS) and
                set(state.get('cases', {})) == set(LABELS), 'hot model/case pair drift')
        actual_guest, self.cases = hot.normalize_guests(state['guest_input']['path'])
        require(actual_guest == state['guest_input'] and actual_guest['kind'] == 'fresh_source_build',
                'source-built guest manifest required')
        manifest = Path(actual_guest['path'])
        self.add(manifest, actual_guest['sha256'])
        guest = load(manifest)
        for record in guest['sources'].values():
            self.add(contained(manifest.parent, record['path']), record['sha256'])
        expected_guest_commands = []
        for case in CASES:
            op, size = case.split('-')
            flags = ['-march=rv64im_zicsr_zifencei', '-mabi=lp64', '-mno-relax']
            defines = ['-DHOT_SB_ENTRIES=2', '-DHOT_OP=' + str(('read', 'write', 'copy').index(op)),
                       '-DHOT_BYTES=' + size, '-DHOT_REPS=4']
            commands = {
                'assemble': ['riscv64-unknown-elf-gcc', *flags, *defines, '-c', '../sources/cpu_hot_bandwidth.S', '-o', 'guest.o'],
                'link': ['riscv64-unknown-elf-gcc', *flags, '-nostdlib', '-nostartfiles', '-Wl,--no-relax',
                         '-Wl,--build-id=none', '-T', '../sources/cpu_hot_bandwidth.ld', 'guest.o', '-o', 'guest.elf'],
                'binary': ['riscv64-unknown-elf-objcopy', '-O', 'binary', 'guest.elf', 'guest.bin'],
                'symbols': ['riscv64-unknown-elf-nm', '-n', 'guest.elf']}
            expected_guest_commands.extend((case, name, command) for name, command in commands.items())
        require(len(guest.get('commands', [])) == len(expected_guest_commands), 'incomplete guest build evidence')
        for record, (case, name, command) in zip(guest['commands'], expected_guest_commands):
            require(record.get('exit') == 0 and record.get('cwd') == case and record.get('command') == command
                    and record.get('log') == case + '/' + name + '.log', 'guest build command/evidence drift')
            log = contained(manifest.parent, record['log'])
            self.add(log, record['log_sha256']); clean_log(log.read_text())
        for case in self.cases.values():
            for relative, digest in case['artifacts'].items():
                self.add(contained(case['directory'], relative), digest)
        self.original_cxx = state['steps']['off-read-4096-link']['command'][0]
        driver = shutil.which(self.original_cxx)
        require(driver is not None and re.fullmatch(r'clang\+\+(?:-\d+)?', Path(driver).name),
                'qualified clang++ driver required')
        # Do not resolve argv[0]: clang++ -> clang changes automatic C++ linkage.
        self.cxx = Path(driver).absolute()
        host = state['host_compiler']
        require(self.cxx.resolve() == Path(host['path']).resolve(), 'hot compiler target drift')
        self.add(self.cxx, host['sha256'])
        self.compiler_target = self.cxx.resolve()
        self.compiler_version = state['compiler']
        require(re.search(r'clang version \d+', self.compiler_version), 'invalid qualified compiler version')
        self.models = {}
        expected_steps = set()
        for label in LABELS:
            rec = state['models'][label]
            path = Path(rec['receipt']).resolve()
            self.add(path, rec['receipt_sha256'])
            component, model, objects = hot.validate_model(path, 1, self.board_inputs, self.compiler_version,
                lsu_entries=4, load_order_older_retire=(label == 'on'), **SHARED)
            require(rec.get('inputs') == component['inputs'] and rec.get('plan') == component['plan'],
                    'hot/model profile disagreement')
            require(rec.get('origin') == ('explicit_reuse' if tag else 'built_for_this_run'), 'model origin drift')
            prefix = 'fpga-next-board-cpu-retire-prefix-' + label + '-'
            require(path.parent.name.startswith(prefix), 'unexpected model directory')
            model_tag = path.parent.name[len(prefix):]
            require(re.fullmatch('[A-Za-z0-9_-]+', model_tag), 'invalid model tag')
            if tag:
                require(model_tag == tag, 'model reuse tag drift')
            else:
                name = label + '-model'; expected_steps.add(name)
                command = ['python3', '-B', str(common.HERE / 'fpga_next_board.py'), '--tag',
                    'cpu-retire-prefix-' + label + '-' + model_tag, '--variant', 'selected', '--jobs', '1',
                    '--smoke-only', '--dma-line-transfers', '--dma-line-entries', '4', '--lsu-entries', '4',
                    '--physical-load-ingress-flow'] + (['--load-order-older-retire'] if label == 'on' else [])
                record = state['steps'][name]
                require(record['command'] in (command, command + ['--resume']), 'model creation command drift')
                self.hot_step(record, record['command'], {str(path): rec['receipt_sha256']},
                              anchor='PASS_FPGA_NEXT_BOARD_SMOKE')
            self.validate_component(path, component, model, objects)
            self.models[label] = dict(receipt=path, state=component, model=model, objects=objects)
            require(set(state['cases'][label]) == set(CASES), 'hot case inventory drift')
            for case in CASES:
                name = label + '-' + case
                binary = self.path.parent / label / case / 'run'
                directory = self.cases[case]['directory']
                command = [self.original_cxx, *hot_flags(case, model, directory),
                    str(common.HERE / 'harness/cpu_retire_prefix_hot.cpp'), *map(str, objects), '-ldl', '-o', str(binary)]
                recorded = state['cases'][label][case]
                self.hot_step(state['steps'][name + '-link'], command, {str(binary): recorded['binary_sha256']})
                text = self.hot_step(state['steps'][name + '-run'], [str(binary), str(directory / 'guest.bin')], {}, anchor='HOT_PASS')
                parsed = hot.parse(text)
                require(recorded == {**parsed, 'guest_sha256': sha(directory / 'guest.bin'),
                        'binary_sha256': sha(binary)}, 'hot metrics/log/artifact disagreement: ' + name)
                expected_steps.update((name + '-link', name + '-run'))
            for mode, anchor in NEGATIVES.items():
                name = label + '-negative-' + mode; expected_steps.add(name)
                self.hot_step(state['steps'][name], [str(self.path.parent / label / 'read-4096/run'),
                    str(self.cases['read-4096']['directory'] / 'guest.bin'), '--inject-' + mode], {}, expected=1, anchor=anchor)
        require(set(state['steps']) == expected_steps, 'hot step inventory drift')
        self.add(Path(__file__).resolve())
        self.guard()

    def add(self, path, expected=None):
        path = Path(path).resolve()
        digest = sha(path)
        require(expected is None or digest == expected, 'input hash mismatch: ' + str(path))
        require(str(path) not in self.files or self.files[str(path)] == digest, 'conflicting input hash')
        self.files[str(path)] = digest
        return digest

    def hot_step(self, record, argv, products, expected=0, anchor=None):
        require(record.get('command') == argv and record.get('exit') == expected, 'upstream command/exit drift')
        require(record.get('artifacts') == products, 'upstream product inventory drift')
        for name, digest in products.items():
            path = Path(name)
            require(path.is_relative_to(common.ROOT), 'hot product outside source root')
            self.add(path, digest)
        log = contained(self.path.parent, record['log'])
        self.add(log, record['log_sha256'])
        text = log.read_text(); clean_log(text, anchor, expected != 0)
        return text

    def validate_component(self, path, state, model, objects):
        expected_artifacts = {str(p.relative_to(path.parent)) for p in
            [model / 'BoardSocGsim.h', model / 'BoardSocGsim.fir', *objects,
             *[p.with_suffix('.cpp') for p in objects], path.parent / 'gc',
             path.parent / 'firmware/rv64gc.elf', path.parent / 'firmware/rv64gc.bin']}
        require(set(state['artifacts']) == expected_artifacts, 'model artifact inventory drift')
        for name, digest in state['artifacts'].items():
            self.add(contained(path.parent, name), digest)
        require(state['commands'] == list(state['steps'].values()), 'model command/step disagreement')
        require(set(state['tests']) == {'gc', 'gc-negative'} and
                all(state['tests'][name] == state['steps']['test-' + name] for name in state['tests']),
                'model test/step disagreement')
        commands = {
            'gc-link': gc_command(self.original_cxx, model, objects, path.parent / 'gc'),
            'test-gc': [str(path.parent / 'gc'), str(path.parent / 'firmware/rv64gc.bin')],
            'test-gc-negative': [str(path.parent / 'gc'), str(path.parent / 'firmware/rv64gc.bin'), '--inject-mismatch'],
            'elaborate': ['mill', '-i', 'IonSoC.test.runMain', 'ooo.FpgaNextBoardGsimMain', str(model), *state['plan']['parameters']],
            'gc-build': ['riscv64-unknown-elf-gcc', '-march=rv64gc', '-mabi=lp64d', '-mcmodel=medany',
                '-mno-relax', '-nostdlib', '-nostartfiles', '-Wl,--no-relax', '-Wl,--build-id=none',
                '-Wl,--defsym=BOARD_RAM_BYTES=2147483648', '-Wl,--defsym=BOARD_MONITOR_BASE=4294934528',
                '-T', str(common.ROOT / 'fpga/firmware/sample_app.ld'), str(common.ROOT / 'fpga/firmware/rv64gc_smoke.S'),
                '-o', str(path.parent / 'firmware/rv64gc.elf')],
            'gc-bin': ['riscv64-unknown-elf-objcopy', '-O', 'binary', str(path.parent / 'firmware/rv64gc.elf'),
                       str(path.parent / 'firmware/rv64gc.bin')]}
        for obj in objects:
            commands['compile-' + obj.stem] = [self.original_cxx, *CXX_FLAGS, '-I' + str(model), '-c',
                                              str(obj.with_suffix('.cpp')), '-o', str(obj)]
        require(set(state['steps']) == set(commands) | {'generate'}, 'model step inventory drift')
        for name, record in state['steps'].items():
            if name == 'generate':
                require(record['command'][1:] == ['--threads=1', '--dir=' + str(model), str(model / 'BoardSocGsim.fir')],
                        'model generation argument drift')
            else:
                require(record['command'] == commands[name], 'model command drift: ' + name)
            expected = int(name == 'test-gc-negative')
            require(record.get('status') == 'PASS' and record.get('actual_exit') == record.get('expected_exit') == expected,
                    'failed model step: ' + name)
            log = contained(path.parent, record['log']); self.add(log, record['log_sha256'])
            clean_log(log.read_text(), {'test-gc': 'RV64GC_BOARD_PASS',
                'test-gc-negative': 'firmware independent anchor/context failure'}.get(name), expected != 0)

    def guard(self):
        require(hot.inventory() == self.state['inputs'] and board.source_inventory() == self.board_inputs,
                'current source inventory drift')
        require(self.cxx.resolve() == self.compiler_target, 'C++ driver target drift')
        for name, digest in self.files.items():
            guests.stable(name, digest, 'frozen qualification input')
        # An added generated object or quote-include shadow must not evade hashes.
        headers = quote_dependencies()
        for model in self.models.values():
            require(sorted(model['model'].glob('*.o')) == model['objects'], 'model object inventory drift')
            for name in headers - {'BoardSocGsim.h'}:
                require(not (model['model'] / name).exists(), 'generated model header shadow: ' + name)
        for case in self.cases.values():
            for name in headers - {'cpu_hot_bandwidth_symbols.h'}:
                require(not (case['directory'] / name).exists(), 'guest header shadow: ' + name)

    def check_compiler_version(self):
        self.guard()
        version = subprocess.check_output([str(self.cxx), '--version'], text=True).splitlines()[0]
        require(version == self.compiler_version, 'qualified C++ driver version drift')
        self.guard()
