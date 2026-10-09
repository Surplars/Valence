#!/usr/bin/env python3
"""Fresh source-matched selected-board off/on physical-ingress bandwidth check.

By default, build portable source-only guests and two fresh source-matched models.
Explicit --hot-receipt/--guest-manifest and --model-tag keep strict reuse available. The
only configuration difference is physicalLoadIngressFlow. Independent complete
request/permission/full-token shadows remain active, including route negatives.
No physical FPGA timing, Linux, board access, synthesis or NEMU claim.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import run as common
from cpu_hot_bandwidth import parse
import build_cpu_hot_bandwidth as guests
import fpga_next_board as board

require = guests.require


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory():
    files = list((common.ROOT / 'src/main').rglob('*.scala'))
    files += list((common.ROOT / 'third_party/berkeley-hardfloat/src/main/scala').rglob('*.scala'))
    files += [common.ROOT / 'src/test/scala/ooo/BoardSocGsimMain.scala',
              common.ROOT / 'src/test/scala/ooo/FpgaNextBoardGsimMain.scala',
              common.ROOT / 'build.mill', Path(__file__), common.HERE / 'fpga_next_board.py',
              common.HERE / 'cpu_hot_bandwidth.py', common.HERE / 'run.py',
              Path(guests.__file__), common.HERE / 'config/toolchain.json',
              *[common.ROOT / p for p in guests.PAYLOADS]]
    files += [common.HERE / 'harness' / name for name in (
        'cpu_flow_bandwidth.cpp', 'cpu_flow_bandwidth.h', 'board_boot.cpp',
        'board_ddr_benchmark.h', 'board_ddr_multiid.h', 'backend_observer.h',
        'backend_ownership_ledger.h', 'data_path_sample.h', 'data_path_ownership_ledger.h',
        'cpu_hot_bandwidth.h', 'performance_observer.h')]
    return {**board.source_inventory(),
            **{str(p.relative_to(common.ROOT)): sha(p) for p in sorted(set(files))}}



def normalize_guests(path, root=common.ROOT):
    """Fresh manifests and original/recovered archival receipts share one strict view."""
    path = Path(path).resolve()
    require(path.is_file(), 'missing guest receipt/manifest: ' + str(path))
    state = json.loads(path.read_text())
    if state.get('schema') == guests.SCHEMA:
        _, cases = guests.load_manifest(path, root)
        return {'kind': 'fresh_source_build', 'path': str(path), 'sha256': sha(path)}, cases
    accepted = {'valence-cpu-hot-bandwidth-reuse-v1': 'PASS_CPU_HOT_BANDWIDTH_REUSE',
                'valence-cpu-hot-bandwidth-recovery-v1': 'PASS_CPU_HOT_BANDWIDTH_RECOVERY'}
    require(state.get('schema') in accepted and state.get('status') == accepted[state['schema']],
            'not a successful original/recovered hot receipt or fresh guest manifest')
    require(set(state.get('cases', {})) == set(guests.CASES), 'incomplete or unexpected guest case set')
    require(state.get('geometry') == {'store_buffer_entries': 2, 'lsu_slots': 2}, 'historical guest geometry drift')
    for name in guests.PAYLOADS:
        require(name in state.get('inputs', {}), 'missing historical guest source hash: ' + name)
        guests.stable(root / name, state['inputs'][name], 'historical guest source')
    cases = {}
    for case in guests.CASES:
        previous = state['cases'][case]
        op, size = case.split('-')
        result = previous.get('result', {})
        require((result.get('op'), result.get('buffer_bytes'), result.get('reps')) == (op, int(size), 4),
                'historical guest case config drift: ' + case)
        relative = state.get('case_provenance', {}).get(case, {}).get('directory', case)
        directory = Path(relative)
        if not directory.is_absolute():
            directory = path.parent / directory
        directory = directory.resolve()
        hashes = {}
        for name in ('guest.elf', 'guest.bin', 'cpu_hot_bandwidth_symbols.h'):
            require(name in previous.get('artifacts', {}), 'missing historical guest hash: ' + name)
            hashes[name] = previous['artifacts'][name]
            guests.stable(directory / name, hashes[name], case + '/' + name)
        require((directory / 'cpu_hot_bandwidth_symbols.h').read_text() == guests.header(previous['symbols']),
                'historical symbol/header mismatch: ' + case)
        cases[case] = {'directory': directory, 'artifacts': hashes}
    return {'kind': 'historical_guest_receipt', 'path': str(path), 'sha256': sha(path)}, cases


def expected_model_plan(flag, *, dma_line_transfers=False, dma_line_entries=1, dma_line_yield_cycles=0, lsu_entries=2, load_order_older_retire=False):
    require(dma_line_entries in (1, 2, 4) and (dma_line_transfers or dma_line_entries == 1),
            'DMA owner count requires line transfers')
    require(dma_line_yield_cycles in (0, 4, 8, 16, 32, 64) and
            (dma_line_transfers or dma_line_yield_cycles == 0), 'DMA yield requires line transfers')
    require(lsu_entries in (2, 4), 'unsupported LSU owner count')
    parameters = ['--selected']
    if dma_line_transfers:
        parameters.append('--dma-line-transfers')
    if dma_line_entries > 1:
        parameters.append('--dma-line-entries=' + str(dma_line_entries))
    if dma_line_yield_cycles:
        parameters.append('--dma-line-yield-cycles=' + str(dma_line_yield_cycles))
    if lsu_entries != 2:
        parameters.append('--lsu-entries=' + str(lsu_entries))
    return {'parameters': parameters + (['--physical-load-ingress-flow'] if flag else []) +
            (['--load-order-older-retire'] if load_order_older_retire else []),
            'smoke_only': True, 'passive_probes': True, 'guest_suite': ['rv64gc']}


def validate_model(path, flag, inputs, compiler, **shared_options):
    path = Path(path)
    require(path.is_file(), 'missing explicitly reusable model receipt: ' + str(path))
    state = json.loads(path.read_text())
    require(state.get('schema') == 'valence-fpga-next-board-evidence-v1' and
            state.get('status') == 'PASS_FPGA_NEXT_BOARD_SMOKE', 'model is not a completed board smoke checkpoint')
    require(state.get('inputs') == inputs, 'model source inventory drift')
    require(state.get('plan') == expected_model_plan(flag, **shared_options), 'model profile drift')
    require(state.get('toolchain') == {**common.LOCK, 'compiler': compiler}, 'model toolchain/profile drift')
    artifacts = state.get('artifacts', {})
    model = path.parent / 'model'
    units = sorted(model.glob('BoardSocGsim[0-9]*.cpp'))
    objects = sorted(model.glob('BoardSocGsim[0-9]*.o'))
    require(units and objects == [p.with_suffix('.o') for p in units], 'missing or unexpected model object set')
    for item in [model / 'BoardSocGsim.h', model / 'BoardSocGsim.fir', *units, *objects]:
        require(item.relative_to(path.parent).as_posix() in artifacts, 'unhashed model artifact: ' + str(item))
    for name, digest in artifacts.items():
        guests.stable(guests.contained(path.parent, name), digest, 'model artifact')
    return state, model, objects


def arguments(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', required=True)
    group = ap.add_mutually_exclusive_group()
    group.add_argument('--hot-receipt', type=Path, help='Original/recovered historical receipt (compatibility)')
    group.add_argument('--guest-manifest', type=Path, help='Source-matched portable fresh guest manifest')
    group.add_argument('--fresh-guests', action='store_true', help='Build guests from tracked payloads (default)')
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--model-tag', help='Explicitly reuse completed exact-source/profile off/on model checkpoints')
    ap.add_argument('--dma-line-transfers', action='store_true', help='Same explicit idle-DMA profile on both sides')
    ap.add_argument('--dma-line-entries', type=int, choices=(1, 2, 4), default=1)
    ap.add_argument('--dma-line-yield-cycles', type=int, choices=(0, 4, 8, 16, 32, 64), default=0)
    args = ap.parse_args(argv)
    if not args.dma_line_transfers and (args.dma_line_entries != 1 or args.dma_line_yield_cycles):
        ap.error('DMA depth/yield requires --dma-line-transfers')
    if not re.fullmatch('[A-Za-z0-9_-]+', args.tag) or (args.model_tag and not re.fullmatch('[A-Za-z0-9_-]+', args.model_tag)):
        ap.error('unsafe tag')
    return args


def main():
    args = arguments()
    shared_options = {name: getattr(args, name) for name in
                      ('dma_line_transfers', 'dma_line_entries', 'dma_line_yield_cycles')}
    model_request = {'reuse_tag': args.model_tag, 'shared_options': shared_options}
    out = common.BUILD / ('cpu-bandwidth-flow-board-' + args.tag)
    require(not out.exists() or args.resume, 'output exists; use a new tag or strict --resume')
    out.mkdir(parents=True, exist_ok=True)
    receipt = out / 'receipt.json'
    if receipt.exists() and not args.resume:
        raise RuntimeError('output exists; use a new tag or strict --resume')
    require(not args.resume or receipt.is_file(), '--resume requires this runner’s existing receipt')
    existing = json.loads(receipt.read_text()) if receipt.exists() else None
    frozen = inventory()
    if existing:
        require(existing['inputs'] == frozen, 'source/input drift')
    selected = args.guest_manifest or args.hot_receipt
    if selected is None:
        selected = out / 'guests' / 'manifest.json'
        if not existing:
            guests.build(selected.parent)
    guest_input, cases = normalize_guests(selected)
    state = existing or {
        'schema': 'valence-cpu-physical-flow-board-v2', 'status': 'RUNNING',
        'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=common.ROOT, text=True).strip(),
        'inputs': frozen, 'guest_input': guest_input,
        'model_request': model_request,
        'steps': {}, 'models': {}, 'cases': {}, 'comparison': {},
        'limits': ['Actual executed selected GSIM board, source-matched off/on.',
                   'No NEMU, physical FPGA timing/resource, Linux or real-board qualification.',
                   '100 MHz conversion of measured model cycles; fixed external AXI timing model.',
                   'Physical-only M-mode guest; S-mode/PMP/epoch coverage is a separate directed adapter proof.']}
    require(state.get('guest_input') == guest_input and state.get('model_request') == model_request,
            'guest/model request drift; use the same arguments or a fresh output tag')
    board_inputs = board.source_inventory()
    def save():
        receipt.write_text(json.dumps(state, indent=2) + '\n')
    def guard():
        require(inventory() == frozen, 'source changed during qualification')
        actual_input, actual_cases = normalize_guests(selected)
        require(actual_input == guest_input and actual_cases == cases, 'guest changed during qualification')
        if 'host_compiler' in state:
            guests.stable(state['host_compiler']['path'], state['host_compiler']['sha256'], 'host compiler')
        for label, record in state['models'].items():
            guests.stable(record['receipt'], record['receipt_sha256'], 'model receipt during qualification')
            validate_model(record['receipt'], int(label == 'on'), board_inputs, state['compiler'], **shared_options)
    state['status'] = 'RUNNING'
    state.pop('error', None)
    save()
    def step(name, command, products=(), expected=0, anchor=None, timeout=900):
        guard()
        if name in state['steps']:
            record = state['steps'][name]
            require(record['command'] == list(map(str, command)) and record['exit'] == expected, 'step command/exit drift')
            require(sha(out / record['log']) == record['log_sha256'], 'step log drift')
            require(all(sha(path) == digest for path, digest in record['artifacts'].items()), 'step artifact drift')
            require(set(record['artifacts']) == {str(p) for p in products}, 'step product set drift')
            require(not anchor or anchor in (out / record['log']).read_text(), 'step success anchor drift')
            return (out / record['log']).read_text()
        log = out / (name + '.log')
        suffix = 0
        while log.exists():
            suffix += 1
            log = out / f'{name}.retry{suffix}.log'
        print('+', ' '.join(map(str, command)), flush=True)
        start = time.monotonic()
        with log.open('w') as stream:
            result = subprocess.run(list(map(str, command)), cwd=common.ROOT, stdout=stream, stderr=subprocess.STDOUT,
                timeout=timeout, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        text = log.read_text()
        record = {'command': list(map(str, command)), 'exit': result.returncode, 'seconds': time.monotonic() - start,
                  'log': log.name, 'log_sha256': sha(log), 'artifacts': {str(p): sha(p) for p in products if Path(p).exists()}}
        if result.returncode != expected or (anchor and anchor not in text):
            state.setdefault('failed_steps', []).append(record); save()
            raise RuntimeError(name + '\n' + text[-6000:])
        require(set(record['artifacts']) == {str(p) for p in products}, 'missing step product')
        state['steps'][name] = record; save(); return text
    try:
        cxx, compiler = common.compiler()
        require(state.get('compiler', compiler) == compiler, 'host compiler drift')
        state['compiler'] = compiler
        compiler_path = shutil.which(cxx)
        require(compiler_path is not None, 'missing host compiler executable')
        host_compiler = {'path': str(Path(compiler_path).resolve()), 'sha256': sha(compiler_path)}
        require(state.get('host_compiler', host_compiler) == host_compiler, 'host compiler executable drift')
        state['host_compiler'] = host_compiler
        for flag in (0, 1):
            label = 'off' if flag == 0 else 'on'
            model_tag = 'cpu-flow-' + label + '-' + (args.model_tag or args.tag)
            model_out = common.BUILD / ('fpga-next-board-' + model_tag)
            model_receipt = model_out / 'receipt.json'
            if not args.model_tag:
                command = ['python3', '-B', common.HERE / 'fpga_next_board.py', '--tag', model_tag,
                           '--variant', 'selected', '--jobs', '1', '--smoke-only']
                if args.dma_line_transfers:
                    command.append('--dma-line-transfers')
                if args.dma_line_entries > 1:
                    command.extend(['--dma-line-entries', str(args.dma_line_entries)])
                if args.dma_line_yield_cycles:
                    command.extend(['--dma-line-yield-cycles', str(args.dma_line_yield_cycles)])
                if flag:
                    command.append('--physical-load-ingress-flow')
                # Resume applies only to this explicitly resumed runner's own model tag.
                previous = state['steps'].get(label + '-model')
                if args.resume and (previous is None or '--resume' in previous['command']):
                    command.append('--resume')
                step(label + '-model', command, [model_receipt], anchor='PASS_FPGA_NEXT_BOARD_SMOKE', timeout=1800)
            model_state, model, objects = validate_model(model_receipt, flag, board_inputs, compiler, **shared_options)
            if flag:
                require(model_state['inputs'] == state['models']['off']['inputs'], 'off/on source inventory mismatch')
            state['models'][label] = {'receipt': str(model_receipt), 'receipt_sha256': sha(model_receipt),
                'inputs': model_state['inputs'], 'plan': model_state['plan'],
                'origin': 'explicit_reuse' if args.model_tag else 'built_for_this_run'}
            save()
            for case in guests.CASES:
                op, size = case.split('-')
                directory = cases[case]['directory']
                case_out = out / label / case
                case_out.mkdir(parents=True, exist_ok=True)
                binary = case_out / 'run'
                flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-DUART_DIVISOR=1', '-DBOARD_CPU_HZ=100000000', '-DBOARD_UART_BAUD=460800', '-DUART_EXTRA_STOP_BITS=0',
                    '-DDDR_MODEL=1', '-DBOARD_DDR_BYTES=2147483648ULL', '-DDDR_MULTI_ID_MODEL=1', '-DDDR_BENCHMARK_MODEL=1',
                    '-DDDR_READ_CREDITS=8', '-DDDR_READ_LATENCY=32', '-DDDR_READ_BEAT_GAP=1', '-DBOARD_CYCLE_LIMIT=300000ULL',
                    '-DHOT_BYTES=' + size, '-DHOT_REPS=4', '-DHOT_SB_ENTRIES=2', '-DHOT_OP=' + str({'read': 0, 'write': 1, 'copy': 2}[op]),
                    '-DPHYSICAL_INGRESS_FLOW=' + str(flag), '-I' + str(model), '-I' + str(directory)]
                step(label + '-' + case + '-link', [cxx, *flags, common.HERE / 'harness/cpu_flow_bandwidth.cpp',
                    *objects, '-ldl', '-o', binary], [binary])
                text = step(label + '-' + case + '-run', [binary, directory / 'guest.bin'],
                            anchor='HOT_PASS', timeout=180)
                parsed = parse(text)
                parsed['guest_sha256'] = sha(directory / 'guest.bin')
                parsed['binary_sha256'] = sha(binary)
                state['cases'].setdefault(label, {})[case] = parsed; save()
                print(label, case, json.dumps(parsed['result']), flush=True)
                if case == 'read-4096':
                    negatives = {
                        'physical-fingerprint': 'physical request fingerprint corruption',
                        'route': 'physical ingress route prediction mismatch',
                        'virtual-enqueue': 'raw virtual enqueue route mismatch',
                        'checked-enqueue': 'raw checked enqueue route mismatch',
                        'authorization': 'independent checked payload/permission mismatch',
                        'private-metadata': 'physical authorization metadata mismatch',
                        'return-token': 'backend return full-token lineage corruption'}
                    for mode, anchor in negatives.items():
                        step(label + '-negative-' + mode, [binary, directory / 'guest.bin', '--inject-' + mode],
                             expected=1, anchor=anchor, timeout=180)
        for case, off in state['cases']['off'].items():
            on = state['cases']['on'][case]
            require(off['guest_sha256'] == on['guest_sha256'], 'off/on guest drift')
            for key in ('architectural_loads', 'architectural_stores', 'physical_source_reads',
                        'physical_destination_writes', 'payload_bytes', 'kernel_pc_trace', 'kernel_retired'):
                require(off['result'][key] == on['result'][key], 'off/on result drift: ' + case + '/' + key)
            if case.startswith('read'):
                require(off['distributions']['cpu_start_to_result']['histogram'].startswith('6:'), 'off load residency mismatch')
                require(on['distributions']['cpu_start_to_result']['histogram'].startswith('5:'), 'on load residency mismatch')
                require(on['result']['kernel_cycles'] < off['result']['kernel_cycles'], 'missing expected load gain')
            state['comparison'][case] = {'off': off['result'], 'on': on['result'],
                'kernel_speedup': off['result']['kernel_cycles'] / on['result']['kernel_cycles'],
                'complete_speedup': off['result']['complete_cycles'] / on['result']['complete_cycles']}
        guard(); state['status'] = 'PASS_SOURCE_MATCHED_CPU_FLOW_BOARD'
    except BaseException as error:
        state['status'] = 'FAIL'; state['error'] = str(error); save(); raise
    save(); print(state['status'], receipt, flush=True)

if __name__ == '__main__':
    main()
