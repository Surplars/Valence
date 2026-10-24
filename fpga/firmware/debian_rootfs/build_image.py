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
import common_linux_profile as common
import sbi_console_handoff
from kernel_proc_contract import validate as validate_uart_proc

MODULE_SOURCES = ('Makefile', 'valence_gmac.c', 'valence_aia.c', 'valence_soc.c', 'valence_cmu.c', 'valence_dma.c',
                  'valence_irq_policy.h', 'valence_driver_names.h', 'valence_rx_queue.h', 'valence_tx_queue.h', 'valence_media_policy.h', 'valence_clockmon.c', 'valence_clockmon_abi.h', 'valence_cpu_rate_transaction.h')
MODULES = ('valence_aia.ko', 'valence_gmac.ko', 'valence_soc.ko', 'valence_cmu.ko', 'valence_dma.ko', 'valence_clockmon.ko')
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
    common_mode = getattr(args, 'platform', 'legacy') == common.PROFILE
    if common_mode and (args.init_system not in ('busybox', 'dinit') or console_profile != 'sbi'):
        raise RuntimeError('Common profile requires matched BusyBox or Debian Dinit rootfs and SBI console')
    if common_mode and args.memory_bytes != 0x80000000:
        raise RuntimeError('CommonMachinePlatform requires2GiB')
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
    baseline = args.baseline.resolve() if args.baseline else None
    baseline_manifest = json.loads((baseline / 'manifest.json').read_text()) if baseline else None
    config = baseline / 'linux.config' if baseline else None
    if config and sha(config) != baseline_manifest['files']['linux.config']['sha256']:
        raise RuntimeError('Baseline kernel configuration changed')
    if not baseline and not common_mode:
        raise RuntimeError('Legacy builds require an explicit baseline')
    if args.reuse_kernel is not None and not baseline:
        raise RuntimeError('Reuse requires a bound baseline manifest')
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
    if config:
        shutil.copyfile(config, kernel / '.config')
    make = ['make', 'O=' + str(kernel), 'ARCH=riscv', 'CROSS_COMPILE=riscv64-linux-gnu-',
            'KBUILD_KCONFIG=' + str(out / 'Kconfig')]
    if config is None and not args.resume_kernel:
        run([*make, 'tinyconfig'], cwd=source, log=out / 'config-base.log')
    features = DEBIAN_CONFIG + (SYSTEMD_CONFIG if args.init_system == 'systemd' else ())
    edit = [source / 'scripts/config', '--file', kernel / '.config',
            *[v for name in features for v in ('--enable', name)],
            '--set-str', 'INITRAMFS_SOURCE', '']
    if common_mode:
        edit += [v for name in net.ENABLED for v in ('--enable', name)]
        edit += [v for name in net.DISABLED for v in ('--disable', name)]
        edit += ['--module', 'VALENCE_SOC']
    edit += net.uart_console.config_flags(console_profile)
    optimization = getattr(args, 'kernel_optimization', 'size')
    if args.resume_kernel and ('CONFIG_CC_OPTIMIZE_FOR_' + optimization.upper() + '=y') not in (kernel/'.config').read_text().splitlines():
        raise RuntimeError('Resume must retain the existing compiler policy; use a fresh output to change it')
    edit += ['--enable', 'CC_OPTIMIZE_FOR_' + optimization.upper(),
             '--disable', 'CC_OPTIMIZE_FOR_' + ('SIZE' if optimization == 'performance' else 'PERFORMANCE')]
    edit += ['--set-str', 'CMDLINE', profile_bootargs(args.init_system, console_profile)]
    if args.init_system in ('systemd', 'dinit'):
        edit += ['--set-val', 'LOG_BUF_SHIFT', '20']
    compression = args.initramfs_compression or ('lz4' if args.init_system == 'dinit' else 'gzip')
    edit += ['--enable', 'RD_' + compression.upper()]
    run(edit, log=out / 'config-edit.log')
    run([*make, 'olddefconfig'], cwd=source, log=out / 'config-final.log')
    validate_kernel_config((kernel / '.config').read_text(), args.init_system, console_profile)
    if 'CONFIG_CC_OPTIMIZE_FOR_' + optimization.upper() + '=y' not in (kernel/'.config').read_text().splitlines():
        raise RuntimeError('Kernel compiler optimization selection was not honored')
    if common_mode:
        selected_modules = {line.split('=')[0] for line in (kernel / '.config').read_text().splitlines() if line.endswith('=m')}
        if selected_modules - {'CONFIG_VALENCE_SOC'}:
            raise RuntimeError('Common rootfs lacks in-tree module installation for: ' + str(sorted(selected_modules)))
    # Build software once, then only embed/relink the completed rootfs later.
    run([*make, '-j' + str(args.jobs), 'Image', 'modules'], cwd=source,
        log=out / 'kernel-build.log', timeout=2400)
    module = out / 'module'
    module.mkdir(exist_ok=args.resume_kernel)
    module_sources = MODULE_SOURCES if common_mode else tuple(n for n in MODULE_SOURCES if 'clockmon' not in n and 'cpu_rate_transaction' not in n)
    modules = MODULES if common_mode else tuple(n for n in MODULES if 'clockmon' not in n and 'cpu_rate_transaction' not in n)
    for name in module_sources:
        shutil.copyfile(NET / name, module / name)
    run([*make, 'M=' + str(module), 'CONFIG_VALENCE_CLOCKMON=' + ('m' if common_mode else 'n'), 'W=1', '-j' + str(args.jobs), 'modules'],
        cwd=source, log=out / 'drivers-build.log', timeout=300)
    log = (out / 'drivers-build.log').read_text()
    if 'warning:' in log or 'error:' in log:
        raise RuntimeError('W=1 driver build produced warnings/errors')
    version = subprocess.check_output([*make, '-s', 'kernelrelease'], cwd=source, text=True).strip()
    module_vermagic, module_dependencies = {}, {}
    for name in modules:
        vermagic = subprocess.check_output(['modinfo', '-F', 'vermagic', module / name], text=True)
        module_vermagic[name] = vermagic.strip()
        module_dependencies[name] = subprocess.check_output(['modinfo', '-F', 'depends', module / name], text=True).strip().split(',')
        module_dependencies[name] = [n for n in module_dependencies[name] if n]
        if not vermagic.startswith(version + ' '):
            raise RuntimeError('Kernel/module version mismatch: ' + name)
    record = dict(stage='kernel_and_modules_ready', vendor='OpenIon', soc='VL100', cpu='Orbital-A1',
        linux_revision=revision, linux_version=version, cpu_hz=100000000, uart_baud=460800,
        kernel_optimization=optimization, compiler_optimization_flag='-O2' if optimization == 'performance' else '-Os',
        memory_bytes=args.memory_bytes, monitor_base=hex(MemoryLayout(args.memory_bytes).monitor),
        abi='lp64d', isa='rv64gc', smp=False, driver_version='0.3',
        config_sha256=sha(kernel / '.config'), kconfig_overlay_sha256=sha(NET / 'Kconfig.valence'),
        generated_kconfig_sha256=sha(out / 'Kconfig'),
        module_sources={name: sha(module / name) for name in module_sources},
        modules={name: sha(module / name) for name in modules}, board_verified=False,
        module_vermagic=module_vermagic, module_dependencies=module_dependencies,
        rootfs_embedded=False, kernel_fpu=True, rtl_or_bit_generated=False,
        init_system=args.init_system,
        initramfs_compression=compression,
        reused_kernel_cache=str(args.reuse_kernel.resolve()) if args.reuse_kernel else None,
        bootargs=profile_bootargs(args.init_system, console_profile),
        console_profile=console_profile, runtime_uart_irq_requested=console_profile == 'uart-irq',
        uart_irq_source=3 if console_profile == 'uart-irq' else None,
        uart_irq_runtime_verified=False, uart_proc_contract=uart_proc_contract)
    if common_mode:
        record.update(cpu='CommonMachinePlatform I1/A1', cpu_hz=50000000,
                      timebase_hz=250000000, fabric_hz=50000000, common_platform=common.CONTRACT,
                      common_profile_source_sha256=sha(HERE / 'common_linux_profile.py'),
                      runtime_clock_monitor_profiles={'i1': True, 'a1': False, common.EXPERIMENTAL_A1: common.A1_MONITOR in (module/'valence_clockmon.c').read_text()})
    (out / 'kernel-build.json').write_text(json.dumps(record, indent=2) + '\n')
    print('VL100_DEBIAN_KERNEL_MODULES_READY ' + str(out), flush=True)


def refresh_modules(args):
    """Rebuild only changed external drivers against a frozen completed kernel."""
    out = output_path(args.out)
    path = out / 'kernel-build.json'
    record = json.loads(path.read_text())
    common.check_record(record)
    if record.get('stage') != 'kernel_and_modules_ready' or (out / 'common-manifest.json').exists() or (out / 'delivery-receipt.json').exists():
        raise RuntimeError('Refresh only prepared, undelivered common kernel')
    source = ROOT / 'simulator/build/linux'
    if clean_revision(source) != record['linux_revision'] or sha(out / 'linux/.config') != record['config_sha256']:
        raise RuntimeError('Cannot refresh drivers against changed kernel')
    if sha(out / 'Kconfig') != record['generated_kconfig_sha256'] or sha(NET / 'Kconfig.valence') != record['kconfig_overlay_sha256']:
        raise RuntimeError('Kconfig drift before module refresh')
    archive = out / 'module-attempts' / str(time.time_ns())
    archive.mkdir(parents=True)
    shutil.copyfile(path, archive / 'kernel-build.json')
    shutil.copytree(out / 'module', archive / 'module')
    module = out / 'module'
    for name in MODULE_SOURCES:
        shutil.copyfile(NET / name, module / name)
    make = ['make', 'O=' + str(out / 'linux'), 'ARCH=riscv', 'CROSS_COMPILE=riscv64-linux-gnu-',
            'KBUILD_KCONFIG=' + str(out / 'Kconfig')]
    run([*make, 'M=' + str(module), 'CONFIG_VALENCE_CLOCKMON=m', 'W=1', '-j' + str(args.jobs), 'modules'],
        cwd=source, log=out / 'drivers-refresh.log', timeout=300)
    log = (out / 'drivers-refresh.log').read_text()
    if 'warning:' in log or 'error:' in log:
        raise RuntimeError('Refreshed modules have warnings/errors')
    vermagic, dependencies = {}, {}
    for name in MODULES:
        vermagic[name] = subprocess.check_output(['modinfo','-F','vermagic',module/name],text=True).strip()
        if not vermagic[name].startswith(record['linux_version'] + ' '):
            raise RuntimeError('Refreshed module vermagic mismatch: ' + name)
        dependencies[name] = [n for n in subprocess.check_output(
            ['modinfo','-F','depends',module/name],text=True).strip().split(',') if n]
    record.update(module_sources={name:sha(module/name) for name in MODULE_SOURCES},
                  modules={name:sha(module/name) for name in MODULES},
                  module_vermagic=vermagic,module_dependencies=dependencies,
                  module_refresh_previous_receipt=str(archive/'kernel-build.json'),
                  common_profile_source_sha256=sha(HERE/'common_linux_profile.py'),
                  runtime_clock_monitor_profiles={'i1': True, 'a1': False, common.EXPERIMENTAL_A1: common.A1_MONITOR in (module/'valence_clockmon.c').read_text()})
    path.write_text(json.dumps(record,indent=2)+'\n')
    print('COMMON_EXTERNAL_MODULES_REFRESHED ' + str(path),flush=True)


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
    common_mode = record.get('common_platform') is not None
    if common_mode:
        common.check_record(record)
        if record.get('init_system') not in ('busybox', 'dinit') or record.get('console_profile') != 'sbi':
            raise RuntimeError('Common image requires matched BusyBox/Dinit SBI profile')
    if (getattr(args, 'platform', 'legacy') == common.PROFILE) != common_mode:
        raise RuntimeError('Image platform must match prepared kernel profile')
    if getattr(args, 'i1_boot_cpu_hz', 50000000) != 50000000:
        if not common_mode or record.get('init_system') != 'dinit' or 'valence_cpu_rate_transaction.h' not in record['module_sources']:
            raise RuntimeError('Boot125 requires the new common Debian Dinit/control-driver candidate')
    if getattr(args, 'i1_boot_fabric_hz', 50000000) != 50000000:
        if getattr(args, 'i1_boot_cpu_hz', 50000000) != 125000000 or 'openion,i1-boot-pair-125' not in (out/'module/valence_clockmon.c').read_text():
            raise RuntimeError('Boot fabric125 requires the exact paired-control driver candidate')
    experimental_a1 = getattr(args, 'experimental_a1_runtime', False)
    hardware_contract = getattr(args, 'a1_runtime_hardware_contract', None)
    if experimental_a1 != bool(hardware_contract):
        raise RuntimeError('Experimental A1 requires both explicit flag and hardware contract')
    if experimental_a1:
        if not common_mode or record.get('init_system') != 'dinit' or args.i1_boot_cpu_hz != 50000000 or args.i1_boot_fabric_hz != 50000000:
            raise RuntimeError('Experimental A1 is separate common Debian read-only boot50')
        common.validate_a1_hardware_contract(json.loads(hardware_contract.read_text()))
        if common.A1_MONITOR not in (out/'module/valence_clockmon.c').read_text():
            raise RuntimeError('Experimental A1 requires matching frozen ABI2 read-only driver')
    source = ROOT / 'simulator/build/linux'
    if clean_revision(source) != record['linux_revision']:
        raise RuntimeError('Kernel source revision drift')
    root = output_path(args.rootfs_out)
    if Path(args.rootfs_record).name != args.rootfs_record or not args.rootfs_record.startswith('rootfs-build') or not args.rootfs_record.endswith('.json'):
        raise RuntimeError('Unexpected rootfs record name')
    root_record = json.loads((root / args.rootfs_record).read_text())
    if root_record.get('stage') != 'packed' or root_record.get('kernel_build') != str(out):
        raise RuntimeError('Rootfs must contain these exact kernel modules')
    if experimental_a1:
        tools_cap = root_record.get('performance_tools', {}).get('clockmon_snapshot_profiles', {})
        if tools_cap.get('a1-runtime') != dict(cpu_abi=2, retirement_lanes=2, scalar_request_lane=0) or tools_cap.get('fabric_abi') != 1:
            raise RuntimeError('Experimental A1 requires matching ABI2/two-lane monitor tool receipt')
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
    for name, digest in record['module_sources'].items():
        if sha(out / 'module' / name) != digest or sha(NET / name) != digest:
            raise RuntimeError('Module source changed after kernel prepare: ' + name)
    for name in record['modules']:
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
    profiles = ((common.EXPERIMENTAL_A1,) if experimental_a1 else common.CPUS) if common_mode else (None,)
    for cpu_profile in profiles:
        target = delivery / cpu_profile if cpu_profile else delivery
        if cpu_profile:
            target.mkdir(exist_ok=False)
        publish_profile(args, out, target, record, root_record, linux_image,
                        cpio, runtime, embedded, cpu_profile)
    if common_mode:
        summary = dict(common_platform=common.CONTRACT, shared_kernel_sha256=sha(linux_image),
                       shared_rootfs_sha256=sha(cpio), profiles={cpu: dict(
                           manifest=str(Path(cpu) / 'manifest.json'),
                           sha256=sha(delivery / cpu / 'manifest.json')) for cpu in profiles},
                       board_verified=False, bit_included=False)
        (delivery / 'common-manifest.json').write_text(json.dumps(summary, indent=2) + '\n')
        receipt = dict(delivery=str(delivery), manifest_sha256=sha(delivery / 'common-manifest.json'))
        with (out / 'delivery-receipt.json').open('x') as stream:
            stream.write(json.dumps(receipt, indent=2) + '\n')


def publish_profile(args, out, delivery, record, root_record, linux_image,
                    cpio, runtime, embedded, cpu_profile):
    kernel = out / 'linux'
    layout = MemoryLayout(record['memory_bytes'])
    payload_limit = layout.monitor - (0x80000 if layout.ram_bytes == 0x80000000 else 0)
    init_system = record.get('init_system', 'busybox')
    console_profile = record.get('console_profile', 'sbi')
    bootargs = record.get('bootargs', net.BOOTARGS)
    compression = record.get('initramfs_compression', 'gzip')
    dts, dtb = delivery / 'valence-vl100.dts', delivery / 'valence-vl100.dtb'
    boot_cpu_hz = getattr(args, 'i1_boot_cpu_hz', 50000000) if cpu_profile == 'i1' else 50000000
    boot_fabric_hz = getattr(args, 'i1_boot_fabric_hz', 50000000) if cpu_profile == 'i1' else 50000000
    dts.write_text(common.device_tree(net, cpu_profile, bootargs, console_profile, boot_cpu_hz, boot_fabric_hz) if cpu_profile else
        net.network_dts(layout.ram_bytes, platform_drivers=True, bootargs=bootargs, console_profile=console_profile))
    dtc = kernel / 'scripts/dtc/dtc'
    run([dtc, '-q', '-I', 'dts', '-O', 'dtb', '-o', dtb, dts])
    if cpu_profile:
        decoded = subprocess.check_output([dtc, '-q', '-I', 'dtb', '-O', 'dts', dtb], text=True)
        common.validate(decoded, cpu_profile, boot_cpu_hz, boot_fabric_hz)
    else:
        net.validate_dtb(dtc, dtb, bootargs=bootargs, console_profile=console_profile)
    if dtb.stat().st_size + 8192 > 0x10000:
        raise RuntimeError('DTB exceeds reserved slot')
    opensbi = opensbi_setup(False)
    handoff_fixup = None
    if cpu_profile and console_profile == 'sbi':
        patched = out / 'opensbi-sbi-console-source'
        handoff_fixup = sbi_console_handoff.prepare(opensbi, patched)
        opensbi = patched
    sbi_out = out / ('opensbi-' + cpu_profile if cpu_profile else 'opensbi')
    run(['make', '-j' + str(args.jobs), 'PLATFORM=generic', 'CROSS_COMPILE=riscv64-linux-gnu-',
         'PLATFORM_RISCV_ISA=rv64imac_zicsr_zifencei', 'PLATFORM_RISCV_ABI=lp64',
         'FW_TEXT_START=0x80200000', 'FW_DYNAMIC=n', 'FW_JUMP=n', 'FW_PAYLOAD=y',
         'FW_PAYLOAD_OFFSET=0x200000', 'FW_PAYLOAD_FDT_ADDR=0x80300000', 'FW_FDT_PADDING=8192',
         'FW_FDT_PATH=' + str(dtb), 'FW_PAYLOAD_PATH=' + str(linux_image), 'O=' + str(sbi_out)],
        cwd=opensbi, log=delivery / 'opensbi-build.log', timeout=600)
    firmware = sbi_out / 'platform/generic/firmware/fw_payload.bin'
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
    if boot_cpu_hz != 50000000:
        suffix += '_linuxcpu' + str(boot_cpu_hz // 1000000)
    if boot_fabric_hz != 50000000:
        suffix += '_fabric' + str(boot_fabric_hz // 1000000)
    stem = ('opensbi_common_' + cpu_profile + '_boot50_u460800' if cpu_profile else
            'opensbi_debian13_riscv64_vl100_cpu100_u460800')
    result = delivery / (stem + suffix + '.bin')
    shutil.copyfile(firmware, result)
    delivery_elf = result.with_suffix('.elf')
    shutil.copyfile(elf, delivery_elf)
    # Match the configured BootROM RRQ; the server intentionally checks basename.
    vld = delivery / 'valence.vld'
    profile = {0x20000000: 'ddr', 0x40000000: 'ddr1g', 0x80000000: 'ddr2g-menu'}[layout.ram_bytes]
    run([sys.executable, HERE.parent / 'netboot_host.py', 'pack', result, '--out', vld, '--memory', profile],
        log=delivery / 'netboot-pack.log')
    raw_image, stage2 = export_stage2_payload(linux_image, delivery)
    shutil.copyfile(kernel / '.config', delivery / 'linux.config')
    for tool in ('netboot_host.py', 'uart_load.py'):
        shutil.copyfile(HERE.parent / tool, delivery / tool)
    shutil.copyfile(NET / 'net_bench_peer.py', delivery / 'net_bench_peer.py')
    manifest = dict(**record)
    manifest.update(stage='firmware_ready_not_board_verified', rootfs=root_record,
        rootfs_embedded=True, stage2_payload=stage2,
        userland_abi=root_record.get('userland_abi', 'lp64d'),
        userland_isa=root_record.get('userland_isa', 'rv64gc'), kernel_prepare_config_sha256=record['config_sha256'],
        config_sha256=sha(kernel / '.config'),
        kernel_runtime_bytes=runtime, bootargs=bootargs, opensbi_revision=OPENSBI_LOCK['revision'], opensbi_console_handoff_fixup=handoff_fixup,
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
            HERE.parent / 'linux_uart/kernel_proc_contract.py', HERE / 'common_linux_profile.py',
            *[NET / name for name in record['module_sources']]]},
        files={p.name: dict(bytes=p.stat().st_size, sha256=sha(p)) for p in
            (result, delivery_elf, vld, raw_image, dtb, dts, delivery / 'linux.config', delivery / 'netboot_host.py',
             delivery / 'uart_load.py', delivery / 'net_bench_peer.py')})
    if cpu_profile:
        manifest.update(cpu_profile=cpu_profile, common_platform=common.CONTRACT,
                        linux_start_cpu_target_hz=boot_cpu_hz, linux_start_fabric_target_hz=boot_fabric_hz,
                        linux_start_fabric_parameters='0x08280a' if boot_fabric_hz == 125000000 else None,
                        linux_start_cpu_parameters='0x08280a' if boot_cpu_hz == 125000000 else None,
                        automatic_frequency_change=boot_cpu_hz != 50000000,
                        frequency_policy="exact boot CPU125 then fabric125; no runtime fabric writes" if boot_fabric_hz == 125000000 else ("exact CPU125 / fabric untouched" if boot_cpu_hz != 50000000 else "read-only boot50"),
                        shared_kernel_sha256=sha(linux_image), shared_rootfs_sha256=sha(cpio),
                        runtime_clock_monitor_present=cpu_profile in ('i1', common.EXPERIMENTAL_A1),
                        active_platform_modules=6 if cpu_profile in ('i1', common.EXPERIMENTAL_A1) else 5)
        if cpu_profile == common.EXPERIMENTAL_A1:
            contract_path = args.a1_runtime_hardware_contract
            contract = common.validate_a1_hardware_contract(json.loads(contract_path.read_text()))
            (delivery/'a1-runtime-hardware-contract.json').write_bytes(contract_path.read_bytes())
            manifest.update(experimental_hardware_required=True, compatible_with_old_a1=False,
                            hardware_contract=contract, hardware_contract_sha256=sha(contract_path),
                            cpu_telemetry_abi=2, fabric_telemetry_abi=1, cpu_retirement_lanes=2,
                            frequency_write_enabled=False, physical_timing_qualified=False)
    (delivery / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('VL100_DEBIAN_FIRMWARE_READY_NOT_BOARD_VERIFIED ' + str(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform', choices=('legacy', common.PROFILE), default=common.PROFILE,
                        help='common-boot50 builds one kernel/rootfs for explicit I1 and A1 DT packages')
    parser.add_argument('--stage', choices=('kernel', 'modules', 'image'), required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--rootfs-out', type=Path)
    parser.add_argument('--rootfs-record', default='rootfs-build.json')
    parser.add_argument('--i1-boot-cpu-hz', type=int, choices=(50000000,125000000), default=50000000,
                        help='explicit new I1 candidate only: driver-controlled CPU125 after Linux module load; A1 stays50')
    parser.add_argument('--i1-boot-fabric-hz', type=int, choices=(50000000,125000000), default=50000000,
                        help='explicit separate I1 candidate: one-shot boot fabric125 after CPU125; no runtime fabric sysfs')
    parser.add_argument('--experimental-a1-runtime', action='store_true', help='separate experimental A1 runtime-only profile, read-only boot50; never for old A1 bit')
    parser.add_argument('--a1-runtime-hardware-contract', type=Path, help='exact experimental hardware contract required with runtime flag')
    parser.add_argument('--delivery-out', type=Path, help='separate new release directory while reusing own kernel objects')
    parser.add_argument('--baseline', type=Path, help='optional exact baseline config/cache; common builds support fresh tinyconfig')
    parser.add_argument('--jobs', type=int, default=min(os.cpu_count() or 8, 16))
    parser.add_argument('--memory-bytes', type=lambda s: int(s, 0), default=0x80000000,
                        choices=(0x20000000, 0x40000000, 0x80000000))
    parser.add_argument('--resume-kernel', action='store_true', help='retry an incomplete software build; retain failed logs')
    parser.add_argument('--reuse-kernel', type=Path, help='seed a fresh independent output with a matching completed kernel cache')
    parser.add_argument('--kernel-optimization', choices=('size','performance'), default='size',
                        help='kernel stage compiler policy; performance is O2, not a board speed guarantee')
    parser.add_argument('--initramfs-compression', choices=('gzip', 'lz4'),
                        help='dinit defaults to LZ4; legacy profiles default to gzip')
    parser.add_argument('--console', choices=net.uart_console.PROFILES, default='sbi',
                        help='kernel stage: uart-irq selects ttyS0; sbi retains polling recovery')
    parser.add_argument('--init-system', choices=('dinit', 'systemd', 'busybox'), default='busybox',
                        help='small common image defaults to BusyBox; Debian init systems remain explicit')
    args = parser.parse_args()
    if args.stage != 'image' and (args.experimental_a1_runtime or args.a1_runtime_hardware_contract):
        parser.error('experimental hardware selection applies only at image/DT stage')
    if args.stage != 'image' and (args.i1_boot_cpu_hz != 50000000 or args.i1_boot_fabric_hz != 50000000):
        parser.error('boot frequency targets apply explicitly at the final image/DT stage only')
    if args.jobs < 1 or (args.stage == 'image' and args.rootfs_out is None):
        parser.error('positive --jobs required; --stage image requires --rootfs-out')
    {'kernel': prepare, 'modules': refresh_modules, 'image': image}[args.stage](args)
