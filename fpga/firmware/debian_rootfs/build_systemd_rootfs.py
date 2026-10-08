#!/usr/bin/env python3
"""Upgrade a verified Debian RAM-root archive to systemd, in a new WSL output.

QEMU-user is used only for signed package setup, never as Valence verification.
Never touches RTL, CAD, the board, or a previously completed archive.
"""
import argparse
import datetime
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import shlex
import stat
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / 'simulator/gsim')]
from build_rootfs import sha, validate_output, copy, archive_paths
from run import run

PACKAGES = ('systemd', 'systemd-sysv', 'udev', 'dbus', 'libpam-systemd')
LABEL = 'OpenIon Valence VL100 Debian 13 systemd RAM-root, repaired netboot bit required'
MODULES = ('valence_soc.ko', 'valence_aia.ko', 'valence_cmu.ko', 'valence_dma.ko', 'valence_gmac.ko')
FILES = (
    ('systemd_init', 'init', 0o755),
    ('valence-platform-init', 'usr/local/libexec/valence-platform-init', 0o755),
    ('valence-ready', 'usr/local/libexec/valence-ready', 0o755),
    ('boot-diagnose', 'usr/local/sbin/boot-diagnose', 0o755),
    ('valence-platform.service', 'etc/systemd/system/valence-platform.service', 0o644),
    ('valence-ready.service', 'etc/systemd/system/valence-ready.service', 0o644),
    ('networking-valence.conf', 'etc/systemd/system/networking.service.d/valence.conf', 0o644),
    ('serial-autologin.conf', 'etc/systemd/system/serial-getty@hvc0.service.d/valence.conf', 0o644),
    ('journald-valence.conf', 'etc/systemd/journald.conf.d/valence.conf', 0o644),
    ('valence-driver-order.conf', 'etc/modprobe.d/valence-order.conf', 0o644),
)


def archive_names(blob):
    """Reject absolute/traversing entries before invoking cpio as root."""
    offset = 0
    names = []
    while offset + 110 <= len(blob):
        header = blob[offset:offset + 110]
        if header[:6] != b'070701':
            raise RuntimeError('Only a checked newc archive is supported')
        fields = [int(header[6 + i * 8:14 + i * 8], 16) for i in range(13)]
        size, namesize = fields[6], fields[11]
        if namesize < 1 or offset + 110 + namesize > len(blob):
            raise RuntimeError('Invalid newc filename size')
        raw = blob[offset + 110:offset + 110 + namesize]
        if raw[-1:] != b'\0' or b'\0' in raw[:-1]:
            raise RuntimeError('Invalid newc filename')
        name = raw[:-1].decode('utf-8')
        start = (offset + 110 + namesize + 3) & ~3
        if start + size > len(blob):
            raise RuntimeError('Truncated newc file data')
        if name == 'TRAILER!!!':
            return names
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or not name:
            raise RuntimeError('Unsafe newc path: ' + name)
        names.append(name)
        offset = (start + size + 3) & ~3
    raise RuntimeError('Missing newc trailer')


def require_root():
    if os.geteuid() != 0:
        raise RuntimeError('Use WSL root only for this isolated rootfs build')


def setup(args):
    require_root()
    out = validate_output(args.out)
    seed = validate_output(args.seed)
    if Path(args.seed_record).name != args.seed_record:
        raise RuntimeError('Seed record must be a basename')
    record_path = seed / args.seed_record
    record = json.loads(record_path.read_text())
    if record.get('stage') != 'packed' or record.get('architecture') != 'riscv64' or record.get('suite') != 'trixie':
        raise RuntimeError('Expected the verified Debian 13 riscv64 packed archive')
    source = seed / record['archive']['path']
    if source.parent.resolve() != seed or sha(source) != record['archive']['sha256']:
        raise RuntimeError('Seed archive path/digest mismatch')
    names = archive_names(source.read_bytes())
    if 'etc/os-release' not in names or 'init' not in names:
        raise RuntimeError('Seed archive is not a complete Debian root')
    out.mkdir(parents=True, exist_ok=False)
    rootfs = out / 'rootfs'
    rootfs.mkdir()
    identity = dict(label=LABEL, stage='restoring', suite='trixie', architecture='riscv64',
        init_system='systemd', seed_record_sha256=sha(record_path),
        seed_archive_sha256=record['archive']['sha256'],
        seed_signature_provenance={key: record.get(key) for key in
            ('key_package_sha256', 'keyring_sha256', 'packages_sha256', 'source_bootstrap_record_sha256')},
        host_qemu_used_only_for_package_setup=True, board_verified=False)
    (out / 'rootfs-build.json').write_text(json.dumps(identity, indent=2) + '\n')
    with source.open('rb') as stream, (out / 'restore.log').open('wb') as log:
        subprocess.run(['cpio', '--quiet', '--extract', '--make-directories',
                        '--preserve-modification-time', '--no-absolute-filenames'],
                       cwd=rootfs, stdin=stream, stdout=log, stderr=log, check=True)
    for tool in ('qemu-riscv64-static', 'chroot', 'systemctl', 'depmod'):
        if not shutil.which(tool):
            raise RuntimeError('Missing host setup tool: ' + tool)
    run(['/usr/lib/systemd/systemd-binfmt', '/usr/lib/binfmt.d/qemu-riscv64.conf'], log=out / 'binfmt.log')
    status = Path('/proc/sys/fs/binfmt_misc/qemu-riscv64').read_text()
    if 'enabled' not in status or 'F' not in status.split('flags:', 1)[1]:
        raise RuntimeError('Fixed-interpreter riscv64 package setup not available')
    copy(HERE / 'policy-rc.d', rootfs / 'usr/sbin/policy-rc.d', 0o755)
    resolv = rootfs / 'etc/resolv.conf'
    if resolv.is_symlink():
        raise RuntimeError('Refusing to overwrite a symlink DNS configuration')
    board_dns = resolv.read_bytes()
    # Scoped DNS override for signed apt downloads; board DNS is restored below.
    try:
        shutil.copyfile('/etc/resolv.conf', resolv)
        env = {**os.environ, 'DEBIAN_FRONTEND': 'noninteractive', 'LC_ALL': 'C'}
        run(['chroot', rootfs, 'apt-get', '-o', 'Acquire::Retries=2', 'update'],
            log=out / 'apt-update.log', env=env, timeout=600)
        run(['chroot', rootfs, 'apt-get', '-y', '--no-install-recommends', 'install', *PACKAGES],
            log=out / 'apt-install.log', env=env, timeout=1800)
        run(['chroot', rootfs, 'dpkg', '--audit'], log=out / 'dpkg-audit.log', env=env)
    finally:
        resolv.write_bytes(board_dns)
    identity['stage'] = 'packages_installed_pending_verify'
    (out / 'rootfs-build.json').write_text(json.dumps(identity, indent=2) + '\n')
    complete_setup(out, identity)


def finalize(args):
    """Resume only this builder's unfinished setup; never replace an archive."""
    require_root()
    out = validate_output(args.out)
    identity = json.loads((out / 'rootfs-build.json').read_text())
    if (identity.get('label') != LABEL or identity.get('init_system') != 'systemd'
            or identity.get('architecture') != 'riscv64' or identity.get('suite') != 'trixie'
            or identity.get('stage') not in ('restoring', 'packages_installed_pending_verify')
            or not identity.get('seed_archive_sha256') or not identity.get('seed_record_sha256')):
        raise RuntimeError('Only an identified, unfinished systemd setup can be resumed')
    rootfs = out / 'rootfs'
    if rootfs.is_symlink() or rootfs.resolve().parent != out or not (out / 'apt-install.log').is_file():
        raise RuntimeError('Missing private rootfs/package setup evidence')
    if (out / 'debian13-riscv64-systemd-vl100.cpio').exists():
        raise RuntimeError('Refusing to finalize a previously archived rootfs')
    complete_setup(out, identity)


def complete_setup(out, identity):
    rootfs = out / 'rootfs'
    audit = subprocess.check_output(['chroot', str(rootfs), 'dpkg', '--audit'], text=True)
    (out / 'dpkg-audit-final.log').write_text(audit)
    if audit.strip():
        raise RuntimeError('Target package database has unfinished/broken packages')
    selected = subprocess.check_output(['chroot', str(rootfs), 'dpkg-query', '-W',
        '-f=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Status}\n',
        *PACKAGES], text=True)
    rows = [line.split('\t') for line in selected.splitlines()]
    if (len(rows) != len(PACKAGES) or
            {row[0].split(':')[0] for row in rows} != set(PACKAGES) or
            any(len(row) != 4 or row[2] not in ('riscv64', 'all') or row[3] != 'installed' for row in rows)):
        raise RuntimeError('Required signed systemd packages are not fully installed')
    (out / 'systemd-packages.tsv').write_text(selected)
    package_list = subprocess.check_output(['chroot', str(rootfs), 'dpkg-query', '-W',
        '-f=${binary:Package}\t${Version}\t${Architecture}\n'], text=True)
    (out / 'packages.tsv').write_text(package_list)
    for source_name, target_name, mode in FILES:
        copy(HERE / source_name, rootfs / target_name, mode)
    copy(HERE / 'interfaces', rootfs / 'etc/network/interfaces', 0o644)
    copy(HERE.parent / 'linux_net/boot-time', rootfs / 'usr/local/sbin/boot-time', 0o755)
    # Empty machine-id permits fresh generation; no build-host identity is shipped.
    (rootfs / 'etc/machine-id').write_text('')
    (rootfs / 'etc/valence/build-time').write_text(
        datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S') + '\n')
    if (rootfs / 'etc/initrd-release').exists():
        raise RuntimeError('Final RAM-root must not advertise a transit initrd')
    run(['systemctl', '--root=' + str(rootfs), 'set-default', 'multi-user.target'], log=out / 'enable.log')
    run(['systemctl', '--root=' + str(rootfs), 'enable', 'valence-platform.service',
         'valence-ready.service', 'networking.service', 'serial-getty@hvc0.service'], log=out / 'enable-services.log')
    run(['systemctl', '--root=' + str(rootfs), 'mask', 'getty@tty1.service',
         'systemd-firstboot.service'], log=out / 'mask-services.log')
    # Parse Debian units with Debian's version, not Ubuntu's older host parser.
    # Static checking via QEMU-user does not start units or emulate the SoC.
    run(['chroot', rootfs, '/usr/bin/systemd-analyze', '--version'],
        log=out / 'unit-verifier-version.log')
    run(['chroot', rootfs, '/usr/bin/systemd-analyze', '--man=no', 'verify', 'valence-platform.service',
         'valence-ready.service', 'networking.service', 'serial-getty@hvc0.service'],
        log=out / 'units-verify-target.log')
    identity.update(stage='systemd_packages_ready', packages_sha256=sha(out / 'packages.tsv'),
        systemd_packages=list(PACKAGES), network_auto_enable=True,
        unit_verifier='target Debian systemd-analyze; static only, --man=no',
        sources={name: sha(HERE / name) for name, _, _ in FILES})
    (out / 'rootfs-build.json').write_text(json.dumps(identity, indent=2) + '\n')
    print('SYSTEMD_ROOTFS_PACKAGES_READY ' + str(out), flush=True)


def pack(args):
    require_root()
    out = validate_output(args.out)
    rootfs = out / 'rootfs'
    marker = out / 'rootfs-build.json'
    identity = json.loads(marker.read_text())
    if identity.get('stage') != 'systemd_packages_ready':
        raise RuntimeError('Setup must complete first; never overwrite a packed archive')
    kernel = validate_output(args.kernel_build)
    record = json.loads((kernel / 'kernel-build.json').read_text())
    if record.get('stage') != 'kernel_and_modules_ready' or record.get('init_system') != 'systemd':
        raise RuntimeError('Systemd requires this exact new kernel/module profile')
    version = record['linux_version']
    if '/' in version or '..' in version:
        raise RuntimeError('Unsafe module release')
    modules = rootfs / 'usr/lib/modules' / version
    for name in MODULES:
        source = kernel / 'module' / name
        if sha(source) != record['modules'][name]:
            raise RuntimeError('Compiled module drift: ' + name)
        copy(source, modules / 'extra' / name, 0o644)
    for name in ('modules.builtin', 'modules.builtin.modinfo'):
        copy(kernel / 'linux' / name, modules / name, 0o644)
    (modules / 'modules.order').write_text(''.join('extra/' + name + '\n' for name in MODULES))
    run(['depmod', '-b', rootfs, '-F', kernel / 'linux/System.map', version], log=out / 'depmod.log')
    if 'WARNING' in (out / 'depmod.log').read_text():
        raise RuntimeError('Module dependency warnings')
    binary = rootfs / 'usr/local/bin/mem-bench'
    run(['riscv64-linux-gnu-gcc', '-O2', '-march=rv64gc_zicsr_zifencei', '-mabi=lp64d',
         '-mstrict-align', '-Wall', '-Wextra', '-Werror', HERE / 'mem-bench.c', '-o', binary],
        log=out / 'mem-bench-build.log')
    # A private mount namespace ensures proc mounts never escape this build.
    check = ('set -e; /usr/lib/systemd/systemd --version; dpkg --audit; '
             f'modprobe --set-version {shlex.quote(version)} --show-depends valence_gmac; '
             'command -v agetty; command -v systemctl')
    run(['unshare', '--mount', '--propagation', 'private', '/bin/sh', '-c',
         'mount -t proc -o ro,nosuid,nodev,noexec proc "$1/proc"; exec chroot "$1" /bin/sh -c "$2"',
         'valence-systemd-check', rootfs, check], log=out / 'userland-check.log', timeout=90)
    paths = archive_paths(rootfs)
    payload_bytes = sum((rootfs / path).stat().st_size for path in paths
                        if not (rootfs / path).is_symlink() and (rootfs / path).is_file())
    if payload_bytes > 512 * 1024 * 1024:
        raise RuntimeError('Systemd rootfs exceeds conservative 2 GiB bring-up budget')
    console = (rootfs / 'dev/console').lstat()
    if not stat.S_ISCHR(console.st_mode) or console.st_rdev != os.makedev(5, 1):
        raise RuntimeError('Missing kernel pre-init console device')
    archive = out / 'debian13-riscv64-systemd-vl100.cpio'
    with archive.open('wb') as stream:
        subprocess.run(['cpio', '--null', '-o', '-H', 'newc', '--reproducible'], cwd=rootfs,
            input=b'\0'.join(p.encode() for p in paths) + b'\0', stdout=stream, check=True)
    compressed = archive.with_suffix('.cpio.gz')
    with compressed.open('wb') as stream:
        subprocess.run(['gzip', '-n', '-6', '-c', str(archive)], stdout=stream, check=True)
    identity.update(stage='packed', kernel_build=str(kernel), rootfs_file_bytes=payload_bytes,
        memory_bytes=record['memory_bytes'], cpu_hz=record['cpu_hz'], uart_baud=record['uart_baud'],
        init='Debian systemd PID 1; standard agetty, ifupdown, logind, volatile journal',
        archive=dict(path=archive.name, bytes=archive.stat().st_size, sha256=sha(archive)),
        compressed=dict(path=compressed.name, bytes=compressed.stat().st_size, sha256=sha(compressed)),
        modules=record['modules'], persistent_storage=False, required_repaired_bit=True,
        vendor='OpenIon', soc='VL100', cpu='Orbital-A1',
        static_unit_verify=True, cpu_or_board_runtime_verified=False,
        diagnostic_apps={'mem-bench': sha(binary)},
        pack_sources={name: sha(HERE / name) for name in
                      ('build_rootfs.py', 'build_systemd_rootfs.py')})
    marker.write_text(json.dumps(identity, indent=2) + '\n')
    print('SYSTEMD_DEBIAN_ROOTFS_PACKED_NOT_BOARD_VERIFIED ' + str(archive), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('setup', 'finalize', 'pack'), required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seed', type=Path)
    parser.add_argument('--seed-record', default='rootfs-build-netboot-drain-r1.json')
    parser.add_argument('--kernel-build', type=Path)
    args = parser.parse_args()
    if args.stage == 'setup' and args.seed is None or args.stage == 'pack' and args.kernel_build is None:
        parser.error('--setup requires --seed; --pack requires --kernel-build')
    {'setup': setup, 'finalize': finalize, 'pack': pack}[args.stage](args)
