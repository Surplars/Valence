#!/usr/bin/env python3
"""Run the actual-CPU S-mode/MPRV data-PMP gate against explicit LSU2/4 models.

Build only the tracked assembly guest and observer harness, never a hardware model.
Both completed selected-board smoke receipts must match the current board sources,
locked toolchain and exact profiles; physical ingress is enabled on both sides; only LSU capacity differs.
Use a new --out directory for every run. No archive or fixed workspace is needed.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

import build_cpu_hot_bandwidth as guests
import cpu_bandwidth_flow_board as flow
import fpga_next_board as board
import run as common

require, sha, stable = guests.require, guests.sha, guests.stable
SCHEMA = 'valence-cpu-mlp-data-pmp-v1'
STATUS = 'PASS_SOURCE_MATCHED_LSU_CAPACITY_DATA_PMP'
SYMBOLS = ('denied_s', 'denied_mprv', 'supervisor_ecall', 'done', 'fail')
SOURCE_PATHS = (
    'simulator/gsim/cpu_mlp_data_pmp.py',
    'simulator/gsim/harness/cpu_flow_data_pmp.cpp',
    'simulator/gsim/payloads/cpu_flow_data_pmp.S',
    'simulator/gsim/payloads/cpu_hot_bandwidth.ld',
    'simulator/gsim/build_cpu_hot_bandwidth.py',
    'simulator/gsim/cpu_bandwidth_flow_board.py',
    'simulator/gsim/cpu_hot_bandwidth.py',
    'simulator/gsim/config/toolchain.json',
    'simulator/gsim/config/opensbi.json',
)
NEGATIVES = {
    'trap': 'data PMP trap provenance mismatch',
    'data': 'data PMP independent read mismatch',
    'count': 'data PMP final architectural/request count mismatch',
}
RESULT = re.compile(
    r'DATA_PMP_BOARD_PASS cycles=(\d+) traps=3 denied_s=1 denied_mprv=1 '
    r'allowed_reads=3 forbidden_physical=0 retired=(\d+) pc_trace=(\d+)')


def inventory():
    return {**board.source_inventory(),
            **{name: sha(common.ROOT / name) for name in SOURCE_PATHS}}


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--out', required=True, type=Path, help='Fresh output directory; resume is intentionally unsupported')
    for side in ('lsu2', 'lsu4'):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--' + side + '-model-receipt', type=Path, help='Explicit completed board receipt.json')
        group.add_argument('--' + side + '-model-tag', help='Exact fpga_next_board.py --tag value under build/gsim')
    parser.add_argument('--dma-line-transfers', action='store_true', default=True, help='Same explicit idle-DMA profile on both models')
    parser.add_argument('--dma-line-entries', type=int, choices=(4,), default=4)
    parser.add_argument('--dma-line-yield-cycles', type=int, choices=(0,), default=0)
    args = parser.parse_args(argv)
    if not args.dma_line_transfers and (args.dma_line_entries != 1 or args.dma_line_yield_cycles):
        parser.error('DMA depth/yield requires --dma-line-transfers')
    for side in ('lsu2', 'lsu4'):
        tag = getattr(args, side + '_model_tag')
        if tag is not None and not re.fullmatch('[A-Za-z0-9_-]+', tag):
            parser.error('unsafe model tag')
    return args


def model_paths(args, build=common.BUILD):
    return {side: (getattr(args, side + '_model_receipt') or
                  Path(build) / ('fpga-next-board-' + getattr(args, side + '_model_tag')) / 'receipt.json').resolve()
            for side in ('lsu2', 'lsu4')}


def validate_models(paths, inputs, compiler, **shared_options):
    require(set(paths) == {'lsu2', 'lsu4'}, 'explicit LSU2/4 model pair required')
    require(paths['lsu2'].resolve() != paths['lsu4'].resolve(), 'LSU2/4 model receipts must be distinct')
    models = {}
    for side in ('lsu2', 'lsu4'):
        require(paths[side].is_file(), 'missing explicitly reusable model receipt: ' + str(paths[side]))
        receipt_hash = sha(paths[side])
        state, directory, objects = flow.validate_model(paths[side], 1, inputs, compiler, lsu_entries=int(side[3:]), **shared_options)
        stable(paths[side], receipt_hash, 'model receipt during validation')
        models[side] = {'receipt': paths[side], 'receipt_sha256': receipt_hash,
                        'directory': directory, 'objects': objects, 'state': state}
    require(models['lsu2']['state']['inputs'] == models['lsu4']['state']['inputs'], 'LSU2/4 source mismatch')
    require(models['lsu2']['state']['toolchain'] == models['lsu4']['state']['toolchain'], 'LSU2/4 toolchain mismatch')
    return models


def parse_symbols(text):
    symbols = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[2] in SYMBOLS:
            require(fields[2] not in symbols, 'duplicate data-PMP symbol: ' + fields[2])
            symbols[fields[2]] = int(fields[0], 16)
    symbol_header(symbols)
    return symbols


def symbol_header(symbols):
    require(set(symbols) == set(SYMBOLS), 'missing or unexpected data-PMP symbols')
    require(all(type(value) is int and 0x80200000 <= value < 0x80204000 and value % 4 == 0
                for value in symbols.values()), 'data-PMP symbol address outside aligned guest image')
    require(len(set(symbols.values())) == len(SYMBOLS), 'aliased data-PMP symbols')
    return ''.join(f'#define GUEST_{name.upper()} 0x{symbols[name]:x}ULL\n' for name in SYMBOLS)


def parse_result(text):
    lines = [line for line in text.splitlines() if line.startswith('DATA_PMP_BOARD_PASS')]
    require(len(lines) == 1, 'missing or ambiguous data-PMP result')
    match = RESULT.fullmatch(lines[0])
    require(match is not None, 'malformed data-PMP result')
    cycles, retired, trace = map(int, match.groups())
    require(0 < cycles < 100100 and retired > 0 and trace < 2**64, 'invalid data-PMP counters')
    return {'cycles': cycles, 'retired': retired, 'pc_trace': trace}


def compare_results(cases):
    require(set(cases) == {'lsu2', 'lsu4'}, 'incomplete data-PMP cases')
    require(all(cases['lsu2'][key] == cases['lsu4'][key] for key in ('retired', 'pc_trace')),
            'LSU2/4 retirement count/trace mismatch')
    return {key: cases['lsu2'][key] for key in ('retired', 'pc_trace')}


def run(args):
    out = args.out.resolve()
    require(not out.exists(), 'choose a fresh data-PMP output directory')
    frozen, board_inputs = inventory(), board.source_inventory()
    paths = model_paths(args)
    shared_options = {name: getattr(args, name) for name in
                      ('dma_line_transfers', 'dma_line_entries', 'dma_line_yield_cycles')}
    # Validate both complete models before any assembly, linking or output writes.
    cxx, compiler = common.compiler()
    models = validate_models(paths, board_inputs, compiler, **shared_options)
    host = shutil.which(cxx)
    require(host is not None, 'missing host compiler executable')
    # Keep the C++ driver basename: resolving clang++ to clang changes linker behavior.
    host = Path(host).absolute()
    tools, versions = guests.toolchain()
    out.mkdir(parents=True, exist_ok=False)
    receipt = out / 'receipt.json'
    state = {'schema': SCHEMA, 'status': 'RUNNING', 'inputs': frozen,
             'compiler': compiler, 'host_compiler': {'path': str(host), 'resolved_path': str(host.resolve()), 'sha256': sha(host)},
             'guest_toolchain': versions, 'model_request': {'shared_options': shared_options},
             'models': {}, 'guest': {}, 'artifacts': {},
             'steps': {}, 'cases': {}, 'negatives': {},
             'limits': ['Actual selected GSIM CPU with S-mode and M-mode MPRV=S denied reads.',
                        'Exact trap/PC/tval, forbidden-request, retirement, backing and drain checks.',
                        'Denied stores/AMOs, NEMU privilege compliance and exhaustive PMP are outside this gate.',
                        'No model rebuild, FPGA timing/resources, Linux, active DMA or physical-board qualification.']}
    for side, item in models.items():
        original = item['state']
        state['models'][side] = {'receipt': str(item['receipt']), 'receipt_sha256': item['receipt_sha256'],
            'inputs': original['inputs'], 'plan': original['plan'], 'toolchain': original['toolchain'],
            'artifacts': original['artifacts'], 'origin': 'explicit_reuse'}

    def save():
        receipt.write_text(json.dumps(state, indent=2) + '\n')

    def guard():
        require(inventory() == frozen, 'source changed during data-PMP qualification')
        stable(host, state['host_compiler']['sha256'], 'host compiler')
        for name, path in tools.items():
            stable(path, versions[name]['sha256'], 'guest toolchain')
        for side in ('lsu2', 'lsu4'):
            stable(paths[side], state['models'][side]['receipt_sha256'], 'model receipt')
        validate_models(paths, board_inputs, compiler, **shared_options)
        for name, digest in state['artifacts'].items():
            stable(guests.contained(out, name), digest, 'produced artifact')
        for record in state['steps'].values():
            stable(guests.contained(out, record['log']), record['log_sha256'], 'step log')

    def step(name, command, products=(), expected=0, anchor=None):
        guard()
        log = out / (name + '.log')
        command = list(map(str, command))
        print('+', ' '.join(command), flush=True)
        start = time.monotonic()
        record = {'command': command, 'cwd': str(out), 'expected_exit': expected, 'log': log.name}
        try:
            with log.open('x') as stream:
                result = subprocess.run(command, cwd=out, stdout=stream, stderr=subprocess.STDOUT, timeout=180,
                    env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0', 'LC_ALL': 'C', 'SOURCE_DATE_EPOCH': '0'})
            record['exit'] = result.returncode
        except BaseException as error:
            record['error'] = str(error)
            raise
        finally:
            record['seconds'] = time.monotonic() - start
            if log.is_file():
                record['log_sha256'] = sha(log)
            state['steps'][name] = record
            save()
        text = log.read_text()
        require(result.returncode == expected and (not anchor or anchor in text), name + '\n' + text[-4000:])
        for product in products:
            path = guests.contained(out, product)
            require(path.is_file(), 'missing step product: ' + product)
            state['artifacts'][product] = sha(path)
        record['artifacts'] = {name: state['artifacts'][name] for name in products}
        save()
        return text

    save()
    try:
        flags = ['-march=rv64im_zicsr_zifencei', '-mabi=lp64', '-mno-relax']
        source = common.HERE / 'payloads/cpu_flow_data_pmp.S'
        linker = common.HERE / 'payloads/cpu_hot_bandwidth.ld'
        step('guest-compile', [tools['cc'], *flags, '-c', source, '-o', 'guest.o'], ['guest.o'])
        step('guest-link', [tools['cc'], *flags, '-nostdlib', '-nostartfiles', '-Wl,--no-relax',
                           '-Wl,-T,' + str(linker), 'guest.o', '-o', 'guest.elf'], ['guest.elf'])
        step('guest-binary', [tools['objcopy'], '-O', 'binary', 'guest.elf', 'guest.bin'], ['guest.bin'])
        symbols = parse_symbols(step('guest-symbols', [tools['nm'], '-n', 'guest.elf']))
        size = (out / 'guest.bin').stat().st_size
        require(0 < size < 16384 and all(address < 0x80200000 + size for address in symbols.values()),
                'data-PMP image/symbol bounds mismatch')
        (out / 'guest_symbols.h').write_text(symbol_header(symbols))
        state['artifacts']['guest_symbols.h'] = sha(out / 'guest_symbols.h')
        state['guest'] = {'symbols': symbols, 'bytes': size, 'binary_sha256': state['artifacts']['guest.bin']}
        save()
        for side, item in models.items():
            binary = out / (side + '-run')
            flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                '-DBACKEND_OWNER_COUNT=' + side[3:], '-DUART_DIVISOR=1', '-DBOARD_CPU_HZ=100000000', '-DBOARD_UART_BAUD=460800', '-DUART_EXTRA_STOP_BITS=0',
                '-DDDR_MODEL=1', '-DBOARD_DDR_BYTES=2147483648ULL', '-DDDR_MULTI_ID_MODEL=1', '-DDDR_BENCHMARK_MODEL=1',
                '-DDDR_READ_CREDITS=8', '-DDDR_READ_LATENCY=32', '-DDDR_READ_BEAT_GAP=1', '-DBOARD_CYCLE_LIMIT=100000ULL',
                '-I' + str(item['directory']), '-I' + str(out), '-I' + str(common.HERE / 'harness')]
            step(side + '-link', [host, *flags, common.HERE / 'harness/cpu_flow_data_pmp.cpp',
                                 *item['objects'], '-ldl', '-o', binary], [binary.name])
            text = step(side + '-test', [binary, 'guest.bin'], anchor='DATA_PMP_BOARD_PASS')
            state['cases'][side] = parse_result(text)
            save()
            for mutation, anchor in NEGATIVES.items():
                name = side + '-negative-' + mutation
                step(name, [binary, 'guest.bin', '--inject-' + mutation], expected=1, anchor=anchor)
                state['negatives'][name] = {'expected_exit': 1, 'required_anchor': anchor}
                save()
        state['comparison'] = compare_results(state['cases'])
        require(len(state['negatives']) == 6, 'incomplete data-PMP negative controls')
        guard()
        state['status'] = STATUS
        save()
    except BaseException as error:
        state['status'] = 'FAIL'
        state['error'] = str(error)
        save()
        raise
    print(STATUS, receipt, flush=True)
    return receipt


def main(argv=None):
    run(arguments(argv))


if __name__ == '__main__':
    main()
