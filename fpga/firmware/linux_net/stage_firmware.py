#!/usr/bin/env python3
"""Check actual packaged CPIO, provenance and layout; stage a fresh delivery."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import build_image as b

CURRENT_ROOT = Path('/mnt/e/VM/Share/Valence-rtl/native-rv64gc-soc-return-control-20261006-r3')
CURRENT_BIT = CURRENT_ROOT / 'release-rv64gc100-u460800-r3/valence_native_rv64gc_2issue_cpu100_u460800_r3.bit'
BIT_SHA = '698780cad0042a8bfbe4b94ccb17857b2161698b78ec745f6ff58d3557f6fef7'
DELIVERY_NAME = 'firmware-net-rv64gc-r3'

def cpio_files(data):
    files, pos = {}, 0
    while pos < len(data):
        header = data[pos:pos + 110]
        if header[:6] != b'070701':
            raise RuntimeError('Invalid newc header')
        fields = [int(header[6 + 8*i:14 + 8*i], 16) for i in range(13)]
        size, name_size = fields[6], fields[11]
        name_start = pos + 110
        raw_name = data[name_start:name_start + name_size]
        if not raw_name.endswith(b'\0'):
            raise RuntimeError('Invalid newc filename')
        name = raw_name[:-1].decode().lstrip('/')
        body = (name_start + name_size + 3) & ~3
        if body + size > len(data):
            raise RuntimeError('Truncated CPIO')
        if name == 'TRAILER!!!':
            return files
        if name in files:
            raise RuntimeError('Duplicate initramfs path: ' + name)
        files[name] = data[body:body + size]
        pos = (body + size + 3) & ~3
    raise RuntimeError('No CPIO trailer')

def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()

def stage(output, destination):
    output = output.resolve()
    manifest = json.loads((output / 'manifest.json').read_text())
    if manifest['isa'] != 'rv64gc' or manifest['cpu_hz'] != 100000000 or manifest['uart_baud'] != 460800:
        raise RuntimeError('Wrong firmware profile')
    for name, expected in manifest['sources'].items():
        if b.sha(b.ROOT / name) != expected:
            raise RuntimeError('Source changed after build: ' + name)
    for name, expected in manifest['userland']['sources'].items():
        if b.sha(b.ROOT / name) != expected:
            raise RuntimeError('Userland source changed after build: ' + name)
    b.validate_config((output / 'linux.config').read_text())
    b.validate_dts((output / 'valence-gc-gmac.dts').read_text())
    b.validate_dtb(output / 'linux/scripts/dtc/dtc', output / 'valence-gc-gmac.dtb')
    b.validate_embedded_dtb((output / b.OUTPUT_NAME).read_bytes(),
                            (output / 'valence-gc-gmac.dtb').read_bytes())
    sources = {
        b.OUTPUT_NAME: output / b.OUTPUT_NAME,
        'valence-gc-gmac.dtb': output / 'valence-gc-gmac.dtb',
        'valence-gc-gmac.dts': output / 'valence-gc-gmac.dts',
        'linux.config': output / 'linux.config',
        'valence_gmac.ko': output / 'module/valence_gmac.ko',
        'valence_aia.ko': output / 'module/valence_aia.ko',
        'fpu-test': output / 'apps/fpu-test',
        'coremark': output / 'apps/coremark',
        'net-bench': output / 'apps/net-bench',
        'uart_load.py': output / 'uart_load.py',
    }
    for name, path in sources.items():
        if b.sha(path) != manifest['files'][name]['sha256']:
            raise RuntimeError('Built file identity mismatch: ' + name)
    image = output / 'linux/arch/riscv/boot/Image'
    b.image_header(image)
    b.validate_payload((output / b.OUTPUT_NAME).read_bytes(), image.read_bytes())
    compressed = (output / 'linux/usr/initramfs_inc_data').read_bytes()
    if compressed[:2] != b'\x1f\x8b' or image.read_bytes().find(compressed) < 0:
        raise RuntimeError('Exact compressed initramfs not embedded in final Image')
    packaged = cpio_files(gzip.decompress(compressed))
    expected_payloads = {
        'bin/busybox': output / 'userland/busybox/busybox',
        'bin/coremark': sources['coremark'], 'bin/fpu-test': sources['fpu-test'],
        'bin/net-bench': sources['net-bench'],
        'lib/modules/valence_gmac.ko': sources['valence_gmac.ko'],
        'lib/modules/valence_aia.ko': sources['valence_aia.ko'],
        'bin/net-status': b.HERE / 'net-status', 'bin/boot-time': b.HERE / 'boot-time',
        'etc/network/interfaces': b.HERE / 'interfaces', 'init': b.HERE / 'init',
        'bin/net-test': b.HERE / 'net-test',
        'usr/share/udhcpc/default.script': b.HERE / 'udhcpc.script',
    }
    for name, path in expected_payloads.items():
        if packaged.get(name) != path.read_bytes():
            raise RuntimeError('Actual initramfs payload mismatch: ' + name)
    for name in ('ip', 'ping', 'arping', 'ifup', 'ifdown', 'udhcpc', 'nc', 'wget', 'insmod'):
        # Linux gen_init_cpio includes the symlink target's terminating NUL.
        if not any(path.endswith('/' + name) and data in (b'/bin/busybox', b'/bin/busybox\0')
                   for path, data in packaged.items()):
            raise RuntimeError('BusyBox applet absent from actual initramfs: ' + name)
    tests = subprocess.run(['python3', '-m', 'unittest', 'discover', '-v', '-p', 'test_*.py'],
        cwd=b.HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
    (output / 'host-tests.log').write_text(tests.stdout)
    if tests.returncode:
        raise RuntimeError(tests.stdout)
    import re
    count = re.search(r'^Ran (\d+) tests? in ', tests.stdout, re.MULTILINE)
    if count is None:
        raise RuntimeError('Host test count missing')
    log = (output / 'gmac-build.log').read_text()
    if 'warning:' in log or 'error:' in log:
        raise RuntimeError('Driver W=1 build has warnings/errors')
    if b.sha(CURRENT_BIT) != BIT_SHA:
        raise RuntimeError('Target bit identity changed')
    allowed = CURRENT_ROOT / DELIVERY_NAME
    if destination.resolve() != allowed.resolve() or destination.is_symlink():
        raise RuntimeError('Unexpected publish destination')
    if destination.exists():
        raise RuntimeError('Never overwrite an existing delivery directory')
    destination.mkdir()
    delivery = {**sources, 'manifest.json': output / 'manifest.json',
        'net_bench_peer.py': b.HERE / 'net_bench_peer.py',
        'BOARD-TEST.txt': b.HERE / 'BOARD-TEST.txt', 'host-tests.log': output / 'host-tests.log',
        'fpu-instruction-check.json': output / 'fpu-instruction-check.json'}
    delivery.update({'net-status': b.HERE / 'net-status', 'boot-time': b.HERE / 'boot-time'})
    for name, source in delivery.items():
        target = destination / name
        shutil.copyfile(source, target)
        if b.sha(source) != b.sha(target):
            raise RuntimeError('Delivery copy mismatch: ' + name)
    receipt = {
        'status': 'PASS_GC_NETWORK_SOFTWARE_BUILD_AND_PACKAGE_BOARD_TEST_PENDING',
        'current_bit_sha256': BIT_SHA, 'current_bit_modified': False,
        'host_tests': int(count.group(1)), 'driver_W1_warnings': 0,
        'packaged_payloads_verified': len(expected_payloads),
        'exact_initramfs_embedded_in_Image_verified': True,
        'modern_F_D_isa_dtb_validated': True, 'kernel_isa_fallback_enabled': True,
        'exact_validated_dtb_embedded_in_OpenSBI_verified': True,
        'kernel_and_init_stage_timestamps_enabled': True,
        'kernel_tick_hz': 250, 'tickless_idle': True, 'data_plane_periodic_polling': False,
        'driver_mode': 'DMA IRQ + budgeted NAPI', 'dma_irq_source': 6,
        'internal_msi_selftest_required_at_boot': True, 'linux_irq_on_board_verified': False,
        'host_irq_race_model_is_not_module_or_hardware_execution': True,
        'hard_float_abi': 'lp64d', 'f_d_opcode_check': True,
        'linux_fpu_context_on_board_verified': False, 'gmac_on_board_verified': False,
        'physical_board_network_test_traffic_sent': False, 'host_loopback_tcp_tool_verified': True,
        'pc_network_settings_modified': False,
        'windows_delivery': 'E:/VM/Share/Valence-rtl/' + CURRENT_ROOT.name + '/' + destination.name,
        'wsl_build': str(output),
        'files': {name: {'bytes': source.stat().st_size, 'sha256': b.sha(source)} for name, source in delivery.items()}}
    encoded = json.dumps(receipt, indent=2) + '\n'
    (output / 'software-receipt.json').write_text(encoded)
    (destination / 'software-receipt.json').write_text(encoded)
    print(json.dumps({'status': receipt['status'], 'bytes': sources[b.OUTPUT_NAME].stat().st_size,
        'sha256': b.sha(sources[b.OUTPUT_NAME]), 'windows_delivery': receipt['windows_delivery']}), flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=b.ROOT / 'build/fpga/linux-net-rv64gc-20261006-r3')
    parser.add_argument('--publish-to', type=Path, default=CURRENT_ROOT / DELIVERY_NAME)
    args = parser.parse_args()
    stage(args.out, args.publish_to)
