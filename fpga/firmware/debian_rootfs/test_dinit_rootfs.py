#!/usr/bin/env python3
"""Short static and isolated native-Dinit tests, not Valence CPU simulation."""
import importlib.util
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
ASSETS = HERE / 'dinit'
ROOT = HERE.parents[2]
NATIVE = ROOT / 'build/fpga/dinit-tools-0.19.4-r2/native/src'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


image = load('dinit_image_test', HERE / 'build_image.py')


class DinitRootfsTests(unittest.TestCase):
    def test_hardware_dt_unchanged(self):
        old = image.net.network_dts(0x80000000, platform_drivers=True)
        new = image.net.network_dts(0x80000000, platform_drivers=True, bootargs=image.DINIT_BOOTARGS)
        self.assertEqual(new.replace(image.DINIT_BOOTARGS, image.net.BOOTARGS), old)
        image.net.validate_dts(new, bootargs=image.DINIT_BOOTARGS)
        self.assertNotIn('systemd.', image.DINIT_BOOTARGS)

    def test_actual_config_and_negative_profile(self):
        text = (ROOT / 'build/fpga/debian-dinit-kernel-20261007-r1/linux/.config').read_text()
        image.validate_kernel_config(text, 'dinit')
        for name in ('FPU', 'MMU', 'DMA_ENGINE'):
            with self.subTest(feature=name), self.assertRaises(RuntimeError):
                image.validate_kernel_config(text.replace('CONFIG_' + name + '=y', '# CONFIG_' + name + ' is not set'), 'dinit')
        with self.assertRaises(RuntimeError):
            image.validate_kernel_config(text, 'systemd')

    def test_pid1_and_single_getty(self):
        init = (ASSETS / 'init').read_text()
        self.assertIn('exec /usr/sbin/dinit ', init)
        self.assertNotIn('exec $bb init', init)
        self.assertNotIn('setsid ', init)
        services = list((ASSETS / 'services').iterdir())
        self.assertEqual(len(services), 6)
        self.assertEqual(sum('/sbin/agetty ' in p.read_text() for p in services), 1)
        serial = (ASSETS / 'services/serial-console').read_text()
        self.assertIn('restart-delay = 2', serial)
        self.assertIn('restart-limit-count = 5', serial)
        self.assertIn('hvc0 vt100', serial)
        self.assertNotIn('setsid ', serial)

    def test_ordering_and_irq_fail_closed(self):
        script = (ASSETS / 'platform-init').read_text()
        positions = [script.index('modprobe ' + name) for name in
            ('valence_soc', 'valence_aia', 'valence_cmu', 'valence_dma', 'valence_gmac')]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(script.index('if [ "$ready" != 1 ]'), positions[2])
        self.assertIn('exit 1', script)
        self.assertIn('depends-on: platform', (ASSETS / 'services/network').read_text())
        self.assertIn('waits-for: platform', (ASSETS / 'services/ready').read_text())

    def test_bounded_logs_and_no_extra_daemon_or_auto_bench(self):
        self.assertIn('size=16M', (ASSETS / 'init').read_text())
        for name in ('platform', 'network'):
            self.assertIn('log-buffer-size = 32768', (ASSETS / 'services' / name).read_text())
        for path in (ASSETS / 'services').iterdir():
            text = path.read_text()
            for bad in ('systemd', 'udevd', 'dbus-daemon', 'journald', 'iperf3', 'dma-bench', 'mem-bench'):
                self.assertNotIn(bad, text)
        for name in ('init', 'platform-init', 'ready', 'network-control'):
            self.assertFalse(re.search(r'^(mem-bench|dma-bench|iperf3) ', (ASSETS / name).read_text(), re.M))

    def test_scripts_parse(self):
        for name in ('init', 'platform-init', 'ready', 'network-control', 'boot-diagnose'):
            subprocess.run(['/bin/sh', '-n', ASSETS / name], check=True)

    def supervision_case(self, failure):
        # Run as an ordinary user/container instance; never PID 1 or system manager.
        # Replace all commands and remove console ownership in this headless fixture.
        with tempfile.TemporaryDirectory(prefix='valence-dinit-test-') as directory:
            work = Path(directory)
            services = work / 'services'
            services.mkdir()
            marker = work / 'serial-started'
            network = work / 'network-started'
            for path in (ASSETS / 'services').iterdir():
                text = re.sub(r'^options = .*\n', '', path.read_text(), flags=re.M)
                text = re.sub(r'^stop-command = .*\n', '', text, flags=re.M)
                if path.name == 'platform':
                    text = re.sub(r'^command = .*$', 'command = /bin/' + ('false' if failure else 'true'), text, flags=re.M)
                elif path.name == 'network':
                    text = re.sub(r'^command = .*$', 'command = /usr/bin/touch ' + str(network), text, flags=re.M)
                elif path.name == 'ready':
                    text = re.sub(r'^command = .*$', 'command = /bin/true', text, flags=re.M)
                elif path.name == 'serial-console':
                    text = re.sub(r'^command = .*$',
                        'command = /bin/sh -c "touch ' + str(marker) + '; exec sleep 30"', text, flags=re.M)
                (services / path.name).write_text(text)
            socket = work / 'control'
            process = subprocess.Popen([NATIVE / 'dinit', '--user', '--container',
                '--services-dir', services, '--socket-path', socket, '--service', 'boot'],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline and not marker.exists() and process.poll() is None:
                    time.sleep(0.05)
                self.assertTrue(marker.exists(), 'Serial service must start even if platform/network failed')
                if not failure:
                    while time.monotonic() < deadline and not network.exists():
                        time.sleep(0.05)
                self.assertEqual(network.exists(), not failure, 'Network must not start after IRQ/platform failure')
                result = subprocess.run([NATIVE / 'dinitctl', '--socket-path', socket, 'list'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('serial-console', result.stdout)
            finally:
                if process.poll() is None:
                    process.terminate()
                process.communicate(timeout=5)

    def test_native_positive_supervision(self):
        self.supervision_case(False)

    def test_native_driver_failure_keeps_login_without_network(self):
        self.supervision_case(True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
