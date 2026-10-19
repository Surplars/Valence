#!/usr/bin/env python3
"""Bounded shared-ROM clock checks; existing tools/sources only, no simulator."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cc', default='cc')
    parser.add_argument('--prefix', default='riscv64-unknown-elf-')
    parser.add_argument('--build-rom', action='store_true', help='build twice and compare the entire full-featured ROM')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(out).free < 4 * 1024**3:
        raise RuntimeError('less than 4 GiB free; refusing builds')
    (out / 'receipt.json').write_text(json.dumps(dict(status='running')) + '\n')
    env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}
    def run(command, name):
        with (out / (name + '.log')).open('w') as log:
            try:
                subprocess.run(list(map(str, command)), env=env, stdout=log,
                               stderr=subprocess.STDOUT, check=True, timeout=120)
            except (OSError, subprocess.SubprocessError) as error:
                (out / 'receipt.json').write_text(json.dumps(dict(status='failed', step=name,
                                                               failure=str(error))) + '\n')
                raise
    flags = ['-std=c11', '-O2', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
    run([sys.executable, '-m', 'unittest', 'discover', '-s', HERE, '-p', 'test_firmware_clocks.py', '-v'], 'config')
    run([args.cc, *flags, '-Wall', '-Wextra', '-Werror', HERE / 'test_board_clocks.c',
         HERE / 'crc32.c', '-o', out / 'clocks-native'], 'clocks-compile')
    run([out / 'clocks-native'], 'clocks-native')
    # Exercise the official CRC algorithm and strict >10 second gate at 250 MHz.
    # This is a host oracle, never a CoreMark performance result.
    core = ROOT / 'simulator/build/coremark-src'
    from build_monitor_diag import MD5
    for name, expected in MD5.items():
        if not (core / name).is_file() or hashlib.md5((core / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('missing/modified pinned official CoreMark: ' + str(core / name))
    cmflags = [*flags, '-DMONITOR_DIAGNOSTIC', '-DDIAGNOSTIC_PORT_TEST',
               '-DTIMEBASE_HZ=250000000', '-DBOARD_CPU_CLOCK_HZ=300000000ULL',
               '-DCOREMARK_COMPILER_VERSION="native oracle only"',
               '-I' + str(HERE), '-I' + str(HERE / 'coremark_port'), '-I' + str(core)]
    objects = []
    for name in ('core_main', 'core_list_join', 'core_matrix', 'core_state', 'core_util'):
        obj = out / (name + '.o')
        run([args.cc, *cmflags, *(['-Dmain=coremark_main'] if name == 'core_main' else []),
             '-c', core / (name + '.c'), '-o', obj], name)
        objects.append(obj)
    run([args.cc, *cmflags, HERE / 'coremark_port/core_portme.c', HERE / 'test_monitor_coremark.c',
         *objects, '-o', out / 'coremark-native'], 'coremark-link')
    run([out / 'coremark-native'], 'coremark-native')
    domain_flags = [*flags, '-DTIMEBASE_HZ=250000000', '-DBOARD_CPU_CLOCK_HZ=100000000ULL',
                    '-I' + str(HERE / 'coremark_port'), '-I' + str(core)]
    for name, inputs in (
            ('netboot', ['test_netboot_board.c', 'netboot.c', 'crc32.c']),
            ('diagnostic', ['test_monitor_diagnostics.c']),
            ('ddr-bench', ['tests/ddr_bench_host.c'])):
        run([args.cc, *domain_flags, *(HERE / name for name in inputs),
             '-o', out / (name + '-native')], name + '-compile')
        run([out / (name + '-native')], name + '-native')
    receipt = dict(status='passed', scope='host software/configuration and optional target link only',
                   cmu_profiles_same_native_binary=2, arithmetic_cases=135, cmu_negative_cases=8,
                   menu_cases_per_profile=47, coremark_formal_boundary_and_crc_cases=6,
                   timebase_hz=250000000, netboot_mmio_cases=32, netboot_posted_rx_cases=22,
                   diagnostic_cases=11, ddr_kernel_units_passed=True, physical_timing_verified=False,
                   board_verified=False, linux_built=False, hardware_simulation=False)
    if args.build_rom:
        for cpu in (100000000, 300000000):
            if shutil.disk_usage(out).free < 4 * 1024**3:
                raise RuntimeError('less than 4 GiB free; refusing next build')
            run([sys.executable, HERE / 'build.py', '--out', out / str(cpu), '--prefix', args.prefix,
                 '--common-platform', '--cpu-hz', str(cpu), '--boot-menu', '--netboot', '--netboot-posted-rx',
                 '--jtag-download', '--crc-mode', 'slice2', '--ddr', '--ddr-bytes', '0x80000000',
                 '--uart-reference-hz', '7372800', '--uart-baud', '460800'], 'rom-' + str(cpu))
        first, second = (out / str(cpu) for cpu in (100000000, 300000000))
        for artifact in ('bootrom.bin', 'monitor-diagnostic.bin', 'bootrom.coe', 'bootrom.even.hex', 'bootrom.odd.hex'):
            if (first / artifact).read_bytes() != (second / artifact).read_bytes():
                raise RuntimeError('CPU profile changed common artifact: ' + artifact)
        data = (first / 'bootrom.bin').read_bytes()
        contract = json.loads((first / 'bootrom-contract.json').read_text())
        assert contract == json.loads((second / 'bootrom-contract.json').read_text())
        assert len(data) <= 128 * 1024 and contract['cpu_hz'] is None
        receipt.update(rom_bytes=len(data), rom_capacity_bytes=128*1024,
                       rom_sha256=hashlib.sha256(data).hexdigest(), full_rom_byte_identical=True,
                       contract=contract)
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
