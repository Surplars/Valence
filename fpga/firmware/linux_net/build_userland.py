#!/usr/bin/env python3
"""Isolated RV64GC/lp64d static musl + BusyBox; never changes old userland."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'simulator/gsim'))
from run import run

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def verify(path):
    header = subprocess.check_output(['riscv64-unknown-elf-readelf', '-h', path], text=True)
    attrs = subprocess.check_output(['riscv64-unknown-elf-readelf', '-A', path], text=True)
    program = subprocess.check_output(['riscv64-unknown-elf-readelf', '-l', path], text=True)
    if 'double-float ABI' not in header or 'INTERP' in program:
        raise RuntimeError('Expected static lp64d ELF: ' + str(path))
    if not re.search(r'_f[0-9]', attrs) or not re.search(r'_d[0-9]', attrs) or re.search(r'_v[0-9]', attrs):
        raise RuntimeError('Expected scalar F/D ISA only: ' + attrs)

def build(output, jobs):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sources = ROOT / 'simulator/build'
    sysroot = output / 'sysroot'
    musl_out = output / 'musl'
    musl_out.mkdir(exist_ok=True)
    run([sources / 'musl-1.2.5/configure', '--target=riscv64-linux-musl', '--disable-shared',
         f'--prefix={sysroot}', f'--syslibdir={sysroot / "lib"}',
         'CC=riscv64-unknown-elf-gcc -march=rv64gc -mabi=lp64d', 'CFLAGS=-Os',
         'AR=riscv64-unknown-elf-ar', 'RANLIB=riscv64-unknown-elf-ranlib'],
        cwd=musl_out, log=output / 'musl-config.log')
    run(['make', f'-j{jobs}'], cwd=musl_out, log=output / 'musl-build.log', timeout=900)
    run(['make', 'install'], cwd=musl_out, log=output / 'musl-install.log')
    specs = sysroot / 'lib/musl-gcc.specs'
    content = subprocess.check_output(['sh', sources / 'musl-1.2.5/tools/musl-gcc.specs.sh',
        sysroot / 'include', sysroot / 'lib', sysroot / 'lib/ld-musl-riscv64.so.1'], text=True)
    specs.write_text(content.split('*esp_link:', 1)[0].rstrip().replace('Scrt1.o', 'crt1.o')
        .replace('crtbeginS.o', 'crtbegin.o').replace('crtendS.o', 'crtend.o') + '\n\n*lib:\n-lc\n\n')
    for name in ('linux', 'asm', 'asm-generic', 'mtd', 'scsi', 'sound', 'video', 'drm'):
        if not (sysroot / 'include' / name).exists():
            run(['cp', '-a', f'/usr/riscv64-linux-gnu/include/{name}', sysroot / 'include'])
    wrapper = output / 'riscv64-valence-gc-musl-gcc'
    wrapper.write_text('#!/bin/sh\nexec riscv64-unknown-elf-gcc -march=rv64gc -mabi=lp64d '
        f'-D__linux__=1 -D__unix__=1 -specs="{specs}" "$@"\n')
    wrapper.chmod(0o755)
    busy_out = output / 'busybox'
    busy_out.mkdir(exist_ok=True)
    make = ['make', f'O={busy_out}', 'ARCH=riscv', 'CROSS_COMPILE=riscv64-unknown-elf-', f'CC={wrapper}']
    run([*make, 'defconfig'], cwd=sources / 'busybox-1.37.0', log=output / 'busybox-config.log')
    enabled = ['STATIC', 'IP', 'IPADDR', 'IPLINK', 'IPROUTE', 'IPNEIGH', 'IFUP', 'IFDOWN',
        'FEATURE_IFUPDOWN_IP', 'FEATURE_IFUPDOWN_IPV4', 'FEATURE_IFUPDOWN_EXTERNAL_DHCP',
        'IFCONFIG', 'ROUTE', 'ARP', 'ARPING', 'PING', 'NETSTAT', 'UDHCPC', 'NSLOOKUP',
        'NC', 'NC_SERVER', 'NC_EXTRA', 'NC_110_COMPAT', 'WGET', 'HTTPD', 'INSMOD']
    disabled = ['PIE', 'TC', 'SHA1_HWACCEL', 'SHA256_HWACCEL']
    flags = [v for name in enabled for v in ('--enable', name)]
    flags += [v for name in disabled for v in ('--disable', name)]
    run([sources / 'linux/scripts/config', '--file', busy_out / '.config', *flags,
         '--set-str', 'EXTRA_CFLAGS', '-Os', '--set-str', 'EXTRA_LDFLAGS', '-static'])
    run([*make, f'-j{jobs}'], cwd=sources / 'busybox-1.37.0', log=output / 'busybox-build.log', timeout=900)
    run([*make, 'busybox.links'], cwd=sources / 'busybox-1.37.0', log=output / 'busybox-links.log')
    binary = busy_out / 'busybox'
    verify(binary)
    run(['riscv64-unknown-elf-strip', '--strip-unneeded', binary])
    config = (busy_out / '.config').read_text().splitlines()
    for name in enabled:
        if f'CONFIG_{name}=y' not in config:
            raise RuntimeError('BusyBox network option missing: ' + name)
    manifest = {'isa': 'rv64gc', 'abi': 'lp64d', 'libc': 'static musl 1.2.5',
        'network_options': enabled, 'busybox_sha256': sha(binary),
        'sources': {str(p.relative_to(ROOT)): sha(p) for p in (Path(__file__), sources / 'musl-1.2.5/COPYRIGHT',
            sources / 'busybox-1.37.0/LICENSE')}, 'board_verified': False}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('GC_USERLAND_READY ' + str(output), flush=True)
    return wrapper, binary

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=16)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    build(args.out, args.jobs)
