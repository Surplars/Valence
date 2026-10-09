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
sys.path[:0] = [str(NET), str(HERE.parent), str(HERE.parent / 'linux_uart'), str(ROOT / 'simulator/gsim')]
# Avoid importing this file as build_image when importing the existing helper.
import importlib.util
spec = importlib.util.spec_from_file_location('valence_network_image', NET / 'build_image.py')
net = importlib.util.module_from_spec(spec)
spec.loader.exec_module(net)
from build_linux import clean_revision, image_header, validate_payload, validate_payload_elf, LOAD, KERNEL, DTB, MONITOR
from run import run, opensbi_setup, OPENSBI_LOCK
from memory_layout import MemoryLayout
from kernel_proc_contract import validate as validate_uart_proc

MODULE_SOURCES = ('Makefile', 'valence_gmac.c', 'valence_aia.c', 'valence_soc.c', 'valence_cmu.c', 'valence_dma.c',
                  'valence_irq_policy.h', 'valence_driver_names.h', 'valence_rx_queue.h', 'valence_tx_queue.h', 'valence_media_policy.h')
MODULES = ('valence_aia.ko', 'valence_gmac.ko', 'valence_soc.ko', 'valence_cmu.ko', 'valence_dma.ko')
DEBIAN_CONFIG = ('SOC_BUS', 'SYSVIPC', 'SIGNALFD', 'TIMERFD', 'EVENTFD',
                 'INOTIFY_USER', 'AIO', 'FILE_LOCKING', 'ADVISE_SYSCALLS',
                 'KALLSYMS', 'UNIX_DIAG', 'INET_UDP_DIAG', 'INET_RAW_DIAG', 'SHMEM', 'TMPFS',
                 'COMMON_CLK', 'DMADEVICES', 'DMA_OF', 'DMA_ENGINE', 'DMA_VIRTUAL_CHANNELS', 'VALENCE_CMU', 'VALENCE_DMA')
SYSTEMD_CONFIG = ('CGROUPS', 'CGROUP_PIDS', 'MEMCG', 'CGROUP_SCHED',
                  'CGROUP_CPUACCT', 'NAMESPACES', 'UTS_NS', 'IPC_NS', 'PID_NS',
                  'NET_NS', 'USER_NS', 'FHANDLE', 'SECCOMP',
                  'SECCOMP_FILTER', 'TMPFS_XATTR', 'TMPFS_POSIX_ACL', 'AUTOFS_FS')
# Show the exact populate_rootfs elapsed time at the UART, not only in dmesg.
SYSTEMD_BOOTARGS = net.BOOTARGS.replace('loglevel=7', 'loglevel=8') + ' systemd.show_status=1'
DINIT_BOOTARGS = net.BOOTARGS.replace('loglevel=7', 'loglevel=8')


def profile_bootargs(init_system, console_profile="sbi"):
    return net.uart_console.bootargs({'busybox': net.BOOTARGS, 'systemd': SYSTEMD_BOOTARGS,
            'dinit': DINIT_BOOTARGS}[init_system], console_profile)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def output_path(path):
    path = path.resolve()
    parent = (ROOT / 'build/fpga').resolve()
    if parent not in path.parents or path == parent or ' ' in str(path):
        raise RuntimeError('Output must be a distinct directory under build/fpga')
    return path


def validate_kernel_config(text, init_system='busybox', console_profile='sbi'):
    bootargs = profile_bootargs(init_system, console_profile)
    net.validate_config(text, bootargs=bootargs, console_profile=console_profile)
    for name in DEBIAN_CONFIG + (SYSTEMD_CONFIG if init_system == 'systemd' else ()):
        if 'CONFIG_' + name + '=y' not in text.splitlines():
            raise RuntimeError('Missing Debian userland kernel feature: ' + name)
    if init_system in ('systemd', 'dinit') and 'CONFIG_LOG_BUF_SHIFT=20' not in text.splitlines():
        raise RuntimeError('Diagnostic image needs a 1 MiB boot log buffer')


def prepare(args):
    console_profile = getattr(args, 'console', 'sbi')
    net.uart_console.check_profile(console_profile)
    if console_profile == 'uart-irq' and args.init_system != 'dinit':
        raise RuntimeError('IRQ UART bootstrap is qualified only for the Dinit profile')
    out = output_path(args.out)
    if args.reuse_kernel is not None and args.resume_kernel:
        raise RuntimeError('Reuse is only for a fresh independent output, not resume')
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
    uart_proc_contract = (validate_uart_proc(source, HERE / 'dinit/uart-irq-init')
                          if console_profile == 'uart-irq' else None)
    baseline = args.baseline.resolve()
    baseline_manifest = json.loads((baseline / 'manifest.json').read_text())
    config = baseline / 'linux.config'
    if sha(config) != baseline_manifest['files']['linux.config']['sha256']:
        raise RuntimeError('Baseline kernel configuration changed')
    kernel = out / 'linux'
    if args.reuse_kernel is not None:
        reuse = output_path(args.reuse_kernel)
        reuse_record = json.loads((reuse / 'kernel-build.json').read_text())
        if (reuse_record.get('linux_revision') != revision or
                baseline_manifest.get('kernel_cache') != str(reuse) or
                sha(reuse / 'linux/.config') != baseline_manifest['files']['linux.config']['sha256']):
            raise RuntimeError('Only a matching, completed baseline kernel can seed the new cache')
        for name, digest in reuse_record['modules'].items():
            if sha(reuse / 'module' / name) != digest:
                raise RuntimeError('Reuse module drift: ' + name)
        run(['cp', '-a', '--reflink=auto', reuse / 'linux', kernel], log=out / 'reuse-cache.log')
    kernel.mkdir(exist_ok=args.resume_kernel or args.reuse_kernel is not None)
    # mainmenu must remain the first top-level Kconfig statement. Generate an
    # overlay in build output instead of sourcing/patching upstream Kconfig.
    (out / 'Kconfig').write_text((source / 'Kconfig').read_text() + '\n' +
                               (NET / 'Kconfig.valence').read_text())
    shutil.copyfile(config, kernel / '.config')
    make = ['make', 'O=' + str(kernel), 'ARCH=riscv', 'CROSS_COMPILE=riscv64-linux-gnu-',
            'KBUILD_KCONFIG=' + str(out / 'Kconfig')]
    features = DEBIAN_CONFIG + (SYSTEMD_CONFIG if args.init_system == 'systemd' else ())
    edit = [source / 'scripts/config', '--file', kernel / '.config',
            *[v for name in features for v in ('--enable', name)],
            '--set-str', 'INITRAMFS_SOURCE', '']
    edit += net.uart_console.config_flags(console_profile)
    edit += ['--set-str', 'CMDLINE', profile_bootargs(args.init_system, console_profile)]
    if args.init_system in ('systemd', 'dinit'):
        edit += ['--set-val', 'LOG_BUF_SHIFT', '20']
    compression = args.initramfs_compression or ('lz4' if args.init_system == 'dinit' else 'gzip')
    edit += ['--enable', 'RD_' + compression.upper()]
    run(edit, log=out / 'config-edit.log')
    run([*make, 'olddefconfig'], cwd=source, log=out / 'config-final.log')
    validate_kernel_config((kernel / '.config').read_text(), args.init_system, console_profile)
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
        rootfs_embedded=False, kernel_fpu=True, rtl_or_bit_generated=False,
        init_system=args.init_system,
        initramfs_compression=compression,
        reused_kernel_cache=str(args.reuse_kernel.resolve()) if args.reuse_kernel else None,
        bootargs=profile_bootargs(args.init_system, console_profile),
        console_profile=console_profile, runtime_uart_irq_requested=console_profile == 'uart-irq',
        uart_irq_source=3 if console_profile == 'uart-irq' else None,
        uart_irq_runtime_verified=False, uart_proc_contract=uart_proc_contract)
    (out / 'kernel-build.json').write_text(json.dumps(record, indent=2) + '\n')
    print('VL100_DEBIAN_KERNEL_MODULES_READY ' + str(out), flush=True)


def export_stage2_payload(linux_image, delivery):
    """Expose the already-validated Linux bytes for U-Boot, without repackaging."""
    raw = delivery / 'Image'
    shutil.copyfile(linux_image, raw)
    if sha(raw) != sha(linux_image):
        raise RuntimeError('Raw stage-2 Linux Image copy changed')
    return raw, dict(format='raw-riscv-linux-Image', image=raw.name,
        runtime_dtb='valence-vl100.dtb', kernel_entry=hex(KERNEL),
        initramfs='embedded', separate_initrd=False, board_verified=False,
        note='U-Boot may stage Image elsewhere and relocate with booti; do not boot valence.vld as Image')


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
    init_system = record.get('init_system', 'busybox')
    if root_record.get('init_system', 'busybox') != init_system:
        raise RuntimeError('Kernel and rootfs init profiles differ')
    console_profile = record.get('console_profile', 'sbi')
    if console_profile == 'uart-irq':
        contract = validate_uart_proc(source, HERE / 'dinit/uart-irq-init')
        if record.get('uart_proc_contract') != contract:
            raise RuntimeError('Re-qualify the kernel stage against the pinned UART proc contract')
    if root_record.get('console_profile', 'sbi') != console_profile:
        raise RuntimeError('Kernel and rootfs console owners differ')
    bootargs = record.get('bootargs', net.BOOTARGS)
    compression = record.get('initramfs_compression', 'gzip')
    if compression not in ('gzip', 'lz4'):
        raise RuntimeError('Unsupported initramfs compression profile')
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
        validate_kernel_config(current, init_system, console_profile)
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
    compression_flags = [v for algorithm in ('GZIP', 'BZIP2', 'LZMA', 'XZ', 'LZO', 'LZ4', 'ZSTD', 'NONE')
        for v in ('--enable' if algorithm.lower() == compression else '--disable',
                  'INITRAMFS_COMPRESSION_' + algorithm)]
    run([source / 'scripts/config', '--file', kernel / '.config', '--set-str',
         'INITRAMFS_SOURCE', str(cpio), *compression_flags])
    run([*make, 'olddefconfig'], cwd=source, log=out / 'config-rootfs.log')
    validate_kernel_config((kernel / '.config').read_text(), init_system, console_profile)
    if 'CONFIG_INITRAMFS_COMPRESSION_' + compression.upper() + '=y' not in (kernel / '.config').read_text().splitlines():
        raise RuntimeError('Initramfs compression choice was not selected')
    run([*make, '-j' + str(args.jobs), 'Image'], cwd=source,
        log=out / 'kernel-rootfs.log', timeout=600)
    linux_image = kernel / 'arch/riscv/boot/Image'
    layout = MemoryLayout(record['memory_bytes'])
    payload_limit = layout.monitor - (0x80000 if layout.ram_bytes == 0x80000000 else 0)
    runtime = image_header(linux_image, payload_limit)
    if runtime + root_record['rootfs_file_bytes'] + 64*1024*1024 > layout.ram_bytes:
        raise RuntimeError('Insufficient conservative RAM budget for image + rootfs + 64 MiB reserve')
    embedded = (kernel / 'usr/initramfs_inc_data').read_bytes()
    magic = b'\x1f\x8b' if compression == 'gzip' else b'\x02\x21\x4c\x18'
    if not embedded.startswith(magic) or linux_image.read_bytes().count(embedded) != 1:
        raise RuntimeError('Exact compressed rootfs not embedded once in Image')
    unpacked = (gzip.decompress(embedded) if compression == 'gzip' else
        subprocess.check_output(['lz4', '-d', '-c'], input=embedded))
    if unpacked != cpio.read_bytes():
        raise RuntimeError('Embedded rootfs differs from signed/packed rootfs')
    dts, dtb = delivery / 'valence-vl100.dts', delivery / 'valence-vl100.dtb'
    dts.write_text(net.network_dts(layout.ram_bytes, platform_drivers=True, bootargs=bootargs,
        console_profile=console_profile))
    dtc = kernel / 'scripts/dtc/dtc'
    run([dtc, '-q', '-I', 'dts', '-O', 'dtb', '-o', dtb, dts])
    net.validate_dtb(dtc, dtb, bootargs=bootargs, console_profile=console_profile)
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
    padding = validate_payload(content, linux_image.read_bytes(), payload_limit)
    elf = firmware.with_suffix('.elf')
    elf_binding = validate_payload_elf(elf.read_bytes(), content, linux_image.read_bytes(), payload_limit)
    symbols = {line.split()[2]: int(line.split()[0], 16) for line in
        subprocess.check_output(['riscv64-linux-gnu-nm', elf], text=True).splitlines()
        if len(line.split()) == 3}
    if symbols.get('_fw_start') != LOAD or symbols.get('payload_bin') != KERNEL or not LOAD < symbols.get('_fw_end', MONITOR) <= DTB:
        raise RuntimeError('Unexpected OpenSBI/kernel/DTB memory layout')
    suffix = '_systemd' if init_system == 'systemd' else ('_dinit_' + compression if init_system == 'dinit' else '')
    if console_profile == 'uart-irq':
        suffix += '_uart_irq'
    result = delivery / ('opensbi_debian13_riscv64_vl100_cpu100_u460800' + suffix + '.bin')
    shutil.copyfile(firmware, result)
    # Match the configured BootROM RRQ; the server intentionally checks basename.
    vld = delivery / 'valence.vld'
    profile = {0x20000000: 'ddr', 0x40000000: 'ddr1g', 0x80000000: 'ddr2g-menu'}[layout.ram_bytes]
    run([sys.executable, HERE.parent / 'netboot_host.py', 'pack', result, '--out', vld, '--memory', profile],
        log=out / 'netboot-pack.log')
    raw_image, stage2 = export_stage2_payload(linux_image, delivery)
    shutil.copyfile(kernel / '.config', delivery / 'linux.config')
    for tool in ('netboot_host.py', 'uart_load.py'):
        shutil.copyfile(HERE.parent / tool, delivery / tool)
    shutil.copyfile(NET / 'net_bench_peer.py', delivery / 'net_bench_peer.py')
    manifest = dict(**record)
    manifest.update(stage='firmware_ready_not_board_verified', rootfs=root_record,
        rootfs_embedded=True, stage2_payload=stage2, kernel_prepare_config_sha256=record['config_sha256'],
        config_sha256=sha(kernel / '.config'),
        kernel_runtime_bytes=runtime, bootargs=bootargs, opensbi_revision=OPENSBI_LOCK['revision'],
        entry=hex(LOAD), kernel_entry=hex(KERNEL), payload_alignment_padding_bytes=padding,
        payload_alignment_padding_hex=content[KERNEL - LOAD + linux_image.stat().st_size:].hex(),
        payload_elf_binding=elf_binding,
        network_auto_enable=root_record['network_auto_enable'], persistent_storage=False,
        systemd=init_system == 'systemd',
        dinit=init_system == 'dinit', initramfs_compression=compression,
        kernel_cache=str(out), rootfs_record=args.rootfs_record,
        bit_included=False, required_rtl_fix='CoherentLineHome stalled direct read offer retention',
        memory_profile=profile, full_address_translation_required=layout.ram_bytes == 0x80000000,
        sources={str(p.relative_to(ROOT)): sha(p) for p in [Path(__file__),
            HERE / 'build_rootfs.py', HERE.parent / 'build_linux.py', NET / 'build_image.py', NET / 'uart_console.py',
            HERE.parent / 'linux_uart/kernel_proc_contract.py',
            *[NET / name for name in MODULE_SOURCES]]},
        files={p.name: dict(bytes=p.stat().st_size, sha256=sha(p)) for p in
            (result, vld, raw_image, dtb, dts, delivery / 'linux.config', delivery / 'netboot_host.py',
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
    parser.add_argument('--reuse-kernel', type=Path, help='seed a fresh independent output with a matching completed kernel cache')
    parser.add_argument('--initramfs-compression', choices=('gzip', 'lz4'),
                        help='dinit defaults to LZ4; legacy profiles default to gzip')
    parser.add_argument('--console', choices=net.uart_console.PROFILES, default='sbi',
                        help='kernel stage: uart-irq selects ttyS0; sbi retains polling recovery')
    parser.add_argument('--init-system', choices=('dinit', 'systemd', 'busybox'), default='dinit',
                        help='new builds use dinit; other profiles remain explicit alternatives')
    args = parser.parse_args()
    if args.jobs < 1 or (args.stage == 'image' and args.rootfs_out is None):
        parser.error('positive --jobs required; --stage image requires --rootfs-out')
    (prepare if args.stage == 'kernel' else image)(args)
