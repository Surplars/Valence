#!/usr/bin/env python3
"""Matched VL100 UP kernel/modules and OpenSBI for a signed Debian rootfs.

Independent build output only. No RTL, Vivado, serial/network board writes.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NET = HERE.parent / 'linux_net'
sys.path[:0] = [str(NET), str(HERE.parent), str(ROOT / 'simulator/gsim')]
# Avoid importing this file as build_image when importing the existing helper.
import importlib.util
spec = importlib.util.spec_from_file_location('valence_network_image', NET / 'build_image.py')
net = importlib.util.module_from_spec(spec)
spec.loader.exec_module(net)
from build_linux import clean_revision, image_header, validate_payload, LOAD, KERNEL, DTB, MONITOR
from run import run, opensbi_setup, OPENSBI_LOCK
from memory_layout import MemoryLayout

MODULE_SOURCES = ('Makefile', 'valence_gmac.c', 'valence_aia.c', 'valence_soc.c', 'valence_cmu.c', 'valence_dma.c',
                  'valence_irq_policy.h', 'valence_driver_names.h')
MODULES = ('valence_aia.ko', 'valence_gmac.ko', 'valence_soc.ko', 'valence_cmu.ko', 'valence_dma.ko')
DEBIAN_CONFIG = ('SOC_BUS', 'SYSVIPC', 'SIGNALFD', 'TIMERFD', 'EVENTFD',
                 'INOTIFY_USER', 'AIO', 'FILE_LOCKING', 'ADVISE_SYSCALLS',
                 'KALLSYMS', 'UNIX_DIAG', 'INET_UDP_DIAG', 'INET_RAW_DIAG', 'SHMEM', 'TMPFS',
                 'COMMON_CLK', 'DMADEVICES', 'DMA_OF', 'DMA_ENGINE', 'DMA_VIRTUAL_CHANNELS', 'VALENCE_CMU', 'VALENCE_DMA')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def output_path(path):
    path = path.resolve()
    parent = (ROOT / 'build/fpga').resolve()
    if parent not in path.parents or path == parent or ' ' in str(path):
        raise RuntimeError('Output must be a distinct directory under build/fpga')
    return path


def validate_kernel_config(text):
    net.validate_config(text)
    for name in DEBIAN_CONFIG:
        if 'CONFIG_' + name + '=y' not in text.splitlines():
            raise RuntimeError('Missing Debian userland kernel feature: ' + name)


def prepare(args):
    out = output_path(args.out)
    if args.resume_kernel:
        if not (out / 'linux/.config').is_file() or (out / 'kernel-build.json').exists() or (out / 'manifest.json').exists():
            raise RuntimeError('Resume only an incomplete independent kernel stage, never a completed delivery')
        attempt = out / 'failed-attempts' / str(time.time_ns())
        attempt.mkdir(parents=True)
        for log in out.glob('*.log'):
            shutil.copyfile(log, attempt / log.name)
    else:
        out.mkdir(parents=True, exist_ok=False)
    source = ROOT / 'simulator/build/linux'
    revision = clean_revision(source)
    baseline = args.baseline.resolve()
    baseline_manifest = json.loads((baseline / 'manifest.json').read_text())
    config = baseline / 'linux.config'
    if sha(config) != baseline_manifest['files']['linux.config']['sha256']:
        raise RuntimeError('Baseline kernel configuration changed')
    kernel = out / 'linux'
    kernel.mkdir(exist_ok=args.resume_kernel)
    # mainmenu must remain the first top-level Kconfig statement. Generate an
    # overlay in build output instead of sourcing/patching upstream Kconfig.
    (out / 'Kconfig').write_text((source / 'Kconfig').read_text() + '\n' +
                               (NET / 'Kconfig.valence').read_text())
    shutil.copyfile(config, kernel / '.config')
    make = ['make', 'O=' + str(kernel), 'ARCH=riscv', 'CROSS_COMPILE=riscv64-linux-gnu-',
            'KBUILD_KCONFIG=' + str(out / 'Kconfig')]
    run([source / 'scripts/config', '--file', kernel / '.config',
         *[v for name in DEBIAN_CONFIG for v in ('--enable', name)],
         '--set-str', 'INITRAMFS_SOURCE', ''], log=out / 'config-edit.log')
    run([*make, 'olddefconfig'], cwd=source, log=out / 'config-final.log')
    validate_kernel_config((kernel / '.config').read_text())
    # Build software once, then only embed/relink the completed rootfs later.
    run([*make, '-j' + str(args.jobs), 'Image', 'modules'], cwd=source,
        log=out / 'kernel-build.log', timeout=2400)
    module = out / 'module'
    module.mkdir(exist_ok=args.resume_kernel)
    for name in MODULE_SOURCES:
        shutil.copyfile(NET / name, module / name)
    run([*make, 'M=' + str(module), 'W=1', '-j' + str(args.jobs), 'modules'],
        cwd=source, log=out / 'drivers-build.log', timeout=300)
    log = (out / 'drivers-build.log').read_text()
    if 'warning:' in log or 'error:' in log:
        raise RuntimeError('W=1 driver build produced warnings/errors')
    version = subprocess.check_output([*make, '-s', 'kernelrelease'], cwd=source, text=True).strip()
    for name in MODULES:
        vermagic = subprocess.check_output(['modinfo', '-F', 'vermagic', module / name], text=True)
        if not vermagic.startswith(version + ' '):
            raise RuntimeError('Kernel/module version mismatch: ' + name)
    record = dict(stage='kernel_and_modules_ready', vendor='OpenIon', soc='VL100', cpu='Orbital-A1',
        linux_revision=revision, linux_version=version, cpu_hz=100000000, uart_baud=460800,
        memory_bytes=args.memory_bytes, monitor_base=hex(MemoryLayout(args.memory_bytes).monitor),
        abi='lp64d', isa='rv64gc', smp=False, driver_version='0.3',
        config_sha256=sha(kernel / '.config'), kconfig_overlay_sha256=sha(NET / 'Kconfig.valence'),
        generated_kconfig_sha256=sha(out / 'Kconfig'),
        module_sources={name: sha(module / name) for name in MODULE_SOURCES},
        modules={name: sha(module / name) for name in MODULES}, board_verified=False,
        rootfs_embedded=False, kernel_fpu=True, rtl_or_bit_generated=False)
    (out / 'kernel-build.json').write_text(json.dumps(record, indent=2) + '\n')
    print('VL100_DEBIAN_KERNEL_MODULES_READY ' + str(out), flush=True)


def image(args):
    out = output_path(args.out)
    record = json.loads((out / 'kernel-build.json').read_text())
    if record['stage'] != 'kernel_and_modules_ready':
        raise RuntimeError('Build a new kernel stage before embedding a rootfs')
    source = ROOT / 'simulator/build/linux'
    if clean_revision(source) != record['linux_revision']:
        raise RuntimeError('Kernel source revision drift')
    root = output_path(args.rootfs_out)
    if Path(args.rootfs_record).name != args.rootfs_record or not args.rootfs_record.startswith('rootfs-build') or not args.rootfs_record.endswith('.json'):
        raise RuntimeError('Unexpected rootfs record name')
    root_record = json.loads((root / args.rootfs_record).read_text())
    if root_record.get('stage') != 'packed' or root_record.get('kernel_build') != str(out):
        raise RuntimeError('Rootfs must contain these exact kernel modules')
    cpio = root / root_record['archive']['path']
    if sha(cpio) != root_record['archive']['sha256']:
        raise RuntimeError('Rootfs archive changed after packing')
    kernel = out / 'linux'
    if sha(kernel / '.config') != record['config_sha256']:
        # Empty INITRAMFS_SOURCE hides ownership/compression choice symbols.
        # Accept exactly their expected derivation, not unrelated config drift.
        current = (kernel / '.config').read_text()
        for symbol in ('ROOT_UID', 'ROOT_GID'):
            if 'CONFIG_INITRAMFS_' + symbol + '=0' not in current.splitlines():
                raise RuntimeError('Unexpected initramfs ownership')
        validate_kernel_config(current)
        normalized = re.sub(r'(?m)^CONFIG_INITRAMFS_SOURCE=.*$', 'CONFIG_INITRAMFS_SOURCE=""',
                            current)
        normalized = re.sub(r'(?m)^(?:# )?CONFIG_INITRAMFS_(?:ROOT_UID|ROOT_GID|COMPRESSION_[A-Z0-9]+).*\n',
                            '', normalized)
        if hashlib.sha256(normalized.encode()).hexdigest() != record['config_sha256']:
            raise RuntimeError('Kernel configuration drift before embedding')
    for name in MODULES:
        if sha(out / 'module' / name) != record['modules'][name]:
            raise RuntimeError('Module drift: ' + name)
    delivery = output_path(args.delivery_out) if args.delivery_out is not None else out
    if delivery != out:
        delivery.mkdir(parents=True, exist_ok=False)
    if sha(NET / 'Kconfig.valence') != record['kconfig_overlay_sha256']:
        raise RuntimeError('Kconfig overlay drift')
    if sha(out / 'Kconfig') != record['generated_kconfig_sha256']:
        raise RuntimeError('Generated Kconfig drift')
    make = ['make', 'O=' + str(kernel), 'ARCH=riscv', 'CROSS_COMPILE=riscv64-linux-gnu-',
            'KBUILD_KCONFIG=' + str(out / 'Kconfig')]
    run([source / 'scripts/config', '--file', kernel / '.config', '--set-str',
         'INITRAMFS_SOURCE', str(cpio)])
    run([*make, 'olddefconfig'], cwd=source, log=out / 'config-rootfs.log')
    validate_kernel_config((kernel / '.config').read_text())
    run([*make, '-j' + str(args.jobs), 'Image'], cwd=source,
        log=out / 'kernel-rootfs.log', timeout=600)
    linux_image = kernel / 'arch/riscv/boot/Image'
    layout = MemoryLayout(record['memory_bytes'])
    runtime = image_header(linux_image, layout.monitor)
    if runtime + root_record['rootfs_file_bytes'] + 64*1024*1024 > layout.ram_bytes:
        raise RuntimeError('Insufficient conservative RAM budget for image + rootfs + 64 MiB reserve')
    embedded = (kernel / 'usr/initramfs_inc_data').read_bytes()
    if not embedded.startswith(b'\x1f\x8b') or linux_image.read_bytes().count(embedded) != 1:
        raise RuntimeError('Exact compressed rootfs not embedded once in Image')
    if gzip.decompress(embedded) != cpio.read_bytes():
        raise RuntimeError('Embedded rootfs differs from signed/packed rootfs')
    dts, dtb = delivery / 'valence-vl100.dts', delivery / 'valence-vl100.dtb'
    dts.write_text(net.network_dts(layout.ram_bytes, platform_drivers=True))
    dtc = kernel / 'scripts/dtc/dtc'
    run([dtc, '-q', '-I', 'dts', '-O', 'dtb', '-o', dtb, dts])
    net.validate_dtb(dtc, dtb)
    if dtb.stat().st_size + 8192 > 0x10000:
        raise RuntimeError('DTB exceeds reserved slot')
    opensbi = opensbi_setup(False)
    run(['make', '-j' + str(args.jobs), 'PLATFORM=generic', 'CROSS_COMPILE=riscv64-linux-gnu-',
         'PLATFORM_RISCV_ISA=rv64imac_zicsr_zifencei', 'PLATFORM_RISCV_ABI=lp64',
         'FW_TEXT_START=0x80200000', 'FW_DYNAMIC=n', 'FW_JUMP=n', 'FW_PAYLOAD=y',
         'FW_PAYLOAD_OFFSET=0x200000', 'FW_PAYLOAD_FDT_ADDR=0x80300000', 'FW_FDT_PADDING=8192',
         'FW_FDT_PATH=' + str(dtb), 'FW_PAYLOAD_PATH=' + str(linux_image), 'O=' + str(out / 'opensbi')],
        cwd=opensbi, log=out / 'opensbi-build.log', timeout=600)
    firmware = out / 'opensbi/platform/generic/firmware/fw_payload.bin'
    content = firmware.read_bytes()
    net.validate_embedded_dtb(content, dtb.read_bytes())
    padding = validate_payload(content, linux_image.read_bytes(), layout.monitor)
    elf = firmware.with_suffix('.elf')
    symbols = {line.split()[2]: int(line.split()[0], 16) for line in
        subprocess.check_output(['riscv64-linux-gnu-nm', elf], text=True).splitlines()
        if len(line.split()) == 3}
    if symbols.get('_fw_start') != LOAD or symbols.get('payload_bin') != KERNEL or not LOAD < symbols.get('_fw_end', MONITOR) <= DTB:
        raise RuntimeError('Unexpected OpenSBI/kernel/DTB memory layout')
    result = delivery / 'opensbi_debian13_riscv64_vl100_cpu100_u460800.bin'
    shutil.copyfile(firmware, result)
    # Match the configured BootROM RRQ; the server intentionally checks basename.
    vld = delivery / 'valence.vld'
    profile = {0x20000000: 'ddr', 0x40000000: 'ddr1g', 0x80000000: 'ddr2g'}[layout.ram_bytes]
    run([sys.executable, HERE.parent / 'netboot_host.py', 'pack', result, '--out', vld, '--memory', profile],
        log=out / 'netboot-pack.log')
    shutil.copyfile(kernel / '.config', delivery / 'linux.config')
    for tool in ('netboot_host.py', 'uart_load.py'):
        shutil.copyfile(HERE.parent / tool, delivery / tool)
    shutil.copyfile(NET / 'net_bench_peer.py', delivery / 'net_bench_peer.py')
    manifest = dict(**record)
    manifest.update(stage='firmware_ready_not_board_verified', rootfs=root_record,
        rootfs_embedded=True, kernel_prepare_config_sha256=record['config_sha256'],
        config_sha256=sha(kernel / '.config'),
        kernel_runtime_bytes=runtime, bootargs=net.BOOTARGS, opensbi_revision=OPENSBI_LOCK['revision'],
        entry=hex(LOAD), kernel_entry=hex(KERNEL), payload_zero_padding_bytes=padding,
        network_auto_enable=root_record['network_auto_enable'], persistent_storage=False, systemd=False,
        kernel_cache=str(out), rootfs_record=args.rootfs_record,
        bit_included=False, required_rtl_fix='CoherentLineHome stalled direct read offer retention',
        memory_profile=profile, full_address_translation_required=layout.ram_bytes == 0x80000000,
        sources={str(p.relative_to(ROOT)): sha(p) for p in [Path(__file__),
            HERE / 'build_rootfs.py', HERE.parent / 'build_linux.py', NET / 'build_image.py',
            *[NET / name for name in MODULE_SOURCES]]},
        files={p.name: dict(bytes=p.stat().st_size, sha256=sha(p)) for p in
            (result, vld, dtb, dts, delivery / 'linux.config', delivery / 'netboot_host.py',
             delivery / 'uart_load.py', delivery / 'net_bench_peer.py')})
    (delivery / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('VL100_DEBIAN_FIRMWARE_READY_NOT_BOARD_VERIFIED ' + str(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('kernel', 'image'), required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--rootfs-out', type=Path)
    parser.add_argument('--rootfs-record', default='rootfs-build.json')
    parser.add_argument('--delivery-out', type=Path, help='separate new release directory while reusing own kernel objects')
    parser.add_argument('--baseline', type=Path, default=ROOT / 'build/fpga/linux-net-rv64gc-20261006-r3')
    parser.add_argument('--jobs', type=int, default=min(os.cpu_count() or 8, 16))
    parser.add_argument('--memory-bytes', type=lambda s: int(s, 0), default=0x80000000,
                        choices=(0x20000000, 0x40000000, 0x80000000))
    parser.add_argument('--resume-kernel', action='store_true', help='retry an incomplete software build; retain failed logs')
    args = parser.parse_args()
    if args.jobs < 1 or (args.stage == 'image' and args.rootfs_out is None):
        parser.error('positive --jobs required; --stage image requires --rootfs-out')
    (prepare if args.stage == 'kernel' else image)(args)
