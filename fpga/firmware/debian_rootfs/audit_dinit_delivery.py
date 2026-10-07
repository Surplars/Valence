#!/usr/bin/env python3
"""Independent packed-content checks; no board access or hardware simulation."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
import netboot_host


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise RuntimeError(message)


def decode_newc(blob):
    entries, linked = {}, {}
    offset = 0
    while offset + 110 <= len(blob):
        require(blob[offset:offset + 6] == b'070701', 'newc header')
        f = [int(blob[offset + 6 + i * 8:offset + 14 + i * 8], 16) for i in range(13)]
        start, size, namesize = offset + 110, f[6], f[11]
        require(namesize > 0 and start + namesize <= len(blob), 'newc name bounds')
        raw = blob[start:start + namesize]
        require(raw[-1:] == b'\0' and b'\0' not in raw[:-1], 'newc name termination')
        name = raw[:-1].decode()
        body = (start + namesize + 3) & ~3
        require(body + size <= len(blob), 'newc data bounds')
        if name == 'TRAILER!!!':
            return entries, linked
        require(not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts, 'newc path')
        name = name.removeprefix('./')
        require(name not in entries, 'duplicate archive path')
        data = blob[body:body + size]
        entries[name] = f, data
        if stat.S_ISREG(f[1]) and f[4] > 1 and size:
            linked[(f[7], f[8], f[0])] = data
        offset = (body + size + 3) & ~3
    raise RuntimeError('missing newc trailer')


def main(args):
    delivery, rootfs_out = args.delivery.resolve(), args.rootfs_out.resolve()
    allowed = (ROOT / 'build/fpga').resolve()
    require(allowed in delivery.parents and allowed in rootfs_out.parents, 'isolated build output required')
    receipt = delivery / 'dinit-content-audit.json'
    require(not receipt.exists(), 'completed receipt is immutable')
    manifest = json.loads((delivery / 'manifest.json').read_text())
    require(manifest['init_system'] == 'dinit' and manifest['initramfs_compression'] == 'lz4'
        and manifest['dinit'] and not manifest['systemd'] and not manifest['board_verified']
        and manifest['cpu_hz'] == 100000000 and manifest['memory_bytes'] == 0x80000000
        and manifest['uart_baud'] == 460800, 'wrong firmware identity')
    for name, row in manifest['files'].items():
        require(Path(name).name == name, 'artifact basename')
        blob = (delivery / name).read_bytes()
        require(len(blob) == row['bytes'] and digest(blob) == row['sha256'], 'artifact drift: ' + name)
    rr = manifest['rootfs']
    archive = rootfs_out / rr['archive']['path']
    blob = archive.read_bytes()
    require(digest(blob) == rr['archive']['sha256'], 'archive hash')
    entries, linked = decode_newc(blob)

    def content(name):
        f, data = entries[name]
        return data or linked.get((f[7], f[8], f[0]), b'')

    init = content('init').decode()
    require('exec /usr/sbin/dinit ' in init and 'setsid ' not in init, 'PID 1/getty contract')
    require('systemd' not in init and 'bb init' not in init, 'legacy init execution')
    names = sorted(name.split('/')[-1] for name in entries if name.startswith('etc/dinit.d/'))
    require(names == sorted(rr['service_descriptors']), 'unexpected Dinit service')
    require('etc/inittab' not in entries, 'legacy respawn configuration shipped')
    # Debian packages may contain vendor unit metadata; Dinit never loads it.
    # Check the actual init executable, not harmless package-owned unit files.
    require('usr/lib/systemd/systemd' not in entries, 'systemd PID 1 executable shipped')
    platform = content('usr/local/libexec/valence-platform-init').decode()
    offsets = [platform.index('modprobe ' + name) for name in
        ('valence_soc', 'valence_aia', 'valence_cmu', 'valence_dma', 'valence_gmac')]
    require(offsets == sorted(offsets) and platform.index('if [ "$ready" != 1 ]') < offsets[2], 'unsafe driver order')
    require('waits-for: platform' in content('etc/dinit.d/ready').decode(), 'serial recovery not soft-dependent')
    require('depends-on: platform' in content('etc/dinit.d/network').decode(), 'network bypasses platform safety')
    for module, expected in manifest['modules'].items():
        require(digest(content('usr/lib/modules/' + manifest['linux_version'] + '/extra/' + module)) == expected,
            'packed module drift: ' + module)
    for name, expected in rr['dinit']['binaries'].items():
        binary = content('usr/sbin/' + name)
        require(digest(binary) == expected and binary[:6] == b'\x7fELF\x02\x01'
            and struct.unpack_from('<H', binary, 18)[0] == 243
            and struct.unpack_from('<I', binary, 48)[0] & 6 == 4, 'Dinit RV64 LP64D binary: ' + name)
    require(entries['dev/console'][0][1] & 0o170000 == 0o020000
        and entries['dev/console'][0][9:11] == [5, 1], 'console device node')
    for path in ('usr/bin/bash', 'usr/lib/riscv64-linux-gnu/libc.so.6', 'usr/local/bin/mem-bench',
                 'usr/local/bin/coremark', 'usr/local/bin/fpu-test', 'usr/local/bin/fastfetch',
                 'usr/bin/iperf3', 'usr/local/sbin/dma-bench'):
        require(path in entries and len(content(path)) > 0, 'missing Debian/tool functionality: ' + path)
    require('VALENCE_RAM_BYTES=2147483648' in content('etc/valence-release').decode(), 'RAM identity')
    compressed = (rootfs_out / rr['compressed']['path']).read_bytes()
    require(digest(compressed) == rr['compressed']['sha256'] and compressed[:4] == b'\x02\x21\x4c\x18', 'legacy LZ4 stream')
    require(subprocess.check_output(['lz4', '-d', '-c'], input=compressed) == blob, 'LZ4 content mismatch')
    config = (delivery / 'linux.config').read_text().splitlines()
    require('CONFIG_RD_LZ4=y' in config and 'CONFIG_INITRAMFS_COMPRESSION_LZ4=y' in config
        and 'CONFIG_INITRAMFS_COMPRESSION_GZIP=y' not in config, 'wrong kernel compressor')
    require(netboot_host.validate(delivery / 'valence.vld', netboot_host.LIMITS['ddr2g']) ==
        manifest['files']['opensbi_debian13_riscv64_vl100_cpu100_u460800_dinit_lz4.bin']['bytes'], 'netboot size/header/CRC')
    for name, expected in rr['sources'].items():
        require(digest((HERE / name).read_bytes()) == expected, 'rootfs source drift: ' + name)
    tests = {}
    for name in ('test_dinit_rootfs.py', 'test_systemd_rootfs.py'):
        result = subprocess.run([sys.executable, HERE / name], stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=30)
        (delivery / (name + '.log')).write_bytes(result.stdout)
        require(result.returncode == 0, 'short test failure: ' + name)
        tests[name] = dict(source_sha256=digest((HERE / name).read_bytes()),
                          log_sha256=digest(result.stdout), status='passed')
    result = dict(status='software_content_and_short_tests_passed_not_board_verified',
        manifest_sha256=digest((delivery / 'manifest.json').read_bytes()), archive_entries=len(entries),
        archive_sha256=digest(blob), compressed_sha256=digest(compressed),
        dinit_source_revision=rr['dinit']['source']['revision'], service_descriptors=rr['service_descriptors'],
        short_tests=tests, serial_recovery_native_test=True, target_dinitcheck=True,
        exact_embedded_rootfs_verified_by_image_builder=True, rtl_changed=False,
        vivado_or_gsim_run=False, board_verified=False, shutdown_on_board_verified=False,
        audit_source_sha256=digest(Path(__file__).read_bytes()))
    receipt.write_text(json.dumps(result, indent=2) + '\n')
    print('DINIT_CONTENT_AUDIT_PASS_NOT_BOARD_VERIFIED ' + str(receipt))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delivery', type=Path, required=True)
    parser.add_argument('--rootfs-out', type=Path, required=True)
    main(parser.parse_args())
