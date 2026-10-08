#!/usr/bin/env python3
"""Build GC/network firmware against clean local Linux, no RTL/Vivado changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
FIRMWARE = HERE.parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(FIRMWARE), str(ROOT / 'simulator/gsim')]
from build_linux import board_dts, clean_revision, image_header, validate_payload, LOAD, KERNEL, DTB, MONITOR
from run import run, opensbi_setup, OPENSBI_LOCK, coremark_setup, COREMARK_SOURCE
from build_userland import verify
import uart_console

OUTPUT_NAME = 'opensbi_linux_rv64gc_cpu100_u460800_gmac_fpu.bin'
ISA_EXTENSIONS = ('i', 'm', 'a', 'f', 'd', 'c', 'zicsr', 'zifencei')
# These describe driver selection policy, not the queues present in a bitstream
# or a successfully exercised Linux data path. Hardware discovery is runtime.
NETWORK_QUEUE_POLICY = {
    'selection': 'runtime DMA capability discovery; absent/malformed uses legacy',
    'rx_requested_slots_default': 4, 'tx_requested_slots_default': 4,
    'requested_slots_range': [1, 16], 'selected_slots_capped_by_hardware': True,
    'legacy_slots_each_direction': 1, 'dma_buffer_bytes_each': 2048,
    'runtime_selected_slots_verified': False,
}
BOOTARGS = ('earlycon=sbi console=hvc0 rdinit=/init loglevel=7 printk.time=1 '
            'initcall_debug initramfs_async=0')
ENABLED = ['PRINTK', 'TTY', 'SERIAL_8250', 'SERIAL_8250_CONSOLE', 'SERIAL_OF_PLATFORM',
    'SERIAL_EARLYCON', 'SERIAL_EARLYCON_RISCV_SBI', 'NONPORTABLE', 'HVC_RISCV_SBI',
    'BLK_DEV_INITRD', 'BINFMT_ELF', 'DEVTMPFS', 'DEVTMPFS_MOUNT', 'PROC_FS', 'SYSFS',
    'TMPFS', 'CMDLINE_FORCE', 'BINFMT_SCRIPT', 'UNIX98_PTYS', 'MULTIUSER', 'FUTEX',
    'POSIX_TIMERS', 'EPOLL', 'RD_GZIP', 'INITRAMFS_COMPRESSION_GZIP', 'FPU',
    'NET', 'INET', 'PACKET', 'UNIX', 'NETDEVICES', 'ETHERNET', 'PHYLIB', 'MDIO_DEVICE',
    'MDIO_BUS', 'OF_MDIO', 'REALTEK_PHY', 'MODULES', 'HZ_250', 'NO_HZ_IDLE', 'HIGH_RES_TIMERS',
    'IRQ_TIME_ACCOUNTING',
    'IKCONFIG', 'IKCONFIG_PROC', 'RISCV_ISA_FALLBACK', 'PRINTK_TIME']
DISABLED = ['EFI', 'SMP', 'VT', 'VT_CONSOLE', 'CONSOLE_TRANSLATIONS', 'DUMMY_CONSOLE',
    'INITRAMFS_COMPRESSION_NONE', 'MODULE_UNLOAD', 'MODULE_SIG', 'MODVERSIONS',
    'HZ_100', 'HZ_1000', 'HZ_300', 'HZ_PERIODIC', 'NO_HZ_FULL', 'IPV6',
    'RISCV_ISA_V', 'RISCV_ISA_ZICBOM']

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def network_dts(memory_bytes=0x20000000, platform_drivers=False, bootargs=BOOTARGS, console_profile="sbi"):
    base = board_dts('rv64gc', 100000000, 460800, memory_bytes)
    legacy_isa = 'riscv,isa = "rv64imafdc_zicsr_zifencei";'
    old_bootargs = 'bootargs = "earlycon=sbi console=hvc0 rdinit=/init loglevel=7";'
    if base.count(legacy_isa) != 1 or base.count(old_bootargs) != 1:
        raise RuntimeError('Unexpected CPU ISA or bootargs template')
    # Linux uses the extension list; retain the legacy string for OpenSBI.
    extension_list = ', '.join('"' + name + '"' for name in ISA_EXTENSIONS)
    base = base.replace(legacy_isa, legacy_isa + '\n'
        '            riscv,isa-base = "rv64i";\n'
        '            riscv,isa-extensions = ' + extension_list + ';')
    base = base.replace(old_bootargs, 'bootargs = "' + bootargs + '";')
    needle = '        uart0: serial@10000000 {'
    if base.count(needle) != 1:
        raise RuntimeError('Unexpected base device tree')
    node = '''        valence_aia: interrupt-controller@c000000 {
            compatible = "openion,valence-aia-csr-v1";
            reg = <0x0 0x0c000000 0x0 0x4000>, <0x0 0x0c004000 0x0 0x4000>;
            reg-names = "root", "leaf";
            interrupt-controller;
            #address-cells = <0>;
            #interrupt-cells = <2>;
            interrupts-extended = <&cpu0_intc 9>;
            /* Fixed single-hart CSR-only IMSIC; not riscv,imsics.
             * Source 31 is reserved for the boot-time internal MSI selftest. */
            status = "okay";
        };
        gmac0: ethernet@10040000 {
            compatible = "openion,valence-native-gmac-v1";
            reg = <0x0 0x10040000 0x0 0x1000>, <0x0 0x10002000 0x0 0x100>;
            reg-names = "mac", "dma";
            dma-coherent;
            openion,ram-base = /bits/ 64 <0x80200000>;
            openion,ram-bytes = /bits/ 64 <RAM_BYTES>;
            phy-mode = "rgmii-rxid";
            phy-handle = <&rtl8211f>;
            max-speed = <1000>;
            local-mac-address = [02 56 41 4c 00 01];
            status = "okay";
            interrupts-extended = <&valence_aia 6 4>;
            interrupt-names = "dma";
            mdio {
                #address-cells = <1>;
                #size-cells = <0>;
                rtl8211f: ethernet-phy@1 { reg = <1>; };
            };
        };
'''
    base = base.replace('/* No standard CPU-writable IMSIC aperture: do NOT describe AIA here.\n'
                        '         * Linux uses SBI DBCN/hvc polling. UART IRQ3 is not used in this image. */',
                        '/* CSR-only IRQ adapter; no standard CPU MSI aperture.\n'
                        '         * UART remains SBI DBCN/hvc polling; packet DMA uses source 6. */')
    text = base.replace(needle, node.replace('RAM_BYTES', hex(memory_bytes)) + needle).replace('aliases { serial0 = &uart0; };',
        'aliases { serial0 = &uart0; ethernet0 = &gmac0; };')
    if platform_drivers:
        extra = '''        cmu0: clock-controller@10080000 {
            compatible = "openion,valence-cmu-v1";
            reg = <0x0 0x10080000 0x0 0x1000>;
            #clock-cells = <1>;
            status = "okay";
        };
        dma0: dma-controller@10001000 {
            compatible = "openion,valence-memcpy-dma-v1";
            reg = <0x0 0x10001000 0x0 0x1000>;
            #dma-cells = <1>;
            dma-coherent;
            interrupts-extended = <&valence_aia 4 4>;
            openion,ram-base = /bits/ 64 <0x80200000>;
            openion,ram-bytes = /bits/ 64 <RAM_BYTES>;
            status = "okay";
        };
'''
        text = text.replace(needle, extra.replace('RAM_BYTES', hex(memory_bytes)) + needle)
        text = text.replace('            reg-names = "mac", "dma";',
            '            reg-names = "mac", "dma";\n'
            '            clocks = <&cmu0 5>, <&cmu0 6>;\n'
            '            clock-names = "tx", "rx";')
        # A software-only client node belongs at root, not under MMIO simple-bus.
        text = text.replace('    soc {', '''    dma-benchmark {
        compatible = "openion,valence-dma-bench-v1";
        dmas = <&dma0 0>;
        dma-names = "copy";
        status = "okay";
    };
    soc {''')
    text = uart_console.device_tree(text, console_profile)
    validate_dts(text, bootargs=bootargs, console_profile=console_profile)
    return text

def validate_dts(text, bootargs=BOOTARGS, console_profile="sbi"):
    """Fail closed on missing modern ISA discovery, not merely CONFIG_FPU=y."""
    uart_console.validate_dts(text, console_profile)
    def strings(name):
        matches = re.findall(r'(?m)^\s*' + re.escape(name) + r'\s*=\s*(.*?);', text)
        if len(matches) != 1:
            raise RuntimeError('Missing or ambiguous DT property: ' + name)
        # dtc may render a string list as one string containing escaped NULs.
        return [part for value in re.findall(r'"([^"\n]*)"', matches[0])
                for part in value.split(r'\0')]
    if strings('riscv,isa-base') != ['rv64i']:
        raise RuntimeError('Wrong DT base ISA')
    extensions = strings('riscv,isa-extensions')
    if len(extensions) != len(ISA_EXTENSIONS) or set(extensions) != set(ISA_EXTENSIONS):
        raise RuntimeError('DT must explicitly advertise exactly the qualified RV64GC extensions')
    if strings('riscv,isa') != ['rv64imafdc_zicsr_zifencei']:
        raise RuntimeError('Legacy ISA does not match the RV64GC profile')
    if strings('bootargs') != [bootargs]:
        raise RuntimeError('DT timestamp bootargs mismatch')
    if '"openion,valence-aia-csr-v1"' not in text or '"riscv,imsics"' in text:
        raise RuntimeError('Describe the qualified CSR-only adapter, not a standard MSI aperture')

def validate_dtb(dtc, path, bootargs=BOOTARGS, console_profile="sbi"):
    text = subprocess.check_output([dtc, '-q', '-I', 'dtb', '-O', 'dts', path], text=True)
    validate_dts(text, bootargs=bootargs, console_profile=console_profile)
    def node(pattern):
        found = re.search(pattern, text, re.S)
        if not found:
            raise RuntimeError('DT interrupt node missing: ' + pattern)
        return found.group(1)
    def cells(body, prop):
        found = re.search(re.escape(prop) + r'\s*=\s*<([^>]+)>;', body)
        if not found:
            raise RuntimeError('DT cells missing: ' + prop)
        return [int(word, 0) for word in found.group(1).split()]
    cpu = node(r'\binterrupt-controller\s*\{([^{}]*)\};')
    aia = node(r'\binterrupt-controller@c000000\s*\{([^{}]*)\};')
    mac = node(r'\bethernet@10040000\s*\{(.*?)\bmdio\s*\{')
    if cells(aia, 'reg') != [0, 0xc000000, 0, 0x4000, 0, 0xc004000, 0, 0x4000]:
        raise RuntimeError('APLIC root/leaf windows mismatch')
    if cells(aia, '#interrupt-cells') != [2] or cells(cpu, '#interrupt-cells') != [1]:
        raise RuntimeError('IRQ cell counts mismatch')
    if cells(aia, 'interrupts-extended') != cells(cpu, 'phandle') + [9]:
        raise RuntimeError('CSR adapter must attach to this hart SEIP')
    if cells(mac, 'interrupts-extended') != cells(aia, 'phandle') + [6, 4]:
        raise RuntimeError('Packet DMA must use source 6, level-high')
    if console_profile == 'uart-irq':
        uart = node(r'\bserial@10000000\s*\{([^{}]*)\};')
        if (cells(uart, 'interrupts-extended') != cells(aia, 'phandle') + [3, 4]
                or cells(uart, 'fifo-size') != [16]
                or cells(uart, 'reg') != [0, 0x10000000, 0, 8]
                or cells(uart, 'reg-io-width') != [1]
                or cells(uart, 'reg-shift') != [0]
                or cells(uart, 'clock-frequency') != [7372800]):
            raise RuntimeError('IRQ UART must use byte MMIO, 16-byte FIFO, source 3 level-high')

def validate_embedded_dtb(firmware, dtb):
    if not dtb.startswith(b'\xd0\x0d\xfe\xed') or firmware.count(dtb) != 1:
        raise RuntimeError('Exact validated DTB not embedded once in OpenSBI firmware')

def validate_config(text, bootargs=BOOTARGS, console_profile="sbi"):
    lines = set(text.splitlines())
    uart_console.validate_config(text, console_profile)
    for name in ('64BIT', 'MMU', 'RISCV_SBI', 'FPU', 'NET', 'INET',
                 'PACKET', 'NETDEVICES', 'PHYLIB', 'OF_MDIO', 'REALTEK_PHY', 'MODULES', 'HZ_250',
                 'NO_HZ_IDLE', 'IRQ_TIME_ACCOUNTING', 'IRQ_DOMAIN', 'OF_IRQ',
                 'RISCV_ISA_FALLBACK', 'PRINTK_TIME', 'CMDLINE_FORCE'):
        if f'CONFIG_{name}=y' not in lines:
            raise RuntimeError('Required config missing: ' + name)
    for name in ('SMP', 'MODULE_UNLOAD', 'HZ_PERIODIC', 'HZ_1000', 'IPV6'):
        if f'CONFIG_{name}=y' in lines:
            raise RuntimeError('Unsupported configuration in single-hart IRQ profile: ' + name)
    if 'CONFIG_CMDLINE="' + bootargs + '"' not in lines:
        raise RuntimeError('Effective kernel command line must enable timestamps')

def build_apps(output):
    cc = output / 'userland/riscv64-valence-gc-musl-gcc'
    if not cc.exists():
        raise RuntimeError('Run linux_net/build_userland.py first')
    apps = output / 'apps'
    apps.mkdir(exist_ok=True)
    port = HERE / 'coremark_port'
    coremark_setup(False)
    sources = [COREMARK_SOURCE / name for name in
               ('core_main.c', 'core_list_join.c', 'core_matrix.c', 'core_state.c', 'core_util.c')]
    run([cc, '-static', '-O2', '-I' + str(port), '-I' + str(COREMARK_SOURCE),
         port / 'core_portme.c', *sources, '-o', apps / 'coremark'], log=output / 'coremark-build.log')
    run([cc, '-static', '-O2', '-Wall', '-Wextra', '-ffp-contract=off',
         HERE / 'fpu_test.c', HERE / 'fp_context.S', '-o', apps / 'fpu-test'],
        log=output / 'fpu-test-build.log')
    run([cc, '-static', '-O2', '-Wall', '-Wextra', HERE / 'net_bench.c', '-o', apps / 'net-bench'],
        log=output / 'net-bench-build.log')
    for binary in (apps / 'coremark', apps / 'fpu-test', apps / 'net-bench'):
        verify(binary)
        run(['riscv64-unknown-elf-strip', '--strip-unneeded', binary])
    disassembly = subprocess.check_output(['riscv64-unknown-elf-objdump', '-d', apps / 'fpu-test'], text=True)
    for instruction in ('fadd.s', 'fsub.s', 'fmul.s', 'fdiv.s', 'fsqrt.s', 'fmadd.s',
                        'fadd.d', 'fsub.d', 'fmul.d', 'fdiv.d', 'fsqrt.d', 'fmadd.d', 'fld', 'fsd'):
        if instruction not in disassembly:
            raise RuntimeError('FPU test lost instruction: ' + instruction)
    (output / 'fpu-instruction-check.json').write_text(json.dumps({
        'status': 'PASS_STATIC_HARD_FLOAT_F_D_OPCODE_CHECK_NOT_BOARD_EXECUTION',
        'fpu_test_sha256': sha(apps / 'fpu-test'), 'isa': 'rv64gc', 'abi': 'lp64d'}, indent=2) + '\n')
    return apps

def rootfs_lines(output, apps):
    user = output / 'userland'
    dirs = {'/dev', '/dev/pts', '/proc', '/sys', '/tmp', '/run', '/root', '/etc', '/etc/network',
        '/bin', '/sbin', '/lib', '/lib/modules', '/var', '/var/run', '/usr', '/usr/bin',
        '/usr/sbin', '/usr/share', '/usr/share/udhcpc', '/usr/share/licenses',
        '/etc/network/if-pre-up.d', '/etc/network/if-up.d', '/etc/network/if-down.d',
        '/etc/network/if-post-down.d'}
    lines = [f'dir {name} {"1777" if name == "/tmp" else "755"} 0 0' for name in sorted(dirs)]
    lines += ['nod /dev/console 600 0 0 c 5 1', 'nod /dev/null 666 0 0 c 1 3']
    files = [('/bin/busybox', user / 'busybox/busybox', '755'),
        ('/bin/coremark', apps / 'coremark', '755'), ('/bin/fpu-test', apps / 'fpu-test', '755'),
        ('/bin/net-bench', apps / 'net-bench', '755'),
        ('/bin/net-status', HERE / 'net-status', '755'), ('/bin/boot-time', HERE / 'boot-time', '755'),
        ('/bin/net-test', HERE / 'net-test', '755'),
        ('/init', HERE / 'init', '755'), ('/etc/network/interfaces', HERE / 'interfaces', '644'),
        ('/usr/share/udhcpc/default.script', HERE / 'udhcpc.script', '755')]
    files.append(('/etc/os-release', HERE / 'os-release', '644'))
    for name in ('profile', 'passwd', 'group'):
        files.append(('/etc/' + name, FIRMWARE / 'linux_rootfs' / name, '644'))
    for name, source in (('busybox', 'busybox-1.37.0/LICENSE'), ('musl', 'musl-1.2.5/COPYRIGHT'),
                         ('coremark', 'coremark-src/LICENSE.md')):
        license_file = ROOT / 'simulator/build' / source
        if license_file.exists():
            files.append(('/usr/share/licenses/' + name, license_file, '644'))
    lines += [f'file {target} {source} {mode} 0 0' for target, source, mode in files]
    lines += [f'slink {name} /bin/busybox 777 0 0' for name in sorted(set(
        (user / 'busybox/busybox.links').read_text().splitlines()))]
    return lines

def build(args):
    source = args.source.resolve()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    revision = clean_revision(source)
    identity = {'linux_revision': revision, 'isa': 'rv64gc', 'abi': 'lp64d',
        'cpu_hz': 100000000, 'uart_baud': 460800, 'gmac_driver': 'native-v1-irq-napi',
        'irq_adapter': 'single-hart-csr-imsic-v1', 'kernel_tick_hz': 250, 'tickless_idle': True}
    marker = output / 'source.json'
    if marker.exists() and json.loads(marker.read_text()) != identity:
        raise RuntimeError('Output identity changed; use a fresh output directory')
    marker.write_text(json.dumps(identity, indent=2) + '\n')
    apps = build_apps(output)
    kernel_out = output / 'linux'
    kernel_out.mkdir(exist_ok=True)
    initramfs = output / 'initramfs.list'
    lines = rootfs_lines(output, apps)
    initramfs.write_text('\n'.join(lines) + '\n')
    make = ['make', f'O={kernel_out}', 'ARCH=riscv', 'CROSS_COMPILE=riscv64-linux-gnu-']
    config = kernel_out / '.config'
    if not config.exists():
        run([*make, 'tinyconfig'], cwd=source, log=output / 'config-base.log')
    flags = [v for name in ENABLED for v in ('--enable', name)]
    flags += [v for name in DISABLED for v in ('--disable', name)]
    run([source / 'scripts/config', '--file', config, *flags,
         '--set-val', 'SERIAL_8250_NR_UARTS', '1', '--set-val', 'SERIAL_8250_RUNTIME_UARTS', '1',
         '--set-str', 'INITRAMFS_SOURCE', str(initramfs), '--set-str', 'CMDLINE',
         BOOTARGS])
    run([*make, 'olddefconfig'], cwd=source, log=output / 'config-final.log')
    validate_config(config.read_text())
    run([*make, f'-j{args.jobs}', 'Image', 'modules'], cwd=source,
        log=output / 'kernel-build.log', timeout=2400)
    module_out = output / 'module'
    module_out.mkdir(exist_ok=True)
    for name in ('Makefile', 'valence_gmac.c', 'valence_aia.c', 'valence_irq_policy.h', 'valence_rx_queue.h', 'valence_tx_queue.h', 'valence_media_policy.h',
                 'valence_driver_names.h', 'valence_soc.c'):
        shutil.copyfile(HERE / name, module_out / name)
    run([*make, f'M={module_out}', 'W=1', f'-j{args.jobs}', 'modules'], cwd=source,
        log=output / 'gmac-build.log', timeout=300)
    module = module_out / 'valence_gmac.ko'
    irq_module = module_out / 'valence_aia.ko'
    lines.append(f'file /lib/modules/valence_gmac.ko {module} 644 0 0')
    lines.append(f'file /lib/modules/valence_aia.ko {irq_module} 644 0 0')
    initramfs.write_text('\n'.join(lines) + '\n')
    # Only regenerate initramfs + relink, not a second clean kernel build.
    run([*make, f'-j{args.jobs}', 'Image'], cwd=source, log=output / 'kernel-final.log', timeout=600)
    image = kernel_out / 'arch/riscv/boot/Image'
    runtime_size = image_header(image)
    dts, dtb = output / 'valence-gc-gmac.dts', output / 'valence-gc-gmac.dtb'
    dts.write_text(network_dts())
    run([kernel_out / 'scripts/dtc/dtc', '-I', 'dts', '-O', 'dtb', '-o', dtb, dts])
    validate_dtb(kernel_out / 'scripts/dtc/dtc', dtb)
    if dtb.stat().st_size + 8192 > 0x10000:
        raise RuntimeError('DTB exceeds reserved slot')
    opensbi = opensbi_setup(False)
    firmware_out = output / 'opensbi'
    run(['make', f'-j{args.jobs}', 'PLATFORM=generic', 'CROSS_COMPILE=riscv64-linux-gnu-',
        'PLATFORM_RISCV_ISA=rv64imac_zicsr_zifencei', 'PLATFORM_RISCV_ABI=lp64',
        'FW_TEXT_START=0x80200000', 'FW_DYNAMIC=n', 'FW_JUMP=n', 'FW_PAYLOAD=y',
        'FW_PAYLOAD_OFFSET=0x200000', 'FW_PAYLOAD_FDT_ADDR=0x80300000', 'FW_FDT_PADDING=8192',
        f'FW_FDT_PATH={dtb}', f'FW_PAYLOAD_PATH={image}', f'O={firmware_out}'],
        cwd=opensbi, log=output / 'opensbi-build.log', timeout=600)
    firmware = firmware_out / 'platform/generic/firmware/fw_payload.bin'
    validate_embedded_dtb(firmware.read_bytes(), dtb.read_bytes())
    elf = firmware.with_suffix('.elf')
    symbols = dict((name, int(address, 16)) for address, kind, name in (
        line.split() for line in subprocess.check_output(['riscv64-linux-gnu-nm', elf], text=True).splitlines()
        if len(line.split()) == 3))
    if symbols.get('_fw_start') != LOAD or symbols.get('payload_bin') != KERNEL or not LOAD < symbols.get('_fw_end', MONITOR) <= DTB:
        raise RuntimeError('OpenSBI firmware layout mismatch')
    padding = validate_payload(firmware.read_bytes(), image.read_bytes())
    result = output / OUTPUT_NAME
    shutil.copyfile(firmware, result)
    shutil.copyfile(config, output / 'linux.config')
    shutil.copyfile(FIRMWARE / 'uart_load.py', output / 'uart_load.py')
    manifest = {**identity, 'linux_version': subprocess.check_output([*make, '-s', 'kernelrelease'],
        cwd=source, text=True).strip(), 'opensbi_revision': OPENSBI_LOCK['revision'],
        'issue_width': 2, 'entry': hex(LOAD), 'kernel_entry': hex(KERNEL),
        'kernel_runtime_bytes': runtime_size, 'kernel_fpu': True,
        'dt_isa_base': 'rv64i', 'dt_isa_extensions': list(ISA_EXTENSIONS),
        'kernel_isa_fallback': True, 'kernel_log_timestamps': True,
        'init_stage_timestamps': True, 'bootargs': BOOTARGS,
        'exact_validated_dtb_embedded_in_OpenSBI': True,
        'fp_test_static_opcode_check': True, 'linux_fp_context_runtime_verified': False,
        'mac': 'native TL64 ABI v1; 1G/full duplex, DMA IRQ + NAPI weight 8/time budget 2ms',
        'network_queue_policy': NETWORK_QUEUE_POLICY, 'data_plane_periodic_polling': False,
        'irq_source': 6, 'irq_type': 'level-high', 'internal_msi_selftest_required_on_board': True,
        'linux_irq_runtime_verified': False, 'initcall_debug': True, 'initramfs_async': False,
        'ipv6_enabled': False,
        'phy': 'RTL8211F at MDIO 1; rgmii-rxid; require TXDLY=0 RXDLY=1 readback',
        'network_config': '/etc/network/interfaces, editable at runtime',
        'default_ipv4': '192.168.137.30/24', 'default_gateway': '192.168.137.1',
        'dma_coherency': 'CPU/DMA probed CoherentLineHome, no false claim at external DDR boundary',
        'module_unload_supported': False, 'board_gmac_verified': False,
        'gsim_run': False, 'vivado_run': False, 'payload_alignment_padding_bytes': padding,
        'userland': json.loads((output / 'userland/manifest.json').read_text()),
        'sources': {str(p.relative_to(ROOT)): sha(p) for p in HERE.rglob('*') if p.is_file()
                    and '__pycache__' not in p.parts},
        'files': {p.name: {'bytes': p.stat().st_size, 'sha256': sha(p)} for p in
            (result, dtb, dts, output / 'linux.config', module, irq_module,
             apps / 'fpu-test', apps / 'coremark', apps / 'net-bench', output / 'uart_load.py')}}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('NETWORK_GC_FIRMWARE_READY ' + str(result), flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'simulator/build/linux')
    parser.add_argument('--out', type=Path, default=ROOT / 'build/fpga/linux-net-rv64gc-20261006-r3')
    parser.add_argument('--jobs', type=int, default=min(os.cpu_count() or 8, 16))
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    build(args)
