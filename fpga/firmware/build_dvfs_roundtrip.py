#!/usr/bin/env python3
"""Build manually triggered RAM-only DVFS board diagnostic, no ROM/IP changes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, default=Path('build/dvfs-roundtrip'))
    p.add_argument('--prefix', default='riscv64-unknown-elf-')
    p.add_argument('--cpu-hz', type=int, default=50000000)
    p.add_argument('--fabric-hz', type=int, default=50000000)
    p.add_argument('--cpu-parameters', type=lambda x:int(x,0), default=0)
    p.add_argument('--fabric-parameters', type=lambda x:int(x,0), default=0)
    p.add_argument('--scratch-bytes', type=int, default=65536)
    a = p.parse_args()
    if not 65536 <= a.scratch_bytes <= 262144 or a.scratch_bytes % 64:
        p.error('scratch must be64..256KiB, multiple of64')
    def parameters(hz):
        if not 10000000 <= hz <= 300000000:
            return 0
        if 50000000 <= hz <= 150000000 and hz % 5000000 == 0:
            o = 20 if hz <= 75000000 else 10
            return 10 | ((hz * o // 25000000) << 8) | (o << 16)
        for o in range(3,129):
            for m in range(32,63):
                if 25000000*m == hz*o:
                    return 10 | (m << 8) | (o << 16)
        return 0
    if a.fabric_hz > 250000000 or not parameters(a.cpu_hz) or not parameters(a.fabric_hz):
        p.error('targets must have exact legal D10/M32..62/O3..128 solutions; fabric <=250MHz')
    def selected(hz, packed):
        if not packed:
            return parameters(hz)
        d,m,o=packed&255,(packed>>8)&255,(packed>>16)&255
        if (packed < 0 or packed >> 24 or d != 10 or not 32 <= m <= 62 or not 3 <= o <= 128
                or 250000000*m != hz*d*o or (hz==50000000 and packed!=0x14280a)):
            p.error('explicit tuple must exactly match Hz and D10/M32..62/O3..128; boot50 tuple is fixed')
        return packed
    cpu_parameters=selected(a.cpu_hz,a.cpu_parameters)
    fabric_parameters=selected(a.fabric_hz,a.fabric_parameters)
    a.out.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parent
    elf = a.out / 'dvfs_roundtrip.elf'
    flags = ['-march=rv64im_zicsr_zifencei', '-mabi=lp64', '-mcmodel=medany', '-mno-relax',
             '-msmall-data-limit=0', '-Os', '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
             '-nostdlib', '-nostartfiles', '-Wall', '-Wextra', '-Werror', '-Wl,--no-relax',
             f'-DDVFS_SCRATCH_BYTES={a.scratch_bytes}', f'-DDVFS_CPU_HZ={a.cpu_hz}U', f'-DDVFS_FABRIC_HZ={a.fabric_hz}U',
             f'-DDVFS_CPU_PARAMETERS={a.cpu_parameters}U', f'-DDVFS_FABRIC_PARAMETERS={a.fabric_parameters}U', f'-T{source / "dvfs_roundtrip.ld"}',
             f'-Wl,-Map,{a.out / "dvfs_roundtrip.map"}']
    subprocess.run([a.prefix+'gcc', *flags, str(source/'sample_start.S'),
                    str(source/'dvfs_roundtrip.c'), '-lgcc', '-o', str(elf)], check=True)
    binary = a.out / 'dvfs_roundtrip.bin'
    subprocess.run([a.prefix+'objcopy', '-O', 'binary', str(elf), str(binary)], check=True)
    subprocess.run([a.prefix+'size', str(elf)], check=True)
    symbols = subprocess.check_output([a.prefix+'nm', '-n', str(elf)], text=True)
    (a.out/'symbols.txt').write_text(symbols)
    names = {'__scratch_start', '__scratch_end', '__bss_start', '__bss_end', '__app_stack_top', 'scratch', 'sweep', 'backup'}
    addresses = {line.split()[2]: int(line.split()[0],16) for line in symbols.splitlines()
                 if len(line.split())==3 and line.split()[2] in names}
    artifacts = {f.name: {'bytes': f.stat().st_size, 'sha256': hashlib.sha256(f.read_bytes()).hexdigest()}
                 for f in (elf,binary)}
    manifest = dict(schema=1, entry=0x80200000, reserved_start=0x80200000, reserved_end=0x80300000,
                    scratch_bytes=a.scratch_bytes, addresses=addresses, artifacts=artifacts,
                    manual_trigger='r', automatic_frequency_change=False, requires_rom_update=False,
                    target_cpu_hz=a.cpu_hz, target_fabric_hz=a.fabric_hz,
                    explicit_parameters=bool(a.cpu_parameters or a.fabric_parameters),
                    timebase_hz=250000000, rate_abi=2, telemetry_abi=1,
                    targets_hz=[[50000000,50000000],[a.cpu_hz,50000000],[a.cpu_hz,a.fabric_hz],
                                [a.cpu_hz,50000000],[50000000,50000000]],
                    packed_profiles={'cpu_target':cpu_parameters,'fabric_target':fabric_parameters,'boot50':0x14280a},
                    physical_timing_qualified=False, board_tested=False, flags=flags,
                    sources={n:hashlib.sha256((source/n).read_bytes()).hexdigest() for n in
                             ['dvfs_roundtrip.c','dvfs_roundtrip.h','dvfs_roundtrip.ld','sample_start.S','valence_clock.h','build_dvfs_roundtrip.py']})
    (a.out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('RAM_DVFS_BUILD_PASS output='+str(a.out))


if __name__ == '__main__':
    main()
