#!/usr/bin/env python3
"""Source-only exporter checks. Subprocesses are mocked; no emitter or hardware run.

Use --baseline-root to compare the omitted flag with the immutable published A
exporter. Without that root the historical comparison is explicitly skipped.
"""
import argparse
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
BASE = None
FLAG = '--posted-younger-load-seal-deferral'
FIELD = 'posted_younger_load_seal_deferral'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class PostedYoungerLoadSealExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix='posted-younger-load-config-')
        cls.exporter = module('posted_younger_load_export', HERE / 'export.py')
        cls.manifest = json.loads((HERE / 'near-term-a-profile.json').read_text())
        cls.options = cls.manifest['native_options'] + cls.manifest['physical_options']
        cls.old = module('posted_younger_load_original_export', BASE / 'fpga/next/export.py') if BASE else None
        if BASE and (BASE / 'fpga/next/export.py').read_bytes() == (HERE / 'export.py').read_bytes():
            raise ValueError('--baseline-root must contain the immutable pre-experiment exporter')

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def invoke(self, exporter, options):
        output = Path(self.scratch.name) / 'never-created'
        def git_only(command, **kwargs):
            self.assertEqual(command, ['git', 'rev-parse', 'HEAD'])
            return '0' * 40 + '\n'
        with mock.patch.object(exporter, 'sources', return_value={}), \
                mock.patch.object(exporter.subprocess, 'check_output', side_effect=git_only), \
                mock.patch.object(exporter.subprocess, 'run', side_effect=AssertionError('unexpected emitter/tool')), \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            exporter.main(['--output', str(output), *(x for x in options if x != '--selected')])
        self.assertFalse(output.exists())
        return json.loads(stdout.getvalue())

    def reject(self, options):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.invoke(self.exporter, options)

    def test_omitted_flag_retains_published_a_native_configuration_and_command(self):
        if self.old is None:
            self.skipTest('Historical A/B requires --baseline-root with immutable published A sources')
        before = self.invoke(self.old, self.options)
        after = self.invoke(self.exporter, self.options)
        self.assertEqual(after['command'], before['command'])
        self.assertEqual(after['configuration'], before['configuration'])
        self.assertEqual(after['native_mac_mode'], before['native_mac_mode'])
        self.assertNotIn(FIELD, after['configuration'])
        self.assertFalse(after[FIELD])

    def test_new_option_is_explicit_append_only_and_changes_one_native_field(self):
        before = self.invoke(self.exporter, self.options)
        after = self.invoke(self.exporter, self.options + [FLAG])
        self.assertEqual(len(before['command'][5:]), 68)
        self.assertEqual(after['command'], before['command'] + [FLAG])
        self.assertEqual(after['native_mac_mode'], before['native_mac_mode'])
        restored = copy.deepcopy(after['configuration'])
        self.assertIs(restored.pop(FIELD), True)
        suffix = FLAG[1:]
        self.assertEqual(restored['name'], before['configuration']['name'] + suffix)
        restored['name'] = restored['name'][:-len(suffix)]
        self.assertEqual(restored, before['configuration'])
        self.assertEqual(after['status'], 'PREFLIGHT_ONLY')
        self.assertFalse(after['physical_qualification'])

    def test_rejects_duplicate_valued_unknown_and_abbreviated_spelling(self):
        self.reject(self.options + [FLAG, FLAG])
        for value in ('', 'true', 'false', '0', '1'):
            self.reject(self.options + [FLAG + '=' + value])
        for invalid in (FLAG[:-1], FLAG + 's', '--posted_younger_load_seal_deferral'):
            self.reject(self.options + [invalid])

    def test_requires_posted_stores_and_rejects_frontier(self):
        self.reject([FLAG])
        self.reject(['--posted-store-merge', '--memory-proof-frontier', '--rob-entries=64',
            '--physical-regs=64', '--lsu-entries=4', '--virtual-ram-load-precheck',
            '--canonical-virtual-store-overlap', '--load-order-older-retire',
            '--data-translation-entries=16', FLAG])
        result = self.invoke(self.exporter, ['--posted-store-merge', FLAG])
        self.assertTrue(result['configuration'][FIELD])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--baseline-root', type=Path)
    args = parser.parse_args()
    BASE = args.baseline_root.resolve() if args.baseline_root else None
    unittest.main(argv=[__file__], verbosity=2)
