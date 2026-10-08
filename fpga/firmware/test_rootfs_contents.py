#!/usr/bin/env python3
"""Source-only rootfs staging tests; no downloads, target tools or Linux build."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import build_linux
import build_rootfs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE / 'linux_net'))
spec = importlib.util.spec_from_file_location('network_rootfs_contents', HERE / 'linux_net/build_image.py')
network = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network)


class RootfsContentsTests(unittest.TestCase):
    def test_build_busybox_without_retired_sources_or_cmake(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'userland'
            sources = root / 'simulator/build'
            for name in ('musl-1.2.5', 'busybox-1.37.0'):
                (sources / name).mkdir(parents=True)
            commands = []

            def run(argv, **kwargs):
                command = [str(arg) for arg in argv]
                commands.append(command)
                if command == ['make', 'install']:
                    (output / 'sysroot/lib').mkdir(parents=True)
                    (output / 'sysroot/include').mkdir()
                if '-o' in command:
                    Path(command[command.index('-o') + 1]).write_bytes(b'libc smoke fixture')
                if command[-1] == 'busybox.links':
                    (output / 'busybox-linux/busybox').write_bytes(b'busybox fixture')
                    (output / 'busybox-linux/busybox.links').write_text('/bin/sh\n/bin/uname\n')

            def specs(argv, **kwargs):
                self.assertEqual(str(argv[0]), 'sh')
                self.assertTrue(str(argv[1]).endswith('musl-gcc.specs.sh'))
                return '*startfile:\nScrt1.o crtbeginS.o crtendS.o\n*esp_link:\nunused\n'

            with mock.patch.object(build_rootfs, 'ROOT', root), \
                    mock.patch.object(build_rootfs, 'run', side_effect=run), \
                    mock.patch.object(build_rootfs, 'verify_elf') as verify, \
                    mock.patch.object(build_rootfs.subprocess, 'check_output', side_effect=specs):
                build_rootfs.build(output, jobs=2)
            record = json.loads((output / 'manifest.json').read_text())
            self.assertEqual(set(record['archives']), {'musl-1.2.5.tar.gz', 'busybox-1.37.0.tar.bz2'})
            self.assertEqual(set(record['binaries']), {'busybox'})
            self.assertNotIn('host_cmake', record)
            self.assertEqual(verify.call_count, 2)
            self.assertFalse(any('fastfetch' in str(cmd) or 'cmake' in str(cmd) for cmd in commands))
            self.assertFalse(any(cmd[0] in ('curl', 'wget', 'tar') for cmd in commands))

    def busybox_fixture(self, userland, legacy_manifest=False):
        binary = userland / 'busybox-linux/busybox'
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b'busybox fixture')
        binary.with_name('busybox.links').write_text('/bin/sh\n/bin/uname\n/bin/sh\n')
        binaries = {'busybox': {'bytes': binary.stat().st_size, 'sha256': build_linux.digest(binary)}}
        if legacy_manifest:
            binaries['fastfetch'] = {'bytes': 123, 'sha256': 'obsolete and intentionally absent'}
        (userland / 'manifest.json').write_text(json.dumps({'binaries': binaries}))
        return binary

    def test_busybox_image_stages_new_and_legacy_manifests_without_fastfetch(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy), tempfile.TemporaryDirectory() as directory:
                userland = Path(directory)
                binary = self.busybox_fixture(userland, legacy)
                lines, binaries = build_linux.busybox_rootfs_lines(userland, userland / 'coremark')
                self.assertEqual(set(binaries), {'busybox'})
                self.assertEqual(lines.count('slink /bin/sh /bin/busybox 777 0 0'), 1)
                for target in ('/init', '/bin/busybox', '/bin/coremark', '/usr/share/licenses/musl'):
                    self.assertTrue(any(line.startswith('file ' + target + ' ') for line in lines), target)
                self.assertNotIn('fastfetch', '\n'.join(lines))
                binary.write_bytes(b'changed binary')
                with self.assertRaisesRegex(RuntimeError, 'provenance mismatch'):
                    build_linux.busybox_rootfs_lines(userland, userland / 'coremark')

    def test_network_image_has_no_old_userland_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'image'
            links = output / 'userland/busybox/busybox.links'
            links.parent.mkdir(parents=True)
            links.write_text('/bin/sh\n/bin/uname\n')
            with mock.patch.object(network, 'ROOT', root):
                lines = network.rootfs_lines(output, output / 'apps')
            for target in ('/bin/coremark', '/bin/fpu-test', '/bin/net-bench', '/bin/net-test', '/init'):
                self.assertTrue(any(line.startswith('file ' + target + ' ') for line in lines), target)
            self.assertNotIn('fastfetch', '\n'.join(lines))
            self.assertFalse((root / 'build/fpga/linux-userland').exists())

    def test_init_and_shell_probe_need_no_retired_command(self):
        init = HERE / 'linux_rootfs/init'
        subprocess.run(['/bin/sh', '-n', init], check=True)
        self.assertNotIn('fastfetch', init.read_text())
        self.assertIn('VALENCE_LINUX_INIT_OK', init.read_text())
        self.assertIn('setsid cttyhack /bin/sh -l', init.read_text())
        harness = (ROOT / 'simulator/gsim/harness/board_linux.cpp').read_text()
        self.assertNotIn('fastfetch', harness.lower())
        match = re.search(r'const std::string command = ROOTFS_BUSYBOX \?\s*("(?:\\.|[^"\\])*")', harness)
        self.assertIsNotNone(match)
        command = json.loads(match[1]).removesuffix('\r')
        self.assertNotIn('VALENCE_SHELL_OK', command)  # Echo alone cannot pass.
        result = subprocess.check_output(['/bin/sh', '-c', command], text=True)
        self.assertIn('VALENCE_SHELL_OK\n', result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
