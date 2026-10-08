#!/usr/bin/env python3
"""Signed Debian 13 riscv64 minbase for Valence; no RTL/CAD/board writes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import datetime
import stat
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / 'simulator/gsim')]
from run import run

KEY_URL = ('https://deb.debian.org/debian/pool/main/d/debian-archive-keyring/'
           'debian-archive-keyring_2025.1_all.deb')
PACKAGES = ('ca-certificates', 'iproute2', 'iputils-ping', 'procps', 'ifupdown',
            'kmod', 'util-linux', 'login', 'ethtool', 'iperf3', 'strace',
            'tcpdump', 'net-tools')
LEGACY_LABEL = 'Valence Debian 13 riscv64 minbase, RAM-only serial bring-up, no automatic GMAC'
LABEL = 'OpenIon Valence VL100 Debian 13 riscv64 minbase, RAM-only, automatic GMAC, repaired bit required'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_output(path):
    path = path.resolve()
    allowed = (ROOT / 'build/fpga').resolve()
    if allowed not in path.parents or path == allowed or ' ' in str(path):
        raise RuntimeError('output must be a distinct child of build/fpga without spaces')
    return path


def copy(source, target, mode=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    if mode is not None:
        target.chmod(mode)


def archive_paths(rootfs, extra_excluded=()):
    """Omit build caches and retired custom tools, even from an older seed.

    Leave source roots and completed seed archives untouched. Debian-managed
    /usr/bin packages are outside the retired /usr/local tool's scope.
    """
    excluded = ('debootstrap', '.valence-build-tools', 'var/cache/apt/archives', 'var/lib/apt/lists',
                'usr/local/bin/fastfetch', 'usr/share/doc/valence/fastfetch',
                *extra_excluded)
    paths = ['.']
    for path in rootfs.rglob('*'):
        relative = path.relative_to(rootfs).as_posix()
        if not any(relative == prefix or relative.startswith(prefix + '/') for prefix in excluded):
            paths.append('./' + relative)
    return sorted(paths)


def bootstrap(args, output):
    if os.geteuid() != 0:
        raise RuntimeError('bootstrap requires WSL root; use wsl -u root, not Windows admin tools')
    for tool in ('debootstrap', 'qemu-riscv64-static', 'curl', 'dpkg-deb', 'chroot'):
        if not shutil.which(tool):
            raise RuntimeError('missing bootstrap dependency: ' + tool)
    output.mkdir(parents=True, exist_ok=False)
    rootfs = output / 'rootfs'
    identity = {'label': LABEL, 'suite': 'trixie', 'architecture': 'riscv64',
                'variant': 'minbase', 'include': list(PACKAGES), 'mirror': args.mirror,
                'key_url': KEY_URL, 'stage': 'bootstrapping', 'on_board_verified': False}
    (output / 'rootfs-build.json').write_text(json.dumps(identity, indent=2) + '\n')
    key_deb = output / 'debian-archive-keyring_2025.1_all.deb'
    run(['curl', '--fail', '--location', '--retry', '2', '--connect-timeout', '20',
         '--max-time', '120', '--output', key_deb, KEY_URL], log=output / 'key-download.log')
    tools = output / 'build-keyring'
    run(['dpkg-deb', '-x', key_deb, tools])
    keyring = tools / 'usr/share/keyrings/debian-archive-keyring.gpg'
    if not keyring.is_file():
        raise RuntimeError('official keyring package missing expected keyring')
    # Register only the official RISC-V format, not every foreign architecture.
    run(['/usr/lib/systemd/systemd-binfmt', '/usr/lib/binfmt.d/qemu-riscv64.conf'],
        log=output / 'binfmt.log')
    status = Path('/proc/sys/fs/binfmt_misc/qemu-riscv64').read_text()
    if 'enabled' not in status or 'flags:' not in status or 'F' not in status.split('flags:', 1)[1].splitlines()[0]:
        raise RuntimeError('fixed-interpreter riscv64 binfmt not enabled for chroot')
    (output / 'binfmt-status.txt').write_text(status)
    # Scoped to this build; do not change the host's global wget configuration.
    copy(HERE / 'wgetrc', output / 'wgetrc', 0o644)
    env = {**os.environ, 'DEBIAN_FRONTEND': 'noninteractive', 'LC_ALL': 'C',
           'WGETRC': str(output / 'wgetrc')}
    run(['debootstrap', '--arch=riscv64', '--variant=minbase', '--foreign',
         '--components=main', '--include=' + ','.join(PACKAGES), '--force-check-gpg',
         '--keyring=' + str(keyring), 'trixie', rootfs, args.mirror],
        log=output / 'bootstrap-first.log', timeout=1800, env=env)
    copy(HERE / 'policy-rc.d', rootfs / 'usr/sbin/policy-rc.d', 0o755)
    run(['chroot', rootfs, '/debootstrap/debootstrap', '--second-stage'],
        log=output / 'bootstrap-second.log', timeout=1800, env=env)
    run(['chroot', rootfs, '/bin/bash', '-c',
         'set -e; dpkg --print-architecture; getconf LONG_BIT; apt --version; dpkg --audit'],
        log=output / 'foreign-userland-check.log', timeout=60, env=env)
    package_list = subprocess.check_output(['chroot', str(rootfs), 'dpkg-query', '-W',
        '-f=${binary:Package}\t${Version}\t${Architecture}\n'], text=True, env=env)
    (output / 'packages.tsv').write_text(package_list)
    if 'VERSION_CODENAME=trixie' not in (rootfs / 'etc/os-release').read_text():
        raise RuntimeError('bootstrap is not Debian trixie')
    identity.update(stage='bootstrapped', key_package_sha256=sha(key_deb),
                    keyring_sha256=sha(keyring), packages_sha256=sha(output / 'packages.tsv'),
                    host_qemu_used_only_for_package_setup=True,
                    valence_isa_or_linux_runtime_verified=False)
    (output / 'rootfs-build.json').write_text(json.dumps(identity, indent=2) + '\n')
    print('DEBIAN_RISCV64_BOOTSTRAPPED ' + str(rootfs), flush=True)


def rootless_runner(args, require_qemu=False):
    """Validate opt-in runner requirements before modifying a private rootfs."""
    runner = getattr(args, 'rootless_chroot', None)
    if runner is None:
        return None
    if not os.environ.get('FAKEROOTKEY'):
        raise RuntimeError('Rootless packing requires caller-owned persistent fakeroot metadata')
    runner = Path(runner).resolve()
    if not runner.is_file() or not os.access(runner, os.X_OK):
        raise RuntimeError('Rootless runner must be an existing executable')
    if require_qemu:
        qemu = getattr(args, 'qemu_user', None)
        if qemu is None or not Path(qemu).is_file() or not os.access(qemu, os.X_OK):
            raise RuntimeError('--rootless-chroot requires an existing executable --qemu-user')
    return str(runner)


def pack(args, output):
    rootless_runner(args, require_qemu=True)
    marker = output / 'rootfs-build.json'
    identity = json.loads(marker.read_text())
    stages = ('bootstrapped', 'packed') if args.update_packed else ('bootstrapped',)
    if identity.get('label') not in (LABEL, LEGACY_LABEL) or identity.get('stage') not in stages:
        raise RuntimeError('pack requires this builder\'s completed bootstrap')
    if args.update_packed:
        generation = args.generation or 'autonet'
        if not re.fullmatch('[a-zA-Z0-9_-]+', generation):
            raise RuntimeError('unsafe rootfs generation')
        if (output / ('rootfs-build-' + generation + '.json')).exists():
            raise RuntimeError('Never overwrite a completed automatic-network rootfs record')
        if sha(output / identity['archive']['path']) != identity['archive']['sha256']:
            raise RuntimeError('Existing packed rootfs archive drift')
        identity['source_bootstrap_record_sha256'] = sha(marker)
        marker = output / ('rootfs-build-' + generation + '.json')
    rootfs = output / 'rootfs'
    baseline = args.baseline.resolve()
    manifest = json.loads((baseline / 'manifest.json').read_text())
    if args.kernel_build is None:
        raise RuntimeError('pack requires --kernel-build with matched compiled VL100 modules')
    kernel_build = validate_output(args.kernel_build)
    kernel_record = json.loads((kernel_build / 'kernel-build.json').read_text())
    if kernel_record.get('stage') != 'kernel_and_modules_ready':
        raise RuntimeError('kernel/module stage is incomplete')
    version = kernel_record['linux_version']
    if '/' in version or '..' in version or not version:
        raise RuntimeError('Invalid kernel release')
    modules_dir = rootfs / 'usr/lib/modules' / version
    for name, expected in kernel_record['modules'].items():
        source = kernel_build / 'module' / name
        if sha(source) != expected:
            raise RuntimeError('matched module drift: ' + name)
        copy(source, modules_dir / 'extra' / name, 0o644)
    for name in ('modules.builtin', 'modules.builtin.modinfo'):
        copy(kernel_build / 'linux' / name, modules_dir / name, 0o644)
    # Every optional module in this minimal kernel is external, built above.
    (modules_dir / 'modules.order').write_text(''.join('extra/' + name + '\n' for name in kernel_record['modules']))
    run(['depmod', '-b', rootfs, '-F', kernel_build / 'linux/System.map', version],
        log=output / 'depmod.log')
    if 'WARNING' in (output / 'depmod.log').read_text():
        raise RuntimeError('depmod warning; module dependencies not ready')
    for name in ('coremark', 'fpu-test', 'net-bench'):
        source = baseline / 'apps' / name
        if sha(source) != manifest['files'][name]['sha256']:
            raise RuntimeError('baseline app drift: ' + name)
        copy(source, rootfs / 'usr/local/bin' / name, 0o755)
    copy(baseline / 'userland/busybox/busybox', rootfs / 'usr/lib/valence/busybox', 0o755)
    user_manifest = json.loads((baseline / 'userland/manifest.json').read_text())
    if sha(rootfs / 'usr/lib/valence/busybox') != user_manifest['busybox_sha256']:
        raise RuntimeError('BusyBox init helper provenance mismatch')
    for name, relative in (('busybox', 'busybox-1.37.0/LICENSE'),
            ('musl', 'musl-1.2.5/COPYRIGHT'),
            ('coremark', 'coremark-src/LICENSE.md')):
        copy(ROOT / 'simulator/build' / relative, rootfs / 'usr/share/doc/valence' / name, 0o644)
    for name in ('net-status', 'boot-time'):
        copy(HERE.parent / 'linux_net' / name, rootfs / 'usr/local/sbin' / name, 0o755)
    copy(HERE / 'dma-bench', rootfs / 'usr/local/sbin/dma-bench', 0o755)
    for source, target, mode in (('init', 'init', 0o755), ('interfaces', 'etc/network/interfaces', 0o644),
            ('valence-net-up', 'usr/local/sbin/valence-net-up', 0o755),
            ('profile', 'etc/profile.d/valence.sh', 0o644), ('sources.list', 'etc/apt/sources.list', 0o644),
            ('inittab', 'etc/inittab', 0o644), ('valence-release', 'etc/valence-release', 0o644),
            ('valence-info', 'usr/local/sbin/valence-info', 0o755),
            ('resolv.conf', 'etc/resolv.conf', 0o644)):
        copy(HERE / source, rootfs / target, mode)
    (rootfs / 'etc/valence').mkdir(exist_ok=True)
    (rootfs / 'etc/valence/build-time').write_text(datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S') + '\n')
    (rootfs / 'etc/hostname').write_text('valence\n')
    release = rootfs / 'etc/valence-release'
    release.write_text(release.read_text().replace('VALENCE_RAM_BYTES=536870912',
                      'VALENCE_RAM_BYTES=' + str(kernel_record['memory_bytes'])))
    (rootfs / 'etc/hosts').write_text('127.0.0.1 localhost\n127.0.1.1 valence\n')
    # The built-in image must provide a console before /init mounts devtmpfs.
    console = rootfs / 'dev/console'
    metadata = console.lstat()
    if not stat.S_ISCHR(metadata.st_mode) or metadata.st_rdev != os.makedev(5, 1):
        raise RuntimeError('rootfs console is not character device 5:1')
    run(([args.qemu_user] if args.rootless_chroot else []) +
        [rootfs / 'usr/lib/valence/busybox', 'sh', '-n', rootfs / 'init'],
        log=output / 'init-syntax.log')
    for module in kernel_record['modules']:
        run([args.rootless_chroot or 'chroot', rootfs, '/sbin/modprobe', '--show-depends', '--set-version', version,
             module.removesuffix('.ko')], log=output / (module + '-modprobe-dry-run.log'))
    # Do not ship bootstrap/QEMU helpers, downloaded .debs, or package indices.
    # Do not delete them: preserve bootstrap evidence and package setup outputs.
    paths = archive_paths(rootfs)
    payload_bytes = sum((rootfs / path).stat().st_size for path in paths
                        if not (rootfs / path).is_symlink() and (rootfs / path).is_file())
    if payload_bytes > 240 * 1024 * 1024:
        raise RuntimeError('rootfs exceeds conservative 512 MiB RAM bring-up budget')
    cpio = output / ('debian13-riscv64-minbase-' + generation + '.cpio' if args.update_packed
                     else 'debian13-riscv64-minbase.cpio')
    with cpio.open('wb') as stream:
        subprocess.run(['cpio', '--null', '-o', '-H', 'newc', '--reproducible'], cwd=rootfs,
                       input=b'\0'.join(p.encode() for p in paths) + b'\0', stdout=stream, check=True)
    compressed = cpio.with_suffix('.cpio.gz')
    with compressed.open('wb') as stream:
        subprocess.run(['gzip', '-n', '-6', '-c', str(cpio)], stdout=stream, check=True)
    # procps needs /proc even for --version. Use a private mount namespace:
    # the read-only proc mount disappears when this check exits; never ship it.
    check = ('set -e; command -v login; dpkg --print-architecture; ip -V; ps --version; apt --version; '
             'ethtool --version; iperf3 --version; strace -V; tcpdump --version; dpkg --audit')
    check_log = output / 'packed-userland-check.log'
    if check_log.exists():
        copy(check_log, output / ('packed-userland-prior-' + str(time.time_ns()) + '.log'))
    if args.rootless_chroot:
        run([args.rootless_chroot, rootfs, '/bin/bash', '-c', check], log=check_log, timeout=60)
    else:
        run(['unshare', '--mount', '--propagation', 'private', '/bin/sh', '-c',
             'mount -t proc -o ro,nosuid,nodev,noexec proc "$1/proc"; exec chroot "$1" /bin/bash -c "$2"',
             'debian-userland-check', rootfs, check], log=check_log, timeout=60)
    identity.update(stage='packed', rootfs_file_bytes=payload_bytes,
                    archive={'path': cpio.name, 'bytes': cpio.stat().st_size, 'sha256': sha(cpio)},
                    compressed={'path': compressed.name, 'bytes': compressed.stat().st_size,
                                'sha256': sha(compressed)}, network_auto_enable=True, label=LABEL,
                    init='lightweight Valence /init, serial-only root autologin; not systemd',
                    memory_bytes=kernel_record['memory_bytes'], cpu_hz=100000000, uart_baud=460800,
                    vendor='OpenIon', soc='VL100', cpu='Orbital-A1',
                    kernel_build=str(kernel_build), kernel_version=version,
                    modules=kernel_record['modules'], module_autoload=('valence_soc', 'valence_aia', 'valence_cmu', 'valence_dma', 'valence_gmac'),
                    gmac_manual_load=False, require_repaired_bit=True,
                    baseline_manifest_sha256=sha(baseline / 'manifest.json'),
                    matched_custom_kernel_required=True, persistent_storage=False,
                    sources={p.name: sha(p) for p in HERE.iterdir() if p.is_file()})
    marker.write_text(json.dumps(identity, indent=2) + '\n')
    print('DEBIAN_RISCV64_ROOTFS_READY ' + str(compressed), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('bootstrap', 'pack'), required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mirror', default='https://deb.debian.org/debian')
    parser.add_argument('--baseline', type=Path, default=ROOT / 'build/fpga/linux-net-rv64gc-20261006-r3')
    parser.add_argument('--kernel-build', type=Path, help='matching completed kernel/module build output')
    parser.add_argument('--rootless-chroot', type=Path, help='explicit userspace runner; caller must preserve fakeroot metadata')
    parser.add_argument('--qemu-user', type=Path, help='QEMU-user for the static shell syntax check only')
    parser.add_argument('--update-packed', action='store_true', help='create a separate automatic-network archive/record from the unpublished manual-network draft')
    parser.add_argument('--generation', help='distinct new archive/receipt name when updating a packed draft')
    args = parser.parse_args()
    destination = validate_output(args.out)
    (bootstrap if args.stage == 'bootstrap' else pack)(args, destination)
