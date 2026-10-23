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
    p.add_argument('--scratch-bytes', type=int, default=65536)
    a = p.parse_args()
    if not 65536 <= a.scratch_bytes <= 262144 or a.scratch_bytes % 64:
        p.error('scratch must be64..256KiB, multiple of64')
    a.out.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parent
    elf = a.out / 'dvfs_roundtrip.elf'
    flags = ['-march=rv64im_zicsr_zifencei', '-mabi=lp64', '-mcmodel=medany', '-mno-relax',
             '-msmall-data-limit=0', '-Os', '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
             '-nostdlib', '-nostartfiles', '-Wall', '-Wextra', '-Werror', '-Wl,--no-relax',
             f'-DDVFS_SCRATCH_BYTES={a.scratch_bytes}', f'-T{source / "dvfs_roundtrip.ld"}',
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
                    timebase_hz=250000000, rate_abi=2, telemetry_abi=1,
                    targets_hz=[[50000000,50000000],[195000000,50000000],[195000000,155000000],
                                [195000000,50000000],[50000000,50000000]],
                    packed_profiles={'cpu195':0x05270a,'fabric155':0x0a3e0a,'boot50':0x14280a},
                    physical_timing_qualified=False, board_tested=False, flags=flags,
                    sources={n:hashlib.sha256((source/n).read_bytes()).hexdigest() for n in
                             ['dvfs_roundtrip.c','dvfs_roundtrip.h','dvfs_roundtrip.ld','sample_start.S','valence_clock.h']})
    (a.out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('RAM_DVFS_BUILD_PASS output='+str(a.out))


if __name__ == '__main__':
    main()
