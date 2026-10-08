#!/usr/bin/env python3
"""Replay an independent-line guest on a hash-verified frozen reference board object.

No RTL elaboration/codegen and no current-candidate claim. Exact original host DDR
latency/credits/beat gap and independent backing-memory checks are retained.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--reference', type=Path, required=True)
    ap.add_argument('--tag', required=True)
    a = ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', a.tag):
        ap.error('invalid tag')
    reference = a.reference.resolve()
    prior = json.loads((reference / 'receipt.json').read_text())
    if prior['status'] != 'PASS_FPGA_NEXT_BOARD_AND_STEADY':
        raise RuntimeError('reference board is not qualified')
    needed = ['model/BoardSocGsim.fir', 'model/BoardSocGsim.h', 'model/BoardSocGsim0.cpp', 'model/BoardSocGsim0.o']
    model_hashes = {name: sha(reference / name) for name in needed}
    if any(prior['artifacts'].get(name) != digest for name, digest in model_hashes.items()):
        raise RuntimeError('reference model artifact changed')
    for name, digest in prior['inputs'].items():
        if name.startswith('simulator/gsim/harness/') and sha(common.ROOT / name) != digest:
            raise RuntimeError('reference harness input differs: ' + name)
    out = common.BUILD / a.tag
    out.mkdir(parents=True, exist_ok=False)
    inputs = [Path(__file__), common.HERE / 'payloads/board_memory_independent.c',
        common.ROOT / 'fpga/firmware/ddr_bench.c', common.ROOT / 'fpga/firmware/board_memory.h',
        common.ROOT / 'fpga/firmware/sample_start.S', common.ROOT / 'fpga/firmware/sample_app.ld',
        *sorted((common.HERE / 'harness').glob('*.h')), common.HERE / 'harness/board_boot.cpp',
        common.HERE / 'harness/board_memory_steady.cpp']
    hashes = lambda: {str(p.relative_to(common.ROOT)): sha(p) for p in inputs}
    frozen = hashes()
    report = {'status': 'RUNNING', 'scope': 'frozen exact reference only', 'source_commit': prior['git_head'],
        'reference_receipt': str(reference / 'receipt.json'), 'reference_receipt_sha256': sha(reference / 'receipt.json'),
        'model_artifacts': model_hashes, 'inputs': frozen, 'synthesis': False, 'board_physics': False}
    try:
        f = common.ROOT / 'fpga/firmware'
        elf, image = out / 'independent.elf', out / 'independent.bin'
        common.run(['riscv64-unknown-elf-gcc', '-O2', '-march=rv64im_zicsr_zifencei', '-mabi=lp64',
            '-mcmodel=medany', '-mno-relax', '-msmall-data-limit=0', '-ffreestanding', '-fno-builtin',
            '-fno-stack-protector', '-nostdlib', '-nostartfiles', '-Wl,--no-relax', '-Wl,--gc-sections',
            '-ffunction-sections', '-fdata-sections', '-DCPU_HZ=100000000ULL', '-DUART_BAUD=460800',
            '-Wl,--defsym=BOARD_RAM_BYTES=2147483648', '-Wl,--defsym=BOARD_MONITOR_BASE=4294934528',
            '-T', f / 'sample_app.ld', f / 'sample_start.S', common.HERE / 'payloads/board_memory_independent.c',
            '-lgcc', '-o', elf], log=out / 'firmware-build.log')
        common.run(['riscv64-unknown-elf-objcopy', '-O', 'binary', elf, image], log=out / 'objcopy.log')
        dis = subprocess.check_output(['riscv64-unknown-elf-objdump', '-d', elf], text=True)
        (out / 'independent.dis').write_text(dis)
        def marker(name):
            block = dis.split('<' + name + '>:', 1)[1].split('\n\n', 1)[0]
            matches = re.findall(r'^\s*([0-9a-f]+):.*\brdtime\b', block, re.M)
            if len(matches) != 1:
                raise RuntimeError('unique rdtime marker missing: ' + name)
            return int(matches[0], 16)
        report['markers'] = {name: marker(name) for name in ('steady_start', 'steady_stop')}
        flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
        defines = ['-DUART_DIVISOR=1', '-DBOARD_CPU_HZ=100000000', '-DBOARD_UART_BAUD=460800',
            '-DUART_EXTRA_STOP_BITS=0', '-DDDR_MODEL=1', '-DBOARD_DDR_BYTES=2147483648ULL',
            '-DDDR_MULTI_ID_MODEL=1', '-DDDR_BENCHMARK_MODEL=1', '-DDDR_READ_CREDITS=8',
            '-DDDR_READ_LATENCY=32', '-DDDR_READ_BEAT_GAP=1', '-DBOARD_CYCLE_LIMIT=12000000ULL',
            '-DMODEL_MSHRS=2', '-DINDEPENDENT_LINE_KERNEL=1',
            '-DSTEADY_START_PC=' + str(report['markers']['steady_start']) + 'ULL',
            '-DSTEADY_STOP_PC=' + str(report['markers']['steady_stop']) + 'ULL']
        report['compile_flags'] = flags + defines
        cxx, compiler = common.compiler()
        report['compiler'] = compiler
        common.run([cxx, *flags, *defines, '-I' + str(reference / 'model'),
            common.HERE / 'harness/board_memory_steady.cpp', reference / 'model/BoardSocGsim0.o',
            '-ldl', '-o', out / 'run'], log=out / 'harness-link.log')
        common.run([out / 'run', image], env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'},
            log=out / 'test.log', timeout=900)
        text = (out / 'test.log').read_text()
        for anchor in ('BOARD_MEMORY_STEADY_PASS', 'INDEPENDENT_LINES',
            'STEADY_ORACLE_SENSITIVITY mutation_detected=1 restored_verified=1 DUT_fault_injection=0'):
            if anchor not in text:
                raise RuntimeError('missing acceptance marker: ' + anchor)
        report['measurements'] = [line for line in text.splitlines() if line.startswith(
            ('INDEPENDENT_LINES', 'BOARD_IPC', 'STEADY_AXI', 'BOARD_MEMORY_STEADY_PASS'))]
        report['status'] = 'PASS_FROZEN_REFERENCE_INDEPENDENT_LINES'
    except Exception as e:
        report['status'] = 'FAIL'; report['error'] = str(e); raise
    finally:
        if hashes() != frozen or any(sha(reference / name) != digest for name, digest in model_hashes.items()):
            report['status'] = 'FAIL_INPUT_CHANGED'
        report['artifacts'] = {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file() and p.name != 'receipt.json'}
        (out / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'measurements': report.get('measurements')}))


if __name__ == '__main__':
    main()
