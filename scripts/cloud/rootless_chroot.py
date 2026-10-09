#!/usr/bin/env python3
"""Run Debian RV64 package tools without chroot, ptrace, mounts or binfmt changes.

The caller must run under workspace fakeroot-tcp. The same metadata server is
used by the guest library and by the native archive writer. This is a build-time
userspace tool, not a security boundary or a Valence runtime qualification.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = (ROOT / 'simulator/build/cloud-linux-image').resolve()


def main():
    if len(sys.argv) < 3 or not os.environ.get('FAKEROOTKEY'):
        raise SystemExit('Usage under fakeroot-tcp: rootless_chroot.py ROOT COMMAND [ARG...]')
    root = Path(sys.argv[1]).resolve()
    if (ROOT / 'build/fpga').resolve() not in root.parents:
        raise SystemExit('Only this isolated build root is allowed')
    staged = root / '.valence-build-tools'
    staged.mkdir(exist_ok=True)
    for relative, name in (
        ('usr/lib/riscv64-linux-gnu/libfakeroot/libfakeroot-tcp.so', 'libfakeroot-tcp.so'),
        ('usr/lib/riscv64-linux-gnu/fakechroot/libfakechroot.so', 'libfakechroot.so')):
        source = BASE / 'probe-root' / relative
        target = staged / name
        if not target.exists() or target.read_bytes() != source.read_bytes():
            shutil.copyfile(source, target)
    command = sys.argv[2:]
    if not command[0].startswith('/'):
        raise SystemExit('Target command must be absolute')
    target = root / command[0].lstrip('/')
    if target.read_bytes()[:2] == b'#!':
        first = target.read_text().splitlines()[0][2:].strip().split()
        command = [*first, *command]
        target = root / command[0].lstrip('/')
    qemu = BASE / 'sysroot/usr/bin/qemu-riscv64'
    env = {**os.environ, 'QEMU_LD_PREFIX': str(root), 'FAKEROOTDONTTRYCHOWN': '1'}
    # Mounting and ldconfig's privileged chroot are unnecessary during userspace
    # package setup. Keep real target binaries intact; no fake wrapper is shipped.
    # Final loader resolution is checked without any generated ld.so.cache.
    substitutions = ':'.join(path + '=/usr/bin/true' for path in (
        '/bin/mount', '/usr/bin/mount', '/bin/umount', '/usr/bin/umount',
        '/sbin/ldconfig', '/usr/sbin/ldconfig'))
    settings = {
        'LD_PRELOAD': '/.valence-build-tools/libfakeroot-tcp.so:/.valence-build-tools/libfakechroot.so',
        'LD_LIBRARY_PATH': '/usr/lib/riscv64-linux-gnu:/lib/riscv64-linux-gnu',
        'FAKECHROOT_BASE': str(root), 'FAKECHROOT_ELFLOADER': str(qemu),
        'FAKECHROOT': 'true', 'FAKECHROOT_EXCLUDE_PATH': '/dev:/proc:/sys',
        'FAKECHROOT_CMD_SUBST': substitutions,
        'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        'DEBIAN_FRONTEND': 'noninteractive', 'LC_ALL': 'C', 'HOME': '/root',
        'DEBOOTSTRAP_DIR': '/debootstrap',
    }
    args = [str(qemu), '-L', str(root)]
    for key, value in settings.items():
        args += ['-E', key + '=' + value]
    args += [str(target), *command[1:]]
    result = subprocess.run(args, env=env, cwd=root)
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
