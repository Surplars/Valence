#!/usr/bin/env python3
"""Offline, rootless common I1/A1 BusyBox initramfs; no board or host installs."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ARCHIVES = {
    'musl-1.2.5.tar.gz': 'a9a118bbe84d8764da0ea0d28b3ab3fae8477fc7e4085d90102b8596fc7c75e4',
    'busybox-1.37.0.tar.bz2': '3311dff32e746499f4df0d5df04d7eb396382d7e108bb9250e7b519b837043a4',
}
REQUIRED_APPLETS = {'sh', 'mount', 'mkdir', 'hostname', 'grep', 'cat', 'dmesg', 'ip',
                    'ifconfig', 'ping', 'udhcpc', 'setsid', 'cttyhack', 'sha256sum',
                    'uname', 'insmod', 'modprobe', 'lsmod', 'ls', 'awk', 'sleep', 'tr', 'find'}
# A hardware dependency policy, not the module inventory. The latter comes ONLY
# from the matched kernel record and ELF .modinfo of each actual .ko.
PRIORITY = ('valence_soc', 'valence_aia', 'valence_clockmon', 'valence_cmu',
            'valence_dma', 'valence_gmac')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def run(argv, *, cwd=None, log=None, timeout=900):
    env = os.environ.copy()
    for name in ('CPATH', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'LIBRARY_PATH'):
        env.pop(name, None)  # Do not inject the host tool-cache headers into target links.
    argv = [str(a) for a in argv]
    if log:
        with Path(log).open('wb') as output:
            subprocess.run(argv, cwd=cwd, env=env, stdout=output,
                           stderr=subprocess.STDOUT, timeout=timeout, check=True)
    else:
        subprocess.run(argv, cwd=cwd, env=env, timeout=timeout, check=True)


def checked_file(base, relative):
    p = PurePosixPath(relative)
    if not relative or p.is_absolute() or '..' in p.parts or '\\' in relative or ':' in relative:
        raise RuntimeError('Unsafe relative input: ' + relative)
    path = Path(base) / relative
    if not path.is_file() or not path.resolve().is_relative_to(Path(base).resolve()):
        raise RuntimeError('Input absent or escapes source: ' + str(path))
    return path


def verify_busybox(binary, readelf):
    data = binary.read_bytes()
    if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01':
        raise RuntimeError('BusyBox is not ELF64 little-endian')
    if struct.unpack_from('<H', data, 18)[0] != 243 or struct.unpack_from('<I', data, 48)[0] & 6:
        raise RuntimeError('BusyBox must be RISC-V soft-float LP64')
    phoff = struct.unpack_from('<Q', data, 32)[0]
    entsize, count = struct.unpack_from('<HH', data, 54)
    if entsize < 56 or phoff + entsize * count > len(data):
        raise RuntimeError('Malformed BusyBox ELF program headers')
    if any(struct.unpack_from('<I', data, phoff + i * entsize)[0] == 3 for i in range(count)):
        raise RuntimeError('BusyBox has a dynamic interpreter')
    attrs = subprocess.check_output([readelf, '-A', str(binary)], text=True)
    match = re.search(r'Tag_RISCV_arch: "([^"]+)"', attrs)
    if not match or not match[1].startswith('rv64i') or re.search(r'_(?:f|d|v)[0-9]', match[1]):
        raise RuntimeError('BusyBox requires unapproved floating/vector ISA')
    return match[1]


def build_userland(args):
    source = args.sources.resolve()
    for name, digest in ARCHIVES.items():
        archive = checked_file(source / 'downloads', name)
        if sha(archive) != digest:
            raise RuntimeError('Pinned archive mismatch: ' + name)
    musl, busy = source / 'musl-1.2.5', source / 'busybox-1.37.0'
    if not (musl / 'configure').is_file() or not (busy / 'Makefile').is_file():
        raise RuntimeError('Environment owner must prepare pinned extracted sources first')
    headers = args.uapi_headers.resolve()
    for name in ('linux', 'asm', 'asm-generic'):
        if not (headers / name).is_dir():
            raise RuntimeError('Explicit target UAPI headers missing: ' + str(headers / name))
    out = args.out.resolve()
    if (out / 'manifest.json').exists():
        raise RuntimeError('Refusing to overwrite a completed userland build')
    out.mkdir(parents=True, exist_ok=args.resume)
    sysroot, musl_out, busy_out = out / 'sysroot', out / 'musl', out / 'busybox-linux'
    musl_out.mkdir(exist_ok=args.resume); busy_out.mkdir(exist_ok=args.resume)
    prefix = args.cross_compile
    cc = prefix + 'gcc'
    run([musl / 'configure', '--target=riscv64-linux-musl', '--disable-shared',
         '--prefix=' + str(sysroot), '--syslibdir=' + str(sysroot / 'lib'),
         'CC=' + cc + ' -march=rv64imac -mabi=lp64', 'CFLAGS=-Os',
         'AR=' + prefix + 'ar', 'RANLIB=' + prefix + 'ranlib'],
        cwd=musl_out, log=out / 'musl-config.log')
    run(['make', '-j' + str(args.jobs)], cwd=musl_out, log=out / 'musl-build.log')
    run(['make', 'install'], cwd=musl_out, log=out / 'musl-install.log')
    specs = sysroot / 'lib/musl-gcc.specs'
    original = subprocess.check_output(['sh', str(musl / 'tools/musl-gcc.specs.sh'),
        str(sysroot / 'include'), str(sysroot / 'lib'), str(sysroot / 'lib/ld-musl-riscv64.so.1')], text=True)
    specs.write_text(original.split('*esp_link:', 1)[0].rstrip().replace('Scrt1.o', 'crt1.o')
                     .replace('crtbeginS.o', 'crtbegin.o').replace('crtendS.o', 'crtend.o')
                     + '\n\n*lib:\n-lc\n\n')
    header_inputs = {}
    for name in ('linux', 'asm', 'asm-generic', 'mtd', 'scsi', 'sound', 'video', 'drm'):
        if (headers / name).is_dir():
            for path in sorted((headers / name).rglob('*')):
                if path.is_file():
                    relative = path.relative_to(headers)
                    target = sysroot / 'include' / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # Keep musl's public libc headers, add only missing UAPI headers.
                    if not target.exists():
                        shutil.copyfile(path, target)
                    header_inputs[str(relative)] = sha(path)
    wrapper = out / 'riscv64-valence-musl-gcc'
    wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(cc)
        + ' -march=rv64imac -mabi=lp64 -D__linux__=1 -D__unix__=1 -specs='
        + shlex.quote(str(specs)) + ' "$@"\n')
    wrapper.chmod(0o755)
    make = ['make', 'O=' + str(busy_out), 'ARCH=riscv',
            'CROSS_COMPILE=' + prefix, 'CC=' + str(wrapper)]
    run([*make, 'defconfig'], cwd=busy, log=out / 'busybox-config.log')
    config = busy_out / '.config'
    edits = {'STATIC': 'y', 'PIE': 'n', 'TC': 'n', 'SHA1_HWACCEL': 'n',
             'SHA256_HWACCEL': 'n', 'MODPROBE_SMALL': 'n', 'MODPROBE': 'y',
             'INSMOD': 'y', 'LSMOD': 'y', 'DEPMOD': 'y', 'EXTRA_CFLAGS': '"-Os"',
             'EXTRA_LDFLAGS': '"-static"'}
    text = config.read_text()
    for key, value in edits.items():
        text = re.sub(r'(?m)^(?:# )?CONFIG_' + key + r'(?:=.*| is not set)\n', '', text)
        text += ('# CONFIG_' + key + ' is not set\n' if value == 'n' else 'CONFIG_' + key + '=' + value + '\n')
    config.write_text(text)
    run([*make, 'oldconfig'], cwd=busy, log=out / 'busybox-oldconfig.log')
    run([*make, '-j' + str(args.jobs)], cwd=busy, log=out / 'busybox-build.log')
    run([*make, 'busybox.links'], cwd=busy, log=out / 'busybox-links.log')
    binary = busy_out / 'busybox'
    run([prefix + 'strip', '--strip-unneeded', binary])
    isa = verify_busybox(binary, prefix + 'readelf')
    links = read_links(busy_out / 'busybox.links')
    missing = REQUIRED_APPLETS - {PurePosixPath(p).name for p in links}
    if missing:
        raise RuntimeError('BusyBox applets missing: ' + ','.join(sorted(missing)))
    record = dict(stage='userland_ready', isa=isa, abi='lp64', link='static musl 1.2.5',
                  busybox_version='1.37.0', archives=ARCHIVES,
                  binaries={'busybox': dict(bytes=binary.stat().st_size, sha256=sha(binary))},
                  links_sha256=sha(busy_out / 'busybox.links'), config_sha256=sha(config),
                  uapi_headers=str(headers), uapi_header_inputs=header_inputs,
                  compiler=subprocess.check_output([cc, '--version'], text=True).splitlines()[0],
                  target_executed=False, board_verified=False,
                  upstream_build_warning_count=sum((out / n).read_text().count('warning:')
                      for n in ('musl-build.log', 'busybox-build.log')),
                  build_logs={n: sha(out / n) for n in ('musl-build.log', 'busybox-build.log')})
    write_json(out / 'manifest.json', record)
    print('COMMON_BUSYBOX_STATIC_USERLAND_READY ' + str(out))


def read_links(path):
    result = set()
    for item in path.read_text().splitlines():
        if item == '/linuxrc':
            result.add('linuxrc')
            continue
        p = PurePosixPath(item)
        if not p.is_absolute() or '..' in p.parts or '\\' in item or len(p.parts) < 3:
            raise RuntimeError('Unsafe BusyBox applet path: ' + item)
        if str(p.parent) not in ('/bin', '/sbin', '/usr/bin', '/usr/sbin') or p.name == 'busybox':
            raise RuntimeError('Unexpected BusyBox applet path: ' + item)
        result.add(item.lstrip('/'))
    return sorted(result)


def module_metadata(path):
    """Read real ELF .modinfo; no executing module code or host modprobe needed."""
    data = path.read_bytes()
    if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<HH', data, 16) != (1, 243):
        raise RuntimeError('Module must be RISC-V ELF64 relocatable: ' + str(path))
    offset = struct.unpack_from('<Q', data, 40)[0]
    size, count, names_index = struct.unpack_from('<HHH', data, 58)
    if size < 64 or not count or names_index >= count or offset + size * count > len(data):
        raise RuntimeError('Malformed module sections')
    def section(i):
        fields = struct.unpack_from('<IIQQQQIIQQ', data, offset + size * i)
        start, length = fields[4:6]
        if fields[1] == 8:  # SHT_NOBITS has no file payload.
            return fields[0], b''
        if start + length > len(data):
            raise RuntimeError('Truncated module section')
        return fields[0], data[start:start + length]
    _, names = section(names_index)
    result = {}
    for i in range(count):
        name_offset, body = section(i)
        if name_offset >= len(names):
            raise RuntimeError('Invalid module section name')
        if names[name_offset:].split(b'\0', 1)[0] == b'.modinfo':
            for entry in body.split(b'\0'):
                if b'=' in entry:
                    key, value = entry.decode('utf-8').split('=', 1)
                    result.setdefault(key, []).append(value)
    for key in ('name', 'vermagic', 'depends'):
        if len(result.get(key, [])) != 1:
            raise RuntimeError('Missing/duplicate module metadata: ' + key)
    return {key: result[key][0].strip() for key in ('name', 'vermagic', 'depends')}


def validate_kernel(kernel):
    record = json.loads((kernel / 'kernel-build.json').read_text())
    platform = record.get('common_platform', {})
    if (record.get('stage') != 'kernel_and_modules_ready' or record.get('init_system') != 'busybox'
            or record.get('console_profile') != 'sbi' or platform.get('cpu_profiles') != ['i1', 'a1']
            or platform.get('cpu_hz') != 50000000 or platform.get('fabric_hz') != 50000000
            or platform.get('timebase_hz') != 250000000):
        raise RuntimeError('Expected matched common I1/A1 boot50 SBI BusyBox kernel')
    version = record['linux_version']
    if not re.fullmatch(r'[A-Za-z0-9_.+-]+', version) or version in ('.', '..'):
        raise RuntimeError('Invalid kernel release')
    modules = {}
    if not isinstance(record.get('modules'), dict) or not record['modules']:
        raise RuntimeError('Empty module inventory')
    for filename, digest in record['modules'].items():
        if not re.fullmatch(r'[A-Za-z0-9_]+\.ko', filename):
            raise RuntimeError('Invalid module filename')
        path = checked_file(kernel / 'module', filename)
        if sha(path) != digest:
            raise RuntimeError('Module hash mismatch: ' + filename)
        meta = module_metadata(path)
        if meta['name'] != filename[:-3] or meta['vermagic'].split()[0] != version:
            raise RuntimeError('Module name/vermagic mismatch: ' + filename)
        for field, key in (('module_vermagic', 'vermagic'), ('module_dependencies', 'depends')):
            expected_meta = (list(filter(None, meta[key].split(',')))
                             if key == 'depends' else meta[key])
            if field in record and record[field].get(filename) != expected_meta:
                raise RuntimeError('Module metadata record drift: ' + filename)
        modules[meta['name']] = dict(meta, filename=filename, sha256=digest,
                                     bytes=path.stat().st_size)
    # The common kernel owner promises every in-tree feature is built in.
    config = checked_file(kernel / 'linux', '.config')
    if sha(config) != record['config_sha256']:
        raise RuntimeError('Kernel config drift')
    modular = set(re.findall(r'(?m)^CONFIG_(\w+)=m$', config.read_text()))
    if modular - {'VALENCE_SOC'}:
        raise RuntimeError('Uninventoried in-tree module configuration: ' + ','.join(sorted(modular)))
    expected = set(PRIORITY)
    if set(modules) != expected:
        raise RuntimeError('Review platform load/probe policy for changed module inventory: '
                           + ','.join(sorted(modules)))
    ordered = []
    pending = set(modules)
    while pending:
        choices = [name for name in PRIORITY if name in pending
                   and not (set(filter(None, modules[name]['depends'].split(','))) - set(ordered))]
        if not choices:
            raise RuntimeError('Unresolved or cyclic module dependencies')
        name = choices[0]; ordered.append(name); pending.remove(name)
    # Hardware policy takes precedence even if ELF dependencies do not express it.
    if ordered.index('valence_aia') > min(ordered.index('valence_dma'), ordered.index('valence_gmac')):
        raise RuntimeError('IRQ dependency ordering violation')
    return record, modules, ordered


def newc_entry(name, payload, mode, inode, major=0, minor=0):
    encoded = name.encode() + b'\0'
    fields = [inode, mode, 0, 0, 2 if stat.S_ISDIR(mode) else 1, 0, len(payload),
              0, 0, major, minor, len(encoded), 0]
    header = b'070701' + ''.join(f'{n:08x}' for n in fields).encode()
    return header + encoded + b'\0' * ((-len(header) - len(encoded)) % 4) + payload + b'\0' * (-len(payload) % 4)


def pack_newc(root):
    result = bytearray()
    inventory = {}
    for inode, path in enumerate(sorted(root.rglob('*')), 1):
        name = path.relative_to(root).as_posix()
        s = path.lstat()
        if path.is_symlink():
            payload = os.readlink(path).encode()
        elif path.is_file():
            payload = path.read_bytes()
        elif path.is_dir():
            payload = b''
        else:
            raise RuntimeError('Unexpected staged file type: ' + name)
        result += newc_entry(name, payload, s.st_mode, inode)
        inventory[name] = dict(mode=oct(s.st_mode), bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    inode = len(inventory) + 1
    for name, major, minor in [('dev/console', 5, 1), ('dev/null', 1, 3), ('dev/tty', 5, 0)]:
        if name in inventory:
            raise RuntimeError('Device path collision')
        result += newc_entry(name, b'', stat.S_IFCHR | 0o600, inode, major, minor); inode += 1
        inventory[name] = dict(mode=oct(stat.S_IFCHR | 0o600), major=major, minor=minor, bytes=0)
    result += newc_entry('TRAILER!!!', b'', 0, inode)
    result += b'\0' * (-len(result) % 512)
    return bytes(result), inventory


def pack(args):
    kernel, userland, out = args.kernel_build.resolve(), args.userland.resolve(), args.out.resolve()
    kr, modules, order = validate_kernel(kernel)
    ur = json.loads((userland / 'manifest.json').read_text())
    binary = checked_file(userland, 'busybox-linux/busybox')
    links_file = checked_file(userland, 'busybox-linux/busybox.links')
    if (ur.get('stage') != 'userland_ready' or ur.get('archives') != ARCHIVES
            or sha(binary) != ur['binaries']['busybox']['sha256']
            or binary.stat().st_size != ur['binaries']['busybox']['bytes']
            or sha(links_file) != ur['links_sha256']):
        raise RuntimeError('Userland provenance mismatch')
    isa = verify_busybox(binary, args.cross_compile + 'readelf')
    links = read_links(links_file)
    if REQUIRED_APPLETS - {PurePosixPath(p).name for p in links}:
        raise RuntimeError('Required BusyBox applets missing')
    out.mkdir(parents=True, exist_ok=False)
    root = out / 'rootfs'; root.mkdir()
    for directory in ('bin', 'sbin', 'usr/bin', 'usr/sbin', 'usr/share/licenses',
                      'proc', 'sys', 'dev/pts', 'tmp', 'run', 'var/log', 'etc/valence', 'root'):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / 'tmp').chmod(0o1777)
    def copy(source, dest, mode=0o644):
        target = root / dest; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target); target.chmod(mode)
    copy(binary, 'bin/busybox', 0o755)
    for link in links:
        (root / link).symlink_to('/bin/busybox')
    for name, dest in [('init', 'init'), ('diagnose', 'usr/sbin/valence-diagnose'),
                       ('net', 'usr/sbin/valence-net'), ('udhcpc', 'usr/sbin/valence-udhcpc')]:
        copy(HERE / name, dest, 0o755)
        subprocess.run(['/bin/sh', '-n', HERE / name], check=True)
    for name in ('profile', 'passwd', 'group', 'os-release'):
        copy(HERE / name, 'etc/' + name)
    (root / 'var/run').symlink_to('/run')
    release = kr['linux_version']
    module_dir = root / 'lib/modules' / release
    (module_dir / 'extra').mkdir(parents=True)
    for name in order:
        copy(kernel / 'module' / modules[name]['filename'],
             'lib/modules/' + release + '/extra/' + modules[name]['filename'])
    (module_dir / 'modules.dep').write_text(''.join('extra/' + modules[n]['filename'] + ':'
        + ''.join(' extra/' + modules[d]['filename'] for d in filter(None, modules[n]['depends'].split(',')))
        + '\n' for n in order))
    (module_dir / 'modules.order').write_text(''.join('extra/' + modules[n]['filename'] + '\n' for n in order))
    # Explicit ordered loading, never broad mdev/modalias probing of nonexistent hardware.
    (root / 'etc/valence/modules.load').write_text(''.join(n + '\n' for n in order))
    (root / 'etc/valence/modules.sha256').write_text(''.join(modules[n]['sha256'] + '  /lib/modules/'
        + release + '/extra/' + modules[n]['filename'] + '\n' for n in order))
    (root / 'etc/valence/kernel-release').write_text(release + '\n')
    (root / 'etc/valence/console-profile').write_text('sbi\n')
    (root / 'etc/valence/network-auto-enable').write_text('1\n' if args.network_auto_enable else '0\n')
    write_json(root / 'etc/valence/modules.json', modules)
    write_json(root / 'etc/valence/platform.json', kr['common_platform'])
    for name, filename in [('musl-1.2.5', 'COPYRIGHT'), ('busybox-1.37.0', 'LICENSE')]:
        copy(args.sources.resolve() / name / filename, 'usr/share/licenses/' + name)
    archive, entries = pack_newc(root)
    raw = out / 'common-i1-a1-busybox.cpio'; raw.write_bytes(archive)
    compressed = out / (raw.name + '.gz')
    compressed.write_bytes(gzip.compress(archive, compresslevel=9, mtime=0))
    if gzip.decompress(compressed.read_bytes()) != archive:
        raise RuntimeError('Compressed initramfs roundtrip failed')
    write_json(out / 'rootfs-contents.json', entries)
    record = dict(stage='packed', init_system='busybox', console_profile='sbi',
        kernel_build=str(kernel), kernel_build_sha256=sha(kernel / 'kernel-build.json'),
        userland_build=str(userland), userland_manifest_sha256=sha(userland / 'manifest.json'),
        architecture='riscv64', userland_isa=isa, userland_abi='lp64',
        common_platform=kr['common_platform'], linux_version=release,
        modules=modules, module_load_order=order, automatic_frequency_change=False,
        network_auto_enable=args.network_auto_enable, network_address_auto_configure=False,
        archive=dict(path=raw.name, bytes=len(archive), sha256=sha(raw)),
        compressed=dict(path=compressed.name, bytes=compressed.stat().st_size, sha256=sha(compressed)),
        rootfs_file_bytes=len(archive), contents_sha256=sha(out / 'rootfs-contents.json'),
        board_verified={'i1': False, 'a1': False}, kernel_boot_tested=False,
        runtime_qualification='PACKAGING_ONLY_NOT_KERNEL_OR_BOARD_EXECUTION',
        source_inputs={n: sha(HERE / n) for n in ('build_rootfs.py', 'init', 'diagnose', 'net', 'udhcpc',
                                                   'profile', 'passwd', 'group', 'os-release')})
    write_json(out / 'rootfs-build-common.json', record)
    print('COMMON_ROOTFS_PACKED_NOT_BOOT_VERIFIED ' + str(out))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('userland', 'pack'):
        p = commands.add_parser(name)
        p.add_argument('--out', type=Path, required=True)
        p.add_argument('--sources', type=Path, default=ROOT / 'simulator/build')
        p.add_argument('--cross-compile', default='riscv64-unknown-elf-')
        if name == 'userland':
            p.add_argument('--uapi-headers', type=Path, required=True)
            p.add_argument('--jobs', type=int, default=4)
            p.add_argument('--resume', action='store_true', help='Resume this private incomplete build, never a completed record')
        else:
            p.add_argument('--kernel-build', type=Path, required=True)
            p.add_argument('--userland', type=Path, required=True)
            p.add_argument('--network-auto-enable', action='store_true', help='Bring eth0 UP, never start DHCP')
    args = parser.parse_args()
    if args.command == 'userland' and args.jobs < 1:
        parser.error('--jobs must be positive')
    try:
        (build_userland if args.command == 'userland' else pack)(args)
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print('COMMON_ROOTFS_FAILED: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
