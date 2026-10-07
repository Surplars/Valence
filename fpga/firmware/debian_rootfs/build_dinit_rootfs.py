#!/usr/bin/env python3
"""Pinned Dinit + verified Debian minbase RAM-root; no RTL/CAD/board writes."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ASSETS = HERE / 'dinit'
sys.path[:0] = [str(HERE), str(ROOT / 'simulator/gsim')]
from build_rootfs import sha, validate_output, copy
from build_systemd_rootfs import archive_names
from run import run

BINARIES = ('dinit', 'dinitctl', 'dinitcheck', 'dinit-shutdown')
SERVICES = ('boot', 'platform', 'network', 'ready', 'login-ready', 'serial-console')
LABEL = 'OpenIon VL100 Debian 13 / Dinit / LZ4 RAM-root; repaired netboot bit required'
FLAGS = '-Os -std=c++11 -fno-rtti -fno-plt'


def tools(args):
    source = validate_output(args.source)
    lock = json.loads((ASSETS / 'lock.json').read_text())
    revision = subprocess.check_output(['git', '-C', source, 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', source, 'status', '--porcelain', '--untracked-files=no'], text=True)
    if revision != lock['revision'] or dirty:
        raise RuntimeError('Dinit source must be the exact clean pinned upstream revision')
    out = validate_output(args.out)
    if (out / 'tools-build.json').exists():
        raise RuntimeError('Refusing to replace a completed tools build')
    out.mkdir(parents=True, exist_ok=args.finish_tools)
    flags = FLAGS + ' -march=rv64gc_zicsr_zifencei -mabi=lp64d -mstrict-align'
    for name, compiler, options in (('native', 'g++', FLAGS), ('riscv64', 'riscv64-linux-gnu-g++', flags)):
        tree = out / name
        if args.finish_tools:
            tracked = subprocess.check_output(['git', '-C', source, 'ls-files', '-z']).split(b'\0')
            for raw in tracked:
                if raw:
                    relative = raw.decode()
                    if sha(source / relative) != sha(tree / relative):
                        raise RuntimeError('Copied pinned source drift: ' + relative)
        else:
            shutil.copytree(source, tree, ignore=shutil.ignore_patterns('.git'))
            run(['./configure', '--platform=Linux', '--sbindir=/usr/sbin', '--enable-shutdown',
             '--shutdown-prefix=dinit-', '--disable-cgroups', '--disable-strip',
             '--default-auto-restart=never', 'CXX=' + compiler, 'CXX_FOR_BUILD=g++',
             'CXXFLAGS=' + options, 'LDFLAGS=' + options, 'CXXFLAGS_FOR_BUILD=' + FLAGS,
             'LDFLAGS_FOR_BUILD=-Os', 'CPPFLAGS_FOR_BUILD='], cwd=tree,
                log=out / (name + '-configure.log'), timeout=120)
        run(['make', '-j' + str(args.jobs)], cwd=tree,
            log=out / (name + ('-finish-build.log' if args.finish_tools else '-build.log')), timeout=600)
    for name in BINARIES:
        binary = out / 'riscv64/src' / name
        run(['riscv64-linux-gnu-strip', '--strip-unneeded', binary])
        header = binary.read_bytes()[:64]
        if (header[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', header, 18)[0] != 243
                or struct.unpack_from('<I', header, 48)[0] & 6 != 4):
            raise RuntimeError('Dinit executable is not RV64 LP64D: ' + name)
    version = subprocess.check_output([out / 'native/src/dinit', '--version'], text=True).strip()
    record = dict(stage='tools_ready', source=lock, version=version,
        build_flags=flags, cgroups_required=False, board_verified=False,
        source_lock_sha256=sha(ASSETS / 'lock.json'),
        binaries={name: sha(out / 'riscv64/src' / name) for name in BINARIES},
        native_check_scope='service parser/supervision only; not Valence CPU execution')
    (out / 'tools-build.json').write_text(json.dumps(record, indent=2) + '\n')
    print('DINIT_RV64GC_TOOLS_READY_NOT_BOARD_VERIFIED ' + str(out), flush=True)


def rootfs(args):
    if os.geteuid() != 0:
        raise RuntimeError('Use WSL root for restoring device nodes into the private rootfs')
    out, seed = validate_output(args.out), validate_output(args.seed)
    if Path(args.seed_record).name != args.seed_record:
        raise RuntimeError('Seed record must be a basename')
    marker = seed / args.seed_record
    seed_record = json.loads(marker.read_text())
    if (seed_record.get('stage') != 'packed' or seed_record.get('architecture') != 'riscv64'
            or seed_record.get('suite') != 'trixie' or seed_record.get('init_system') == 'systemd'):
        raise RuntimeError('Use the verified small pre-systemd Debian 13 archive')
    archive = seed / seed_record['archive']['path']
    if archive.parent.resolve() != seed or sha(archive) != seed_record['archive']['sha256']:
        raise RuntimeError('Seed archive path or digest changed')
    names = archive_names(archive.read_bytes())
    if 'etc/os-release' not in names or 'init' not in names:
        raise RuntimeError('Seed is not a complete rootfs')
    kernel = validate_output(args.kernel_build)
    kr = json.loads((kernel / 'kernel-build.json').read_text())
    if (kr.get('stage') != 'kernel_and_modules_ready' or kr.get('init_system') != 'dinit'
            or kr.get('initramfs_compression') != 'lz4'):
        raise RuntimeError('Expected the matched Dinit/LZ4 kernel stage')
    tool_out = validate_output(args.tools_build)
    tr = json.loads((tool_out / 'tools-build.json').read_text())
    if tr.get('stage') != 'tools_ready' or tr.get('source_lock_sha256') != sha(ASSETS / 'lock.json'):
        raise RuntimeError('Pinned Dinit tools stage changed')
    out.mkdir(parents=True, exist_ok=False)
    root = out / 'rootfs'
    root.mkdir()
    record = dict(label=LABEL, stage='restoring', architecture='riscv64', suite='trixie',
        init_system='dinit', initramfs_compression='lz4', board_verified=False,
        seed_record_sha256=sha(marker), seed_archive_sha256=sha(archive),
        seed_signature_provenance={key: seed_record.get(key) for key in
            ('key_package_sha256', 'keyring_sha256', 'packages_sha256', 'source_bootstrap_record_sha256')},
        dinit=tr, kernel_build=str(kernel), host_qemu_used_only_for_static_userland_checks=True)
    (out / 'rootfs-build.json').write_text(json.dumps(record, indent=2) + '\n')
    with archive.open('rb') as stream, (out / 'restore.log').open('wb') as log:
        subprocess.run(['cpio', '--quiet', '-id', '--preserve-modification-time',
            '--no-absolute-filenames'], cwd=root, stdin=stream, stdout=log, stderr=log, check=True)
    # No package installation, host DNS substitution, systemd or automatic udev scan.
    status = Path('/proc/sys/fs/binfmt_misc/qemu-riscv64').read_text()
    if 'enabled' not in status or 'F' not in status.split('flags:', 1)[1]:
        raise RuntimeError('Fixed-interpreter riscv64 static tool checks require binfmt')
    package_list = subprocess.check_output(['chroot', str(root), 'dpkg-query', '-W',
        '-f=${binary:Package}\t${Version}\t${Architecture}\n'], text=True)
    if any(line.split('\t')[0].split(':')[0] in
           ('systemd', 'systemd-sysv', 'libpam-systemd', 'udev', 'dbus') for line in package_list.splitlines()):
        raise RuntimeError('Seed contains the unwanted systemd service stack')
    (out / 'packages.tsv').write_text(package_list)
    for name in BINARIES:
        source = tool_out / 'riscv64/src' / name
        if sha(source) != tr['binaries'][name]:
            raise RuntimeError('Dinit binary drift: ' + name)
        copy(source, root / 'usr/sbin' / name, 0o755)
    for name, target in (('init', 'dinit'), ('dinit-reboot', 'dinit-shutdown'),
                         ('dinit-halt', 'dinit-shutdown'), ('dinit-poweroff', 'dinit-shutdown')):
        link = root / 'usr/sbin' / name
        if link.exists() or link.is_symlink():
            raise RuntimeError('Refusing to overwrite init/shutdown aliases')
        link.symlink_to(target)
    for name, target in (('init', 'init'), ('platform-init', 'usr/local/libexec/valence-platform-init'),
                        ('network-control', 'usr/local/libexec/valence-network-control'),
                        ('ready', 'usr/local/libexec/valence-dinit-ready'),
                        ('boot-diagnose', 'usr/local/sbin/boot-diagnose')):
        copy(ASSETS / name, root / target, 0o755)
        run(['/bin/sh', '-n', ASSETS / name], log=out / (name + '-syntax.log'))
    copy(ASSETS / 'environment', root / 'etc/dinit/environment', 0o644)
    for name in SERVICES:
        copy(ASSETS / 'services' / name, root / 'etc/dinit.d' / name, 0o644)
    copy(HERE / 'interfaces', root / 'etc/network/interfaces', 0o644)
    copy(HERE / 'valence-driver-order.conf', root / 'etc/modprobe.d/valence-order.conf', 0o644)
    copy(tool_out / 'riscv64/LICENSE', root / 'usr/share/doc/valence/dinit/LICENSE', 0o644)
    version = kr['linux_version']
    if not version or '/' in version or '..' in version:
        raise RuntimeError('Invalid kernel release')
    module_dir = root / 'usr/lib/modules' / version
    for name, digest in kr['modules'].items():
        source = kernel / 'module' / name
        if sha(source) != digest:
            raise RuntimeError('Matched module changed: ' + name)
        copy(source, module_dir / 'extra' / name, 0o644)
    for name in ('modules.builtin', 'modules.builtin.modinfo'):
        copy(kernel / 'linux' / name, module_dir / name, 0o644)
    (module_dir / 'modules.order').write_text(''.join('extra/' + name + '\n' for name in kr['modules']))
    run(['depmod', '-b', root, '-F', kernel / 'linux/System.map', version], log=out / 'depmod.log')
    if 'WARNING' in (out / 'depmod.log').read_text():
        raise RuntimeError('Module dependency warnings')
    run(['riscv64-linux-gnu-gcc', '-O2', '-march=rv64gc_zicsr_zifencei', '-mabi=lp64d',
        '-mstrict-align', '-Wall', '-Wextra', '-Werror', HERE / 'mem-bench.c',
        '-o', root / 'usr/local/bin/mem-bench'], log=out / 'mem-bench-build.log')
    (root / 'etc/valence/build-time').write_text(datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S') + '\n')
    run(['chroot', root, '/usr/sbin/dinit', '--version'], log=out / 'target-version.log')
    run(['chroot', root, '/usr/sbin/dinitcheck', '--services-dir', '/etc/dinit.d', 'boot'],
        log=out / 'target-services-check.log')
    audit = subprocess.check_output(['chroot', str(root), 'dpkg', '--audit'], text=True)
    (out / 'dpkg-audit.log').write_text(audit)
    if audit.strip():
        raise RuntimeError('Debian package audit failed')
    for name in kr['modules']:
        run(['chroot', root, '/sbin/modprobe', '--set-version', version, '--show-depends',
             name.removesuffix('.ko')], log=out / (name + '-dry-run.log'))
    console = (root / 'dev/console').lstat()
    if not stat.S_ISCHR(console.st_mode) or console.st_rdev != os.makedev(5, 1):
        raise RuntimeError('Missing pre-init character console device')
    excluded = ('debootstrap', 'var/cache/apt/archives', 'var/lib/apt/lists', 'etc/inittab')
    paths = ['.']
    for path in root.rglob('*'):
        relative = path.relative_to(root).as_posix()
        if not any(relative == p or relative.startswith(p + '/') for p in excluded):
            paths.append('./' + relative)
    paths.sort()
    payload_bytes = sum((root / p).stat().st_size for p in paths
        if not (root / p).is_symlink() and (root / p).is_file())
    if payload_bytes > 240 * 1024 * 1024:
        raise RuntimeError('Dinit rootfs exceeds the pre-systemd memory budget')
    result = out / 'debian13-riscv64-dinit-vl100.cpio'
    with result.open('wb') as stream:
        subprocess.run(['cpio', '--null', '-o', '-H', 'newc', '--reproducible'], cwd=root,
            input=b'\0'.join(p.encode() for p in paths) + b'\0', stdout=stream, check=True)
    compressed = result.with_suffix('.cpio.lz4')
    with compressed.open('wb') as stream:
        subprocess.run(['lz4', '-l', '-9', '-c', result], stdout=stream, check=True)
    decoded = subprocess.check_output(['lz4', '-d', '-c', compressed])
    if decoded != result.read_bytes():
        raise RuntimeError('LZ4 round-trip mismatch')
    record.update(stage='packed', archive=dict(path=result.name, bytes=result.stat().st_size, sha256=sha(result)),
        compressed=dict(path=compressed.name, bytes=compressed.stat().st_size, sha256=sha(compressed)),
        rootfs_file_bytes=payload_bytes, packages_sha256=sha(out / 'packages.tsv'),
        memory_bytes=kr['memory_bytes'], cpu_hz=kr['cpu_hz'], uart_baud=kr['uart_baud'], modules=kr['modules'],
        service_descriptors=list(SERVICES), persistent_daemons=['dinit', 'agetty/login/bash'],
        no_systemd_services=True, no_udev_or_dbus_daemons=True, network_auto_enable=True,
        driver_failure_keeps_serial=True, network_failure_keeps_serial=True,
        persistent_storage=False, require_repaired_bit=True, vendor='OpenIon', soc='VL100', cpu='Orbital-A1',
        sources={str(p.relative_to(HERE)): sha(p) for p in
            [Path(__file__), HERE / 'mem-bench.c', *sorted(p for p in ASSETS.rglob('*') if p.is_file())]},
        checks='target dinitcheck/module dry-run/package audit/LZ4 round-trip; not board execution')
    (out / 'rootfs-build.json').write_text(json.dumps(record, indent=2) + '\n')
    print('DINIT_LZ4_ROOTFS_PACKED_NOT_BOARD_VERIFIED ' + str(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('tools', 'rootfs'), required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--seed', type=Path)
    parser.add_argument('--seed-record', default='rootfs-build-netboot-drain-r1.json')
    parser.add_argument('--tools-build', type=Path)
    parser.add_argument('--kernel-build', type=Path)
    parser.add_argument('--jobs', type=int, default=8)
    parser.add_argument('--finish-tools', action='store_true', help='finish an incomplete tools output after checking all copied upstream files')
    args = parser.parse_args()
    if args.jobs < 1 or args.stage == 'tools' and args.source is None or args.stage == 'rootfs' and any(
            v is None for v in (args.seed, args.tools_build, args.kernel_build)):
        parser.error('tools requires --source; rootfs requires --seed, --tools-build and --kernel-build')
    (tools if args.stage == 'tools' else rootfs)(args)
