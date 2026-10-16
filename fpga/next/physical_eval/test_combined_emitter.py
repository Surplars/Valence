"""Synthetic launcher/toolchain tests; never invokes a compiler or emits RTL."""
from pathlib import Path
import tempfile
import unittest
from combined_contract import info
from emit_combined import bind_mill_distribution, normalized_version, safe_environment, verify_tool_bytes


class MockEmitterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mock-emitter-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.launcher = self.root/'mill'
        self.dist = self.root/'mill-dist'
        self.launcher.write_text('#!/usr/bin/env bash\nexec bash "$(dirname -- "$0")/mill-dist" "$@"\n')
        self.dist.write_bytes(b'MOCK MILL DISTRIBUTION')
        self.chain = dict(mill=dict(path=str(self.launcher), **info(self.launcher)),
                          millDistribution=bind_mill_distribution(self.launcher, self.dist))
        for name in ('firtool', 'java'):
            path = self.root/name; path.write_bytes(b'MOCK TOOL '+name.encode())
            self.chain[name] = dict(path=str(path), **info(path))

    def test_unchanged_distribution_and_launcher(self):
        verify_tool_bytes(self.chain)

    def test_unchanged_launcher_changed_distribution_rejected(self):
        launcher_before = info(self.launcher)
        self.dist.write_bytes(b'CHANGED MOCK MILL DISTRIBUTION')
        self.assertEqual(info(self.launcher), launcher_before)
        with self.assertRaisesRegex(ValueError, 'millDistribution'):
            verify_tool_bytes(self.chain)

    def test_wrong_adjacent_distribution_rejected(self):
        wrong = self.root/'other-dist'; wrong.write_bytes(b'MOCK')
        with self.assertRaisesRegex(ValueError, 'binding'):
            bind_mill_distribution(self.launcher, wrong)

    def test_unknown_launcher_rejected(self):
        self.launcher.write_text('#!/bin/sh\nexec other-compiler "$@"\n')
        with self.assertRaisesRegex(ValueError, 'binding'):
            bind_mill_distribution(self.launcher, self.dist)

    def test_standalone_distribution(self):
        self.assertEqual(bind_mill_distribution(self.dist, self.dist)['sha256'], info(self.dist)['sha256'])

    def test_jvm_option_echo_does_not_leak_or_change_version(self):
        text = 'Mill Build Tool version 1.1.7\nPicked up JAVA_TOOL_OPTIONS: -Dhttp.proxyPort=12345 -Dpassword=SECRET\n'
        self.assertEqual(normalized_version(text), 'Mill Build Tool version 1.1.7')
        env = safe_environment(dict(JAVA_HOME='/mock/jdk', CHISEL_FIRTOOL_PATH='/mock/firtool',
            JAVA_TOOL_OPTIONS='-Xmx4g -XX:ActiveProcessorCount=2 -Dhttp.proxyPort=12345 -Dpassword=SECRET',
            HTTPS_PROXY='http://user:SECRET@example.invalid:12345', COURSIER_REPOSITORIES='SECRET'))
        self.assertNotIn('SECRET', str(env)); self.assertNotIn('12345', str(env))
        self.assertEqual(env['JAVA_TOOL_OPTIONS'][:2], ['-Xmx4g', '-XX:ActiveProcessorCount=2'])


if __name__ == '__main__':
    unittest.main()
