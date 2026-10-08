#!/usr/bin/env python3
"""Pure host/static profile tests; no simulated or physical Valence execution."""
import importlib.util
import os
from pathlib import Path
import struct
import unittest

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rootfs = load('valence_systemd_rootfs_test', HERE / 'build_systemd_rootfs.py')
image = load('valence_systemd_image_test', HERE / 'build_image.py')


def cpio_entry(name, content=b''):
    # Independent newc encoder for safe-name/parser negatives.
    raw = name.encode() + b'\0'
    values = [1, 0o100644, 0, 0, 1, 0, len(content), 0, 0, 0, 0, len(raw), 0]
    prefix = b'070701' + b''.join(f'{v:08x}'.encode() for v in values) + raw
    prefix += b'\0' * (-len(prefix) % 4)
    return prefix + content + b'\0' * (-len(content) % 4)


class SystemdProfileTests(unittest.TestCase):
    def test_safe_newc(self):
        archive = cpio_entry('.', b'') + cpio_entry('etc/os-release', b'Debian') + cpio_entry('TRAILER!!!')
        self.assertEqual(rootfs.archive_names(archive), ['.', 'etc/os-release'])

    def test_traversal_rejected(self):
        for name in ('/etc/evil', '../escape', 'a/../../escape'):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                rootfs.archive_names(cpio_entry(name) + cpio_entry('TRAILER!!!'))

    def test_bad_archive_rejected(self):
        for data in (b'', cpio_entry('etc/file'), cpio_entry('etc/file', b'abc')[:-2]):
            with self.subTest(size=len(data)), self.assertRaises(RuntimeError):
                rootfs.archive_names(data)

    def test_profiles_have_identical_hardware_dt(self):
        old = image.net.network_dts(0x80000000, platform_drivers=True)
        new = image.net.network_dts(0x80000000, platform_drivers=True, bootargs=image.SYSTEMD_BOOTARGS)
        self.assertEqual(new.replace(image.SYSTEMD_BOOTARGS, image.net.BOOTARGS), old)
        image.net.validate_dts(new, bootargs=image.SYSTEMD_BOOTARGS)
        with self.assertRaises(RuntimeError):
            image.net.validate_dts(new)

    def test_actual_systemd_config_and_negative_controls(self):
        path = Path(os.environ.get('VALENCE_SYSTEMD_KERNEL_CONFIG', str(image.ROOT / 'build/fpga/debian-systemd-kernel-20261007-r1/linux/.config')))
        text = path.read_text()
        image.validate_kernel_config(text, 'systemd')
        for name in ('CGROUPS', 'FHANDLE', 'SECCOMP_FILTER'):
            with self.subTest(feature=name), self.assertRaises(RuntimeError):
                image.validate_kernel_config(text.replace('CONFIG_' + name + '=y', '# CONFIG_' + name + ' is not set'), 'systemd')
        with self.assertRaises(RuntimeError):
            image.validate_kernel_config(text.replace('loglevel=8', 'loglevel=7'), 'systemd')

    def test_pid1_is_not_busybox_or_nested_setsid(self):
        init = (HERE / 'systemd_init').read_text()
        self.assertIn('exec /usr/lib/systemd/systemd', init)
        self.assertNotIn('setsid ', init)
        self.assertNotIn('exec $bb init', init)
        login = (HERE / 'serial-autologin.conf').read_text()
        self.assertIn('/sbin/agetty --autologin root', login)
        self.assertNotIn('setsid ', login)
        self.assertIn('KillMode=control-group', login)
        self.assertIn('RestartSec=2', login)

    def test_driver_load_order_and_fail_closed_irq(self):
        script = (HERE / 'valence-platform-init').read_text()
        positions = [script.index('modprobe ' + name) for name in
                     ('valence_soc', 'valence_aia', 'valence_cmu', 'valence_dma', 'valence_gmac')]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(script.index('if [ "$ready" != 1 ]'), positions[2])
        self.assertIn('exit 1', script)
        unit = (HERE / 'networking-valence.conf').read_text()
        self.assertIn('Requires=valence-platform.service', unit)

    def test_ram_only_bounded_logs_and_no_automatic_bench(self):
        self.assertIn('Storage=volatile', (HERE / 'journald-valence.conf').read_text())
        self.assertIn('RuntimeMaxUse=16M', (HERE / 'journald-valence.conf').read_text())
        for name in ('valence-platform-init', 'systemd_init', 'valence-ready'):
            lines = (HERE / name).read_text().splitlines()
            self.assertFalse(any(line.startswith(('mem-bench ', 'dma-bench ', 'iperf3 ')) for line in lines))


if __name__ == '__main__':
    unittest.main(verbosity=2)
