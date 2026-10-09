#!/usr/bin/env python3
"""Independent software configuration/ownership tests; no hardware claims."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
FW = HERE.parent
ROOT = FW.parents[1]
sys.path[:0] = [str(FW / 'linux_net'), str(FW / 'debian_rootfs')]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


image = load('uart_debian_image', FW / 'debian_rootfs/build_image.py')
rootfs = load('uart_dinit_rootfs', FW / 'debian_rootfs/build_dinit_rootfs.py')
profile = image.net.uart_console
audit = load('uart_dinit_audit', FW / 'debian_rootfs/audit_dinit_delivery.py')


def config(console):
    # Independent required-feature fixture, including the unmodified BSP policy.
    features = ('64BIT MMU RISCV_SBI FPU NET INET PACKET NETDEVICES PHYLIB OF_MDIO '
        'REALTEK_PHY MODULES HZ_250 NO_HZ_IDLE IRQ_TIME_ACCOUNTING IRQ_DOMAIN OF_IRQ '
        'RISCV_ISA_FALLBACK PRINTK_TIME CMDLINE_FORCE PROC_FS SYSFS DEVTMPFS TTY SERIAL_8250 SERIAL_8250_CONSOLE '
        'SERIAL_OF_PLATFORM SERIAL_EARLYCON SERIAL_EARLYCON_RISCV_SBI').split()
    features += list(image.DEBIAN_CONFIG)
    lines = ['CONFIG_' + name + '=y' for name in features]
    lines += ['CONFIG_LOG_BUF_SHIFT=20', 'CONFIG_SERIAL_8250_NR_UARTS=1',
              'CONFIG_SERIAL_8250_RUNTIME_UARTS=1',
              'CONFIG_CMDLINE="' + image.profile_bootargs('dinit', console) + '"',
              '# CONFIG_HVC_RISCV_SBI is not set' if console == 'uart-irq' else 'CONFIG_HVC_RISCV_SBI=y']
    return '\n'.join(lines) + '\n'


class ProfileTests(unittest.TestCase):
    def test_sbi_default_unchanged(self):
        self.assertEqual(image.profile_bootargs('dinit'), image.DINIT_BOOTARGS)
        text = image.net.network_dts()
        self.assertNotIn('fifo-size', text)
        self.assertNotIn('<&valence_aia 3 4>', text)
        image.validate_kernel_config(config('sbi'), 'dinit')

    def test_native_configuration_and_mutations(self):
        text = config('uart-irq')
        image.validate_kernel_config(text, 'dinit', 'uart-irq')
        changes = [('CONFIG_PROC_FS=y', '# CONFIG_PROC_FS is not set'),
                   ('CONFIG_SYSFS=y', '# CONFIG_SYSFS is not set'),
                   ('CONFIG_DEVTMPFS=y', '# CONFIG_DEVTMPFS is not set'),
                   ('# CONFIG_HVC_RISCV_SBI is not set', 'CONFIG_HVC_RISCV_SBI=y'),
                   ('CONFIG_SERIAL_OF_PLATFORM=y', '# CONFIG_SERIAL_OF_PLATFORM is not set'),
                   ('console=ttyS0,460800n8', 'console=hvc0'),
                   ('earlycon=sbi', 'earlycon=sbi keep_bootcon'),
                   ('CONFIG_SERIAL_8250_NR_UARTS=1', 'CONFIG_SERIAL_8250_NR_UARTS=2')]
        for before, after in changes:
            with self.subTest(mutation=before), self.assertRaises(RuntimeError):
                image.validate_kernel_config(text.replace(before, after), 'dinit', 'uart-irq')

    def test_native_dt_and_recovery_mismatch(self):
        args = image.profile_bootargs('dinit', 'uart-irq')
        text = image.net.network_dts(0x80000000, True, args, 'uart-irq')
        self.assertIn('interrupts-extended = <&valence_aia 3 4>;', text)
        self.assertIn('fifo-size = <16>;', text)
        self.assertIn('current-speed = <460800>;', text)
        self.assertIn('interrupts-extended = <&valence_aia 6 4>;', text)
        self.assertNotIn('"riscv,imsics"', text)
        for bad in (text.replace('fifo-size = <16>;', ''), text.replace(args, image.DINIT_BOOTARGS)):
            with self.assertRaises(RuntimeError):
                image.net.validate_dts(bad, args, 'uart-irq')
        with self.assertRaises(RuntimeError):
            image.net.validate_dts(text, args, 'sbi')

    def test_compiled_dt_irq_phandle_and_bad_source(self):
        dtc = shutil.which('dtc')
        if not dtc:
            self.skipTest('dtc unavailable')
        args = image.profile_bootargs('dinit', 'uart-irq')
        text = image.net.network_dts(0x80000000, True, args, 'uart-irq')
        with tempfile.TemporaryDirectory() as directory:
            dts, dtb = Path(directory) / 'board.dts', Path(directory) / 'board.dtb'
            for source in (3, 6):
                dts.write_text(text.replace('<&valence_aia 3 4>', f'<&valence_aia {source} 4>'))
                subprocess.run([dtc, '-q', '-I', 'dts', '-O', 'dtb', '-o', dtb, dts], check=True)
                if source == 3:
                    image.net.validate_dtb(dtc, dtb, args, 'uart-irq')
                else:
                    with self.assertRaises(RuntimeError):
                        image.net.validate_dtb(dtc, dtb, args, 'uart-irq')

    def test_current_ddr_and_menu_reserved_regions(self):
        args = image.profile_bootargs('dinit', 'uart-irq')
        text = image.net.network_dts(0x80000000, True, args, 'uart-irq')
        self.assertIn('reg = <0x0 0x80200000 0x0 0x80000000>;', text)
        for before, after in (('reg = <0x0 0xfff78000 0x0 0x80000>;', 'reg = <0x0 0xfff79000 0x0 0x70000>;'),
                              ('diagnostics@fff78000', 'unreserved@fff78000'),
                              ('monitor@ffff8000', 'unreserved@ffff8000'),
                              ('reg = <0x0 0x80200000 0x0 0x80000000>;', 'reg = <0x0 0x80000000 0x0 0x80000000>;')):
            with self.subTest(mutation=before), self.assertRaises(RuntimeError):
                image.net.validate_dts(text.replace(before, after), args, 'uart-irq')
        with self.assertRaises(RuntimeError):
            image.net.validate_dts(text.replace('            no-map;', '', 1), args, 'uart-irq')
        block = ('        diagnostics@fff78000 {\n'
                 '            reg = <0x0 0xfff78000 0x0 0x80000>;\n'
                 '            no-map;\n        };\n')
        misplaced = text.replace(block, '').replace('    soc {', block + '    soc {')
        self.assertNotEqual(text, misplaced)
        with self.assertRaises(RuntimeError):
            image.net.validate_dts(misplaced, args, 'uart-irq')
        dtc = shutil.which('dtc')
        if not dtc:
            self.skipTest('dtc unavailable for compiled reservation check')
        with tempfile.TemporaryDirectory() as directory:
            dts, dtb = Path(directory) / 'board.dts', Path(directory) / 'board.dtb'
            dts.write_text(text)
            subprocess.run([dtc, '-q', '-I', 'dts', '-O', 'dtb', '-o', dtb, dts], check=True)
            image.net.validate_dtb(dtc, dtb, args, 'uart-irq')

    def test_rootfs_single_owner_and_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'etc/dinit.d').mkdir(parents=True)
            shutil.copyfile(rootfs.ASSETS / 'init', root / 'init')
            shutil.copyfile(rootfs.ASSETS / 'services/serial-console', root / 'etc/dinit.d/serial-console')
            old = (root / 'init').read_bytes()
            rootfs.configure_console(root, 'sbi')
            self.assertEqual((root / 'init').read_bytes(), old)
            rootfs.configure_console(root, 'uart-irq')
            text = (root / 'init').read_text()
            self.assertLess(text.index('mount -t devtmpfs'), text.index('. /usr/local/libexec/valence-uart'))
            self.assertLess(text.index('. /usr/local/libexec/valence-uart'), text.index('exec /usr/sbin/dinit'))
            self.assertIn(' ttyS0 vt100', (root / 'etc/dinit.d/serial-console').read_text())
            self.assertNotIn('hvc0', (root / 'etc/dinit.d/serial-console').read_text())

    def test_bootstrap_success_and_failures(self):
        original = (rootfs.ASSETS / 'uart-irq-init').read_text()
        for mode in ('ready', 'rv64-padded', 'unknown-port', 'irq-zero', 'wrong-mmio', 'aia-fault', 'modprobe-fail'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'status').write_text('ready=1 faulted=' + ('1' if mode == 'aia-fault' else '0'))
                serial = '0: uart:16550A mmio:0x10000000 irq:7 tx:0 rx:0\n'
                if mode == 'rv64-padded': serial = serial.replace('mmio:0x10000000', 'MMIO:0x0000000010000000')
                if mode == 'unknown-port': serial = serial.replace('16550A', 'unknown')
                if mode == 'irq-zero': serial = serial.replace('irq:7', 'irq:0')
                if mode == 'wrong-mmio': serial = serial.replace('10000000', '10000100')
                (root / 'serial').write_text(serial)
                (root / 'tty').touch()
                # Only replace external hardware endpoints in this host fixture.
                text = original.replace('/sys/bus/platform/devices/*/irqchip_status', str(root / 'status'))
                text = text.replace('/proc/tty/driver/serial_8250', str(root / 'serial'))
                text = text.replace('/dev/kmsg', str(root / 'kmsg')).replace('/dev/ttyS0', str(root / 'tty'))
                text = text.replace('/run/valence/', str(root) + '/')
                text = text.replace('sleep 3600', 'exit 77')
                text = text.replace('[ -c ', '[ -f ')
                text = text.replace('sleep 0.1', ': # bounded wait elided in host fixture')
                text = text.replace('modprobe valence_aia', 'false' if mode == 'modprobe-fail' else 'true')
                text = text.replace('stty -F ', 'true ')
                script = root / 'test.sh'
                script.write_text('set -eu\n' + text)
                result = subprocess.run(['/bin/sh', script], capture_output=True, timeout=3)
                self.assertEqual(result.returncode, 0)
                self.assertIn('ttyS0 descriptors opened', (root / 'uart-startup.log').read_text())
                self.assertIn('UART IRQ traffic unverified', (root / 'uart-startup.log').read_text())
                self.assertFalse((root / 'uart-recovery-required').exists())

    def test_packed_console_owner_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'etc/dinit.d').mkdir(parents=True)
            shutil.copyfile(rootfs.ASSETS / 'init', root / 'init')
            shutil.copyfile(rootfs.ASSETS / 'services/serial-console', root / 'etc/dinit.d/serial-console')
            rootfs.configure_console(root, 'uart-irq')
            manifest = {'console_profile': 'uart-irq', 'rootfs': {'console_profile': 'uart-irq'}}
            content = lambda name: (root / name).read_bytes()
            audit.require_console_contract(manifest, content, config('uart-irq').splitlines())
            with self.assertRaises(RuntimeError):
                audit.require_console_contract(manifest, content, config('sbi').splitlines())
            manifest['rootfs']['console_profile'] = 'sbi'
            with self.assertRaises(RuntimeError):
                audit.require_console_contract(manifest, content, config('uart-irq').splitlines())

    def test_packed_audit_rejects_regressions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'etc/dinit.d').mkdir(parents=True)
            shutil.copyfile(rootfs.ASSETS / 'init', root / 'init')
            shutil.copyfile(rootfs.ASSETS / 'services/serial-console', root / 'etc/dinit.d/serial-console')
            rootfs.configure_console(root, 'uart-irq')
            helper = root / 'usr/local/libexec/valence-uart-irq-init'
            original = helper.read_text()
            for before, after in (('uart_proc=/proc/tty/driver/serial_8250', 'uart_proc=/proc/tty/driver/serial'),
                                  ('command exec <', 'exec <'), ('\ntrue\n', '\nwhile :; do sleep 3600; done\n')):
                helper.write_text(original.replace(before, after))
                with self.subTest(mutation=before), self.assertRaises(RuntimeError):
                    audit.require_console_contract(
                        {'console_profile': 'uart-irq', 'rootfs': {'console_profile': 'uart-irq'}},
                        lambda name: (root / name).read_bytes(), config('uart-irq').splitlines())

    def test_stage2_raw_payload_bytes_are_not_wrapped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, delivery = root / 'kernel', root / 'delivery'
            source.write_bytes(b'not-a-VLD-wrapper\x00' + bytes(range(256)))
            delivery.mkdir()
            result, contract = image.export_stage2_payload(source, delivery)
            self.assertEqual(result.read_bytes(), source.read_bytes())
            self.assertEqual(result.name, 'Image')
            self.assertEqual(contract['runtime_dtb'], 'valence-vl100.dtb')
            self.assertEqual(contract['kernel_entry'], '0x80400000')
            self.assertEqual(contract['initramfs'], 'embedded')
            self.assertFalse(contract['board_verified'])

    def test_busy_irq_budget_does_not_disable_other_devices(self):
        text = (FW / 'linux_net/valence_aia.c').read_text()
        boundary = text.split('if (count == VA_CLAIM_BUDGET)', 1)[1].split('if (p->faulted)', 1)[0]
        self.assertIn('p->budget_yields++', boundary)
        self.assertNotIn('faulted = true', boundary)
        self.assertIn('!va_claim_valid(word)', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
