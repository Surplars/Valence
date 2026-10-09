#!/usr/bin/env python3
"""Focused representative extension of explicit same-source LSU2/4 board models.

No elaboration, generated-model compilation, source mutation, global setup,
component-receipt rewrite, full regression, Linux, FPGA tool or board access.
--prepare performs only provenance reads and local metadata writes.
--execute must only be used after the parent grants the CPU-heavy slot.
"""
import argparse
import hashlib
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
ROOT = HERE.parents[1]
OUT = None
sys.path.insert(0, str(HERE))
from fpga_next_board import source_inventory, marker
from virtual_load_board import parse as parse_virtual
from mshr_occupancy import validate

import cpu_mlp_bandwidth_board as mlp
import cpu_mlp_data_pmp as capacity
import run as common

RECEIPT = None
CASES = ('steady', 'independent', 'virtual', 'fetch-permission', 'rv64gc')
SCOPE = {
    'profile': 'same selected two-issue FPGA-next board with DMA lines/depth4/yield0 configured but idle; physicalLoadIngressFlow enabled on both; only LSU capacity and derived owner/request queues differ',
    'steady': '64KiB > 32KiB L1 capacity; three-pass read/write/copy, separately measured write/copy flush tails, 1024-node 3072-hop dependent pointer chase',
    'independent': '64KiB working set, one LD per 64-byte line, 3072 loads over three passes',
    'cold': 'actual Sv39 cold_pages ROI: four new virtual pages and physical lines after an independent warm region; no fabricated cold classification of the physical repeated stream',
    'virtual': 'Sv39 MPRV/S-effective data warm/cold/chase, 4KiB page alias, exact one permitted UART LSR MMIO read, no wrong-path MMIO or retirement, precise load-page fault cause/PC/tval, drain and full signature',
    'pmp': 'existing fetch-permission guest: grant, revoke execute, precise instruction-access fault, restore; guest checks mepc/mtval and non-execution at the cached compressed gate; host checks trap sequence 9/1/9',
    'atomic': 'unchanged rv64gc smoke: amoadd.d old/new anchor, lr.d, successful sc.d, final LD; inherited and freshly rerun exact binary/executable',
    'rv64gc': 'existing integer/compressed/F/D exact anchors, Sv39 S-mode alias FP32-register/fcsr save/restore, S-mode ecall, PMP allow-all setup, UART MMIO',
    'capacity_observation': 'Virtual driver uses the current full-capacity ownership ledger; generated observer changes only the passive LSU peak sum to all owners. Other guest oracles are unchanged.',
    'oracles': 'unchanged independent harnesses; steady final backing/chain oracle and built-in backing mutation, Sv39 signature/trap/marker negatives, fetch/RV64GC misa-anchor negatives',
    'not_covered': ['Denied data-PMP load/store/AMO', 'Exhaustive atomics or concurrent reservation invalidation',
        'All translation epochs or interrupt schedules', 'External DMA/coherence probe injection',
        'NEMU for these representative guests', 'Physical FPGA PPA, timing or board bandwidth',
        'Full regression or Linux'],
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def pin(files, path, expected=None):
    path = Path(path).resolve()
    actual = sha(path)
    if expected is not None and actual != expected:
        raise RuntimeError('provenance mismatch: ' + str(path))
    files[str(path)] = actual


def provenance(hot_path):
    files = {}
    hot_path = Path(hot_path).resolve()
    pin(files, hot_path)
    hot = load(hot_path)
    assert hot['status'] == 'PASS_SOURCE_MATCHED_CPU_LSU_CAPACITY_BOARD'
    assert hot['schema'] == 'valence-cpu-lsu-capacity-board-v1'
    assert hot['inputs'] == mlp.inventory(), 'hot source inventory drift'
    for name, digest in hot['inputs'].items(): pin(files, ROOT / name, digest)
    expected_shared = dict(dma_line_transfers=True, dma_line_entries=4, dma_line_yield_cycles=0)
    assert hot['model_request']['shared_options'] == expected_shared
    _, compiler = common.compiler()
    inventory = source_inventory()
    paths = {label: Path(hot['models'][label]['receipt']) for label in ('lsu2', 'lsu4')}
    checked = capacity.validate_models(paths, inventory, compiler, **expected_shared)
    models = {}
    for label in ('lsu2', 'lsu4'):
        path = paths[label]
        pin(files, path, hot['models'][label]['receipt_sha256'])
        component = checked[label]['state']
        for name, digest in component['inputs'].items(): pin(files, ROOT / name, digest)
        for name, digest in component['artifacts'].items(): pin(files, path.parent / name, digest)
        for record in component['commands']:
            assert record['status'] == 'PASS'
            pin(files, path.parent / record['log'], record['log_sha256'])
        models[label] = {'directory': str(path.parent), 'receipt_sha256': sha(path),
            'plan': component['plan'], 'objects': {str(path.parent / name): digest
                for name, digest in component['artifacts'].items() if name.endswith('.o')},
            'gc_link_command': component['steps']['gc-link']['command'],
            'existing_gc_tests': component['tests'], 'toolchain': component['toolchain']}
    assert models['lsu2']['objects'] and len(models['lsu2']['objects']) == len(models['lsu4']['objects'])
    pin(files, ROOT / 'fpga/firmware/fetch_permission_smoke.S')
    for name in ('config/toolchain.json', 'config/opensbi.json', 'cpu_mlp_data_pmp.py',
                 'cpu_bandwidth_flow_board.py'):
        pin(files, HERE / name)
    pin(files, __file__)
    compilers = {m['gc_link_command'][0] for m in models.values()}
    assert len(compilers) == 1
    for compiler in compilers: pin(files, compiler)
    tools = {}
    for tool in ('riscv64-unknown-elf-gcc', 'riscv64-unknown-elf-objcopy',
                 'riscv64-unknown-elf-objdump', 'riscv64-unknown-elf-nm'):
        path = shutil.which(tool)
        assert path, 'source approved environment first: missing ' + tool
        tools[tool] = path
        pin(files, path)
    return files, inventory, models, tools


def virtual_observer(source):
    """Only widen the passive peak counter; reuse all independent guest checks."""
    old = 'unsigned(backend.live[0]) + unsigned(backend.live[1])'
    assert source.count(old) == 1, 'virtual observer peak anchor drift'
    return source.replace(old, 'backend.liveCount()')


def perf(log):
    result = {}
    for line in log.splitlines():
        if not line.startswith('BOARD_IPC '):
            continue
        fields = dict(word.split('=', 1) for word in line.split()[1:])
        name = fields.pop('name')
        assert name not in result
        result[name] = {k: float(v) if k == 'ipc' else int(v) for k, v in fields.items()}
    return result


def main():
    global OUT, RECEIPT
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--execute', action='store_true')
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--hot-receipt', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    a = ap.parse_args()
    files, inventory, models, toolpaths = provenance(a.hot_receipt)
    OUT = a.out.resolve()
    assert not OUT.exists() or a.resume, 'choose a fresh output or strict resume'
    OUT.mkdir(parents=True, exist_ok=True)
    RECEIPT = OUT / 'receipt.json'
    if RECEIPT.exists():
        assert a.resume, 'receipt exists: use strict --resume'
        state = load(RECEIPT)
        assert state['files'] == files and state['models'] == models and state['scope'] == SCOPE, 'extension input drift'
    else:
        state = {'schema': 'valence-cpu-mlp-representative-v1', 'status': 'PREPARED_NOT_EXECUTED',
            'files': files, 'model_source_inventory': inventory, 'models': models, 'scope': SCOPE,
            'toolpaths': toolpaths, 'steps': {}, 'cases': {}, 'negative_controls': {}, 'artifacts': {},
            'model_elaborations': 0, 'generated_model_compiles': 0, 'production_changes': 0,
            'component_receipt_mutations': 0, 'hot_receipt_sha256': sha(a.hot_receipt)}

    def save():
        RECEIPT.write_text(json.dumps(state, indent=2) + '\n')

    def guard():
        assert source_inventory() == inventory, 'source inventory drift during extension'
        for path, digest in files.items():
            assert sha(path) == digest, ('frozen input changed', path)
        for path, digest in state['artifacts'].items():
            assert sha(OUT / path) == digest, ('extension artifact changed', path)
        for record in state['steps'].values():
            assert sha(OUT / record['log']) == record['log_sha256'], ('extension log changed', record['log'])

    def step(name, argv, products=(), expected=0, anchor=None, timeout=600):
        argv = list(map(str, argv))
        guard()
        if name in state['steps']:
            previous = state['steps'][name]
            assert previous['command'] == argv and previous['expected_exit'] == expected and previous['anchor'] == anchor
            return (OUT / previous['log']).read_text()
        log = OUT / (name + '.log')
        retry = 0
        while log.exists():
            retry += 1
            log = OUT / f'{name}.retry{retry}.log'
        print('+ ' + ' '.join(argv), flush=True)
        started = time.monotonic()
        code = None
        error = None
        try:
            with log.open('w') as stream:
                code = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                    timeout=timeout, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0',
                                         'PYTHONDONTWRITEBYTECODE': '1'}).returncode
        except subprocess.TimeoutExpired as failure:
            error = str(failure)
        text = log.read_text()
        record = {'command': argv, 'actual_exit': code, 'expected_exit': expected, 'anchor': anchor,
            'log': log.name, 'log_sha256': sha(log), 'seconds': time.monotonic() - started,
            'artifacts': {str(p.relative_to(OUT)): sha(p) for p in products if p.exists()}}
        bad_sanitizer = any(token in text for token in ('ERROR: AddressSanitizer', 'runtime error:', 'SUMMARY: UndefinedBehaviorSanitizer'))
        if error or code != expected or (anchor and anchor not in text) or bad_sanitizer:
            record['status'] = 'TIMEOUT' if error else 'FAIL'
            record['error'] = error
            state.setdefault('failed_steps', []).append(record)
            state['status'] = 'FAIL'
            save()
            raise RuntimeError(name + '\n' + text[-7000:])
        assert all(p.exists() for p in products), 'expected product absent'
        record['status'] = 'PASS'
        state['artifacts'].update(record['artifacts'])
        state['steps'][name] = record
        save()
        return text

    guard()
    save()
    if a.prepare:
        print('PREPARED_NOT_EXECUTED ' + str(RECEIPT))
        return
    state['status'] = 'RUNNING'
    state.pop('error', None)
    save()
    try:
        fw = OUT / 'firmware'
        fw.mkdir(exist_ok=True)
        firmware = ROOT / 'fpga/firmware'
        for tool, path in toolpaths.items():
            step('tool-' + tool, [path, '--version'])
        step('tool-cxx', [models['lsu2']['gc_link_command'][0], '--version'])
        for case in ('steady', 'independent'):
            elf, binary = fw / (case + '.elf'), fw / (case + '.bin')
            step(case + '-build', [toolpaths['riscv64-unknown-elf-gcc'], '-O2', '-march=rv64im_zicsr_zifencei', '-mabi=lp64',
                '-mcmodel=medany', '-mno-relax', '-msmall-data-limit=0', '-ffreestanding', '-fno-builtin',
                '-fno-stack-protector', '-nostdlib', '-nostartfiles', '-Wl,--no-relax', '-Wl,--gc-sections',
                '-ffunction-sections', '-fdata-sections', '-DCPU_HZ=100000000ULL', '-DUART_BAUD=460800',
                '-Wl,--defsym=BOARD_RAM_BYTES=2147483648', '-Wl,--defsym=BOARD_MONITOR_BASE=4294934528',
                '-T', firmware / 'sample_app.ld', firmware / 'sample_start.S',
                HERE / f'payloads/board_memory_{case}.c', '-lgcc', '-o', elf], products=(elf,))
            step(case + '-bin', [toolpaths['riscv64-unknown-elf-objcopy'], '-O', 'binary', elf, binary], products=(binary,))
            dis = step(case + '-disassembly', [toolpaths['riscv64-unknown-elf-objdump'], '-d', elf])
            # Use the already independently checked marker helper on the frozen ELF.
            starts = {k: marker(elf, k) for k in ('steady_start', 'steady_stop')}
            assert all(re.search(r'^\s*' + format(pc, 'x') + r':.*\brdtime\b', dis, re.M) for pc in starts.values())
            state.setdefault('guests', {})[case] = {'elf': str(elf), 'binary': str(binary),
                'elf_sha256': sha(elf), 'binary_sha256': sha(binary), 'markers': starts}
            save()
        virtual_dir = fw / 'virtual'
        virtual_products = tuple(virtual_dir / name for name in ('guest.o', 'guest.elf', 'guest.bin', 'guest.json', 'guest.dis', 'guest.nm'))
        step('virtual-build', [sys.executable, HERE / 'build_virtual_load_core.py', virtual_dir], products=virtual_products)
        guest = load(virtual_dir / 'guest.json')
        state['guests']['virtual'] = guest
        header = fw / 'virtual_load_guest_symbols.h'
        values = {name.upper(): value for name, value in guest['symbols'].items()}
        values['ENTRY'] = values.pop('_START')
        values['IMAGE_END'] = guest['symbols']['_start'] + Path(guest['binary']).stat().st_size
        contents = '#pragma once\n' + ''.join(f'#define VIRTUAL_GUEST_{name} 0x{value:x}ULL\n' for name, value in values.items())
        if header.exists():
            assert header.read_text() == contents
        else:
            header.write_text(contents)
        state['artifacts'][str(header.relative_to(OUT))] = sha(header)
        fetch_elf, fetch_bin = fw / 'fetch-permission.elf', fw / 'fetch-permission.bin'
        step('fetch-permission-build', [toolpaths['riscv64-unknown-elf-gcc'], '-march=rv64gc', '-mabi=lp64d', '-mcmodel=medany',
            '-mno-relax', '-nostdlib', '-nostartfiles', '-Wl,--no-relax', '-Wl,--build-id=none',
            '-Wl,--defsym=BOARD_RAM_BYTES=2147483648', '-Wl,--defsym=BOARD_MONITOR_BASE=4294934528',
            '-T', firmware / 'sample_app.ld', firmware / 'fetch_permission_smoke.S', '-o', fetch_elf], products=(fetch_elf,))
        step('fetch-permission-bin', [toolpaths['riscv64-unknown-elf-objcopy'], '-O', 'binary', fetch_elf, fetch_bin], products=(fetch_bin,))
        step('fetch-permission-disassembly', [toolpaths['riscv64-unknown-elf-objdump'], '-d', fetch_elf])
        state['guests']['fetch-permission'] = {'elf': str(fetch_elf), 'binary': str(fetch_bin),
            'elf_sha256': sha(fetch_elf), 'binary_sha256': sha(fetch_bin)}
        save()
        virtual_cpp = fw / 'virtual_load_board.cpp'
        content = virtual_observer((HERE / 'harness/virtual_load_board.cpp').read_text())
        if virtual_cpp.exists(): assert virtual_cpp.read_text() == content
        else: virtual_cpp.write_text(content)
        state['artifacts'][str(virtual_cpp.relative_to(OUT))] = sha(virtual_cpp)
        save()
        for label in ('lsu2', 'lsu4'):
            component = Path(models[label]['directory'])
            model = component / 'model'
            validate(ROOT, model / 'BoardSocGsim.h', 2, 'board$platform$privateCache$')
            bindir = OUT / label
            bindir.mkdir(exist_ok=True)
            for case in CASES:
                extra = []
                arguments = []
                if case in ('steady', 'independent'):
                    executable, binary = bindir / case, Path(state['guests'][case]['binary'])
                    harness = HERE / 'harness/board_memory_steady.cpp'
                    extra = ['-DMODEL_MSHRS=2'] + (['-DINDEPENDENT_LINE_KERNEL=1'] if case == 'independent' else [])
                    extra += ['-DSTEADY_START_PC=' + str(state['guests'][case]['markers']['steady_start']) + 'ULL',
                              '-DSTEADY_STOP_PC=' + str(state['guests'][case]['markers']['steady_stop']) + 'ULL']
                    anchor = 'BOARD_MEMORY_STEADY_PASS'
                elif case == 'virtual':
                    executable, binary = bindir / case, Path(guest['binary'])
                    harness, extra, anchor = virtual_cpp, ['-I' + str(fw), '-I' + str(HERE / 'harness'), '-DBACKEND_OWNER_COUNT=' + label[3:]], 'VIRTUAL_BOARD_PASS'
                else:
                    executable = component / 'gc'
                    binary = fetch_bin if case == 'fetch-permission' else component / 'firmware/rv64gc.bin'
                    arguments = ['--fetch-permission'] if case == 'fetch-permission' else []
                    anchor = 'FETCH_PERMISSION_BOARD_PASS' if case == 'fetch-permission' else 'RV64GC_BOARD_PASS'
                if case in ('steady', 'independent', 'virtual'):
                    cmd = models[label]['gc_link_command'].copy()
                    cmd[cmd.index(str(HERE / 'harness/rv64gc_board.cpp'))] = str(harness)
                    cmd[cmd.index('-o') + 1] = str(executable)
                    if case == 'virtual':
                        cmd.remove('-DDDR_BENCHMARK_MODEL=1')
                    idx = cmd.index('-I' + str(model))
                    cmd[idx:idx] = extra
                    assert {x for x in cmd if x.endswith('.o')} == set(models[label]['objects'])
                    step(label + '-' + case + '-link', cmd, products=(executable,))
                name = label + '-' + case
                log = step(name + '-run', [executable, binary, *arguments], anchor=anchor)
                metrics = parse_virtual(log) if case == 'virtual' else {'performance': perf(log)}
                if case in ('steady', 'independent'):
                    assert len(metrics['performance']) == (6 if case == 'steady' else 1)
                    assert 'STEADY_ORACLE_SENSITIVITY mutation_detected=1 restored_verified=1 DUT_fault_injection=0' in log
                if case == 'virtual':
                    assert set(metrics['roi']) == {'warm_independent', 'cold_pages', 'dependent_chase'}
                state['cases'][name] = {'status': 'PASS', 'binary': str(binary), 'binary_sha256': sha(binary),
                    'executable': str(executable), 'executable_sha256': sha(executable), 'metrics': metrics,
                    'run_step': name + '-run'}
                save()
                print(name + ' PASS\n' + '\n'.join(line for line in log.splitlines()
                    if line.startswith(('BOARD_IPC ', 'VIRTUAL_BOARD_ARCH ', 'VIRTUAL_BOARD_PASS ', 'BOARD_MEMORY_STEADY_PASS ',
                                        'FETCH_PERMISSION_BOARD_PASS ', 'RV64GC_BOARD_PASS '))), flush=True)
                negatives = [('signature', 'independent full-core signature mismatch'),
                    ('trap', 'independent full-core trap provenance mismatch'),
                    ('marker', 'ROI boundary order/uniqueness mismatch')] if case == 'virtual' else (
                    [('mismatch', 'firmware independent anchor/context failure')] if case in ('fetch-permission', 'rv64gc') else [])
                for mutation, rejection in negatives:
                    n = name + '-negative-' + mutation
                    step(n, [executable, binary, *arguments, '--inject-' + mutation], expected=1, anchor=rejection)
                    state['negative_controls'][n] = {'status': 'REJECTED', 'expected_exit': 1, 'required_anchor': rejection}
                    save()
        assert len(state['cases']) == 10 and len(state['negative_controls']) == 10
        comparisons = {}
        for case in CASES:
            old, new = state['cases']['lsu2-' + case], state['cases']['lsu4-' + case]
            assert old['binary_sha256'] == new['binary_sha256'], 'LSU2/4 guest byte mismatch: ' + case
            if case == 'virtual':
                for key in ('signature_hash', 'retired', 'pc_trace', 'traps', 'trap_pc', 'trap_cause', 'trap_tval', 'lsr_reads'):
                    assert old['metrics']['architecture'][key] == new['metrics']['architecture'][key], ('Sv39 architectural A/B mismatch', key)
                for name, before in old['metrics']['roi'].items():
                    after = new['metrics']['roi'][name]
                    assert (before['retired'], before['pc_trace']) == (after['retired'], after['pc_trace']), ('Sv39 ROI retirement mismatch', name)
            for region, before in old['metrics']['performance'].items():
                after = new['metrics']['performance'][region]
                comparisons[case + '/' + region] = {'lsu2_cycles': before['cycles'], 'lsu4_cycles': after['cycles'],
                    'change_percent': 100 * (after['cycles'] / before['cycles'] - 1),
                    'lsu2_retired': before['retired'], 'lsu4_retired': after['retired'],
                    'lsu2_read_miss': before['read_miss'], 'lsu4_read_miss': after['read_miss']}
        state['comparison'] = comparisons
        state['measurement_limits'] = ['Steady driver ROI samples whole boundary cycles; adjacent retired lanes may differ by timing.',
            'Virtual ROI retirement is lane-exact and its retired PC trace is compared.',
            'No zero-regression assertion is hidden in correctness status; all cycle deltas are reported.',
            'PMP guest validates execute denial, not denied data loads/stores/AMOs.',
            'Fresh RV64GC confirms exact existing AMO/LR/SC anchors, not exhaustive atomic coverage.']
        state['architectural_ab_equivalence'] = 'PASS_VIRTUAL_EXACT_SIGNATURE_TRAP_RETIRED_PC_AND_PER_ROI_TRACE'
        guard()
        state['status'] = 'PASS_SOURCE_MATCHED_CPU_LSU_CAPACITY_REPRESENTATIVE'
    except BaseException as error:
        state['status'] = 'FAIL'
        state['error'] = str(error)
        raise
    finally:
        save()
    print(state['status'] + ' ' + str(RECEIPT), flush=True)


if __name__ == '__main__':
    main()
