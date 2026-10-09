"""Fail-closed, source-defined contracts for the narrow fetch/context runner."""
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
GSIM = ROOT / 'simulator/gsim'
VALIDATOR = GSIM / 'fixtures/cpu_order_replay_history_v1/strict_validation.py'
spec = importlib.util.spec_from_file_location('fetch_context_model_validation', VALIDATOR)
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
require, sha, exact, contained = v.require, v.sha, v.exact, v.contained
PRODUCTION = '2288c7f008e9d6440e8a28e339da28152b54892a'
HOST = '4cbebc9c5ffc8d7af6220cc513ebf81a16c09145'
PRODUCTION_TREE = 'c6e69b6b539bc36285b602a39fae32cb76ea012c'
CXX_FLAGS = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
BOARD_FLAGS = ['-DBACKEND_OWNER_COUNT=4', '-DUART_DIVISOR=1', '-DBOARD_CPU_HZ=100000000',
    '-DBOARD_UART_BAUD=460800', '-DUART_EXTRA_STOP_BITS=0', '-DDDR_MODEL=1',
    '-DBOARD_DDR_BYTES=2147483648ULL', '-DDDR_MULTI_ID_MODEL=1', '-DDDR_BENCHMARK_MODEL=1',
    '-DDDR_READ_CREDITS=8', '-DDDR_READ_LATENCY=32', '-DDDR_READ_BEAT_GAP=1']
FETCH_FLAGS = ['-march=rv64gc', '-mabi=lp64d', '-mcmodel=medany', '-mno-relax', '-nostdlib',
    '-nostartfiles', '-Wl,--no-relax', '-Wl,--build-id=none',
    '-Wl,--defsym=BOARD_RAM_BYTES=2147483648', '-Wl,--defsym=BOARD_MONITOR_BASE=4294934528']
CASES = ('fetch-permission', 'virtual')
NEGATIVES = {
    'fetch-permission': [('mismatch', 'firmware independent anchor/context failure')],
    'virtual': [('signature', 'independent full-core signature mismatch'),
                ('trap', 'independent full-core trap provenance mismatch'),
                ('marker', 'ROI boundary order/uniqueness mismatch')],
}
ANCHORS = {'fetch-permission': 'FETCH_PERMISSION_BOARD_PASS', 'virtual': 'VIRTUAL_BOARD_PASS'}
SANITIZERS = ('ERROR: AddressSanitizer', 'runtime error:', 'SUMMARY: UndefinedBehaviorSanitizer',
              'SUMMARY: AddressSanitizer', 'LeakSanitizer')


def clean_log(text, anchor=None, negative=False):
    require(not any(x in text for x in SANITIZERS), 'sanitizer diagnostic in proof log')
    require(anchor is None or anchor in text, 'missing required log anchor: ' + str(anchor))
    if negative:
        require(not any(x in text for x in ('FETCH_PERMISSION_BOARD_PASS', 'RV64GC_BOARD_PASS',
                                          'VIRTUAL_BOARD_PASS')), 'negative reported success')


def verify_sources(root, expected):
    require(type(expected) is dict and bool(expected), 'empty retained source inventory')
    for name, digest in expected.items():
        path = contained(root, name)
        require(path.is_file() and sha(path) == digest, 'retained source/oracle/guest drift: ' + name)


def source_lock():
    lock = json.loads((HERE / 'source_lock.json').read_text())
    require(lock.get('schema') == 'valence-fetch-context-source-lock-v1' and
            lock.get('production') == PRODUCTION and lock.get('host') == HOST and
            lock.get('production_tree') == PRODUCTION_TREE, 'source lock anchor drift')
    verify_sources(ROOT, lock['sources'])
    return lock


def link_command(cxx, model, objects, output, case, header_dir=None, root=ROOT):
    require(case in CASES, 'unknown qualification case')
    defines = [x for x in BOARD_FLAGS if case != 'virtual' or x != '-DDDR_BENCHMARK_MODEL=1']
    extra = ['-I' + str(header_dir), '-I' + str(root / 'simulator/gsim/harness')] if case == 'virtual' else []
    source = root / 'simulator/gsim/harness' / ('virtual_load_board.cpp' if case == 'virtual' else 'rv64gc_board.cpp')
    return list(map(str, [cxx, *CXX_FLAGS, *defines, '-DBOARD_CYCLE_LIMIT=12000000ULL', *extra,
                         '-I' + str(model), source, *objects, '-ldl', '-o', output]))


def historical_evidence(path, state, objects):
    """Validate every old step, log and product; never execute receipt commands.

    Original path strings are evidence only. The explicit receipt may be moved
    with its complete artifact/log tree, without rebuilding or rewriting it.
    """
    steps = state.get('steps', {})
    require(type(steps) is dict and 'gc-build' in steps and 'gc-link' in steps, 'missing model step evidence')
    build = steps['gc-build'].get('command', [])
    require(len(build) >= 5 and '-T' in build, 'invalid historical firmware recipe')
    linker_path, elf_path = Path(build[build.index('-T') + 1]), Path(build[-1])
    require(linker_path.is_absolute() and elf_path.is_absolute() and len(linker_path.parents) >= 3 and
            len(elf_path.parents) >= 2, 'historical roots must be absolute')
    oldroot = linker_path.parents[2]
    oldout = elf_path.parents[1]
    require(oldroot.is_absolute() and oldout.is_absolute(), 'historical roots must be absolute')
    oldmodel = oldout / 'model'
    oldobjects = [oldmodel / p.name for p in objects]
    cxx = steps['gc-link'].get('command', [''])[0]
    require(re.fullmatch(r'clang\+\+(?:-\d+)?', Path(cxx).name), 'historical compiler driver drift')
    commands = {
        'gc-build': list(map(str, ['riscv64-unknown-elf-gcc', *FETCH_FLAGS, '-T',
            oldroot / 'fpga/firmware/sample_app.ld', oldroot / 'fpga/firmware/rv64gc_smoke.S',
            '-o', oldout / 'firmware/rv64gc.elf'])),
        'gc-bin': list(map(str, ['riscv64-unknown-elf-objcopy', '-O', 'binary',
            oldout / 'firmware/rv64gc.elf', oldout / 'firmware/rv64gc.bin'])),
        'elaborate': list(map(str, ['mill', '-i', 'IonSoC.test.runMain', 'ooo.FpgaNextBoardGsimMain',
                                  oldmodel, *state['plan']['parameters']])),
        'gc-link': link_command(cxx, oldmodel, oldobjects, oldout / 'gc', 'fetch-permission', root=oldroot),
        'test-gc': list(map(str, [oldout / 'gc', oldout / 'firmware/rv64gc.bin'])),
        'test-gc-negative': list(map(str, [oldout / 'gc', oldout / 'firmware/rv64gc.bin', '--inject-mismatch'])),
    }
    for obj in oldobjects:
        commands['compile-' + obj.stem] = list(map(str, [cxx, *CXX_FLAGS, '-I' + str(oldmodel),
            '-c', obj.with_suffix('.cpp'), '-o', obj]))
    require(set(steps) == set(commands) | {'generate'}, 'complete model step inventory drift')
    require(exact(state.get('commands'), list(steps.values())), 'model command/step disagreement')
    require(set(state.get('tests', {})) == {'gc', 'gc-negative'} and all(
        exact(state['tests'][name], steps['test-' + name]) for name in ('gc', 'gc-negative')),
        'model test/step disagreement')
    expected_artifacts = {'model/BoardSocGsim.h', 'model/BoardSocGsim.fir', 'gc',
        'firmware/rv64gc.elf', 'firmware/rv64gc.bin', *('model/' + p.name for p in objects),
        *('model/' + p.with_suffix('.cpp').name for p in objects)}
    require(set(state['artifacts']) == expected_artifacts, 'complete model artifact inventory drift')
    logs = {}
    for name, record in steps.items():
        command = record.get('command')
        if name == 'generate':
            require(type(command) is list and len(command) == 4 and Path(command[0]).name == 'gsim' and
                command[1:] == ['--threads=1', '--dir=' + str(oldmodel), str(oldmodel / 'BoardSocGsim.fir')],
                'model generator recipe drift')
        else:
            require(exact(command, commands[name]), 'model recipe drift: ' + name)
        expected = int(name == 'test-gc-negative')
        require(record.get('status') == 'PASS' and type(record.get('actual_exit')) is int and
                type(record.get('expected_exit')) is int and record['actual_exit'] == record['expected_exit'] == expected,
                'model exit/status drift: ' + name)
        log = contained(path.parent, record['log'])
        require(log.is_file() and sha(log) == record['log_sha256'], 'model log drift: ' + name)
        require(record['log'] not in logs, 'duplicate model log')
        clean_log(log.read_text(), {'test-gc': 'RV64GC_BOARD_PASS',
            'test-gc-negative': 'firmware independent anchor/context failure'}.get(name), bool(expected))
        logs[record['log']] = sha(log)
    return {'historical_compiler_driver': cxx, 'logs': logs}


def header_text(guest):
    values = {name.upper(): value for name, value in guest['symbols'].items()}
    values['ENTRY'] = values.pop('_START')
    values['IMAGE_END'] = guest['symbols']['_start'] + Path(guest['binary']).stat().st_size
    return '#pragma once\n' + ''.join(f'#define VIRTUAL_GUEST_{name} 0x{value:x}ULL\n' for name, value in values.items())


def include_guard(models, header_dir=None):
    # All quote-include dependencies of unchanged harnesses must resolve to the
    # frozen source tree, apart from the actual model and generated symbol header.
    names = set()
    for source in (GSIM / 'harness').iterdir():
        if source.suffix in ('.cpp', '.h'):
            names.update(re.findall(r'^\s*#include\s+"([^"\n]+)"', source.read_text(), re.M))
    for _, model, _ in models.values():
        for name in names - {'BoardSocGsim.h'}:
            require(not (model / name).exists(), 'model include shadow: ' + name)
    require(not (GSIM / 'harness/BoardSocGsim.h').exists(), 'source model-header shadow')
    require(not (GSIM / 'harness/virtual_load_guest_symbols.h').exists(), 'source symbol-header shadow')
    if header_dir:
        for name in names - {'virtual_load_guest_symbols.h'}:
            require(not (header_dir / name).exists(), 'output include shadow: ' + name)


def metrics(case, text, parse_virtual):
    clean_log(text, ANCHORS[case])
    if case == 'fetch-permission':
        rows = [line for line in text.splitlines() if line.startswith('FETCH_PERMISSION_BOARD_PASS ')]
        require(len(rows) == 1, 'missing/duplicate fetch PASS line')
        pairs = [word.split('=', 1) for word in rows[0].split()[1:]]
        require(len({pair[0] for pair in pairs}) == len(pairs), 'duplicate fetch result field')
        fields = dict(pairs)
        require(set(fields) == {'cycles', 'context_fprs', 's_ecall', 'compressed_advances', 'ddr_reads'},
                'fetch result field drift')
        result = {key: int(value) for key, value in fields.items()}
        require(result['s_ecall'] == 3 and result['compressed_advances'] > 0 and result['ddr_reads'] > 0,
                'fetch precise-trap/compressed witness missing')
        return result
    kinds = {'VIRTUAL_BOARD_ROI': 3, 'VIRTUAL_BOARD_ARCH': 1, 'VIRTUAL_BOARD_PASS': 1, 'BOARD_IPC': 3}
    for kind, count in kinds.items():
        rows = [line for line in text.splitlines() if line.startswith(kind + ' ')]
        require(len(rows) == count, 'virtual result record inventory drift: ' + kind)
        for row in rows:
            keys = [word.split('=', 1)[0] for word in row.split()[1:]]
            require(len(keys) == len(set(keys)), 'duplicate virtual field')
    result = parse_virtual(text)
    regions = {'warm_independent', 'cold_pages', 'dependent_chase'}
    require(set(result['roi']) == set(result['performance']) == regions, 'virtual region inventory drift')
    arch = result['architecture']
    require(set(arch) == {'signature_hash', 'retired', 'pc_trace', 'traps', 'trap_pc', 'trap_cause',
        'trap_tval', 'lsr_reads', 'owner_checks', 'cancelled_outstanding_cycles'}, 'virtual architecture inventory drift')
    require(arch['traps'] == 1 and arch['trap_cause'] == 13 and arch['trap_tval'] == 0x40008000 and
            arch['lsr_reads'] == 1 and arch['owner_checks'] > 0, 'virtual architecture witnesses missing')
    run = result['run']
    require(run['regions'] == 3 and run['DDR_READ_LATENCY'] == 32 and run['DDR_READ_CREDITS'] == 8 and
            run['DDR_READ_BEAT_GAP'] == 1 and run['forced_response_holds'] == 0, 'virtual DDR schedule drift')
    return result


def equivalent(cases):
    old, new = cases['off-virtual']['metrics'], cases['on-virtual']['metrics']
    for key in ('signature_hash', 'retired', 'pc_trace', 'traps', 'trap_pc', 'trap_cause', 'trap_tval', 'lsr_reads'):
        require(old['architecture'][key] == new['architecture'][key], 'virtual architectural A/B mismatch: ' + key)
    for name in old['roi']:
        for key in ('retired', 'pc_trace'):
            require(old['roi'][name][key] == new['roi'][name][key], 'virtual ROI A/B mismatch: ' + name + '/' + key)
    for case in CASES:
        require(cases['off-' + case]['guest_sha256'] == cases['on-' + case]['guest_sha256'], 'guest A/B bytes differ')
    return 'PASS_EXACT_VIRTUAL_SIGNATURE_TRAP_RETIRED_PC_AND_ROI_TRACE'
