#!/usr/bin/env python3
"""Read-only checks of both real historical loaders and the exact source bridge.

Mutations are supplied through mocked reads or bridge constants, never written to
production files or original manifests. Subprocess execution is prohibited.
"""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class HistoricalSourceBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = module('tested_seal_source_bridge', HERE / 'young_load_seal_source_bridge.py')
        cls.a = module('tested_seal_a_entry', HERE / 'board_near_term_a.py')
        cls.r3 = module('tested_seal_r3_entry', HERE / 'board_timing64.py')
        cls.manifests = {name: (HERE / name).read_bytes() for name in cls.bridge.MANIFEST_SHA256}

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(mock.patch.object(subprocess, 'run', side_effect=AssertionError('unexpected process')))
        self.stack.enter_context(mock.patch.object(subprocess, 'check_output', side_effect=AssertionError('unexpected process')))

    def tearDown(self):
        self.stack.close()
        for name, original in self.manifests.items():
            self.assertEqual((HERE / name).read_bytes(), original)

    def validate_a(self, options=None, profile=None):
        path = HERE / 'near-term-a-profile.json'
        profile = json.loads(path.read_text()) if profile is None else profile
        return self.bridge.validate_legacy_sources(ROOT, path, profile,
            profile['native_options'] if options is None else options)

    @contextlib.contextmanager
    def mutated_read(self, relative):
        original = Path.read_bytes
        target = ROOT / relative
        def read(path):
            data = original(path)
            return data + b'\nmutation\n' if path == target else data
        with mock.patch.object(Path, 'read_bytes', read):
            yield

    def test_actual_loaders_preserve_original_exact64_and_a68_views(self):
        r3 = self.r3.load_profile()
        a = self.a.load_profile()
        self.assertEqual(len(r3), 64)
        self.assertEqual(a, json.loads(self.manifests['near-term-a-profile.json']))
        self.assertEqual(a['rollback_options'], r3)
        self.assertEqual(len(a['native_options']), 68)
        self.assertNotIn(self.bridge.FLAG, a['native_options'])
        receipt = self.validate_a()
        self.assertIs(receipt['postedYoungerLoadSealDeferral'], False)
        self.assertIs(receipt['qualificationInherited'], False)
        self.assertIs(receipt['fullCpuQualification'], False)
        self.assertIs(receipt['physicalQualification'], False)

    def test_old_digest_must_match_the_original_manifest_exactly(self):
        replacements = copy.deepcopy(self.bridge.REPLACEMENTS)
        name = next(iter(replacements))
        replacements[name] = ('0' * 64, replacements[name][1])
        with mock.patch.object(self.bridge, 'REPLACEMENTS', replacements):
            with self.assertRaisesRegex(RuntimeError, 'old digest differs'):
                self.validate_a()

    def test_new_digest_and_exact_replacement_set_are_enforced(self):
        replacements = copy.deepcopy(self.bridge.REPLACEMENTS)
        name = next(iter(replacements))
        replacements[name] = (replacements[name][0], '0' * 64)
        with mock.patch.object(self.bridge, 'REPLACEMENTS', replacements):
            with self.assertRaisesRegex(RuntimeError, 'production leaf differs|bridge composition differs'):
                self.validate_a()
        for changed in (dict(list(self.bridge.REPLACEMENTS.items())[1:]),
                {**self.bridge.REPLACEMENTS, 'src/main/scala/core/ooo/Unknown.scala': ('1' * 64, '2' * 64)}):
            with mock.patch.object(self.bridge, 'REPLACEMENTS', changed), self.assertRaises(RuntimeError):
                self.validate_a()

    def test_wrong_original_manifest_or_profile_cannot_authorize_replacements(self):
        profile = json.loads(self.manifests['near-term-a-profile.json'])
        profile['production_leaf_sha256']['src/main/scala/core/ooo/OooParams.scala'] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'original historical manifest'):
            self.validate_a(profile=profile)
        for name in self.manifests:
            with self.mutated_read('fpga/next/' + name), self.assertRaises(RuntimeError):
                self.a.load_profile()

    def test_both_actual_loaders_reject_mutated_replacement_unchanged_and_unlisted_leaves(self):
        for relative in ('src/main/scala/core/ooo/OooParams.scala',
                'src/main/scala/core/ooo/IntegerCore.scala',
                'src/main/scala/core/ooo/PostedStoreMerge.scala',
                'src/main/scala/core/ooo/PostedYoungerLoadSeal.scala'):
            self.assertTrue((ROOT / relative).is_file())
            for entry in (self.r3, self.a):
                with self.subTest(leaf=relative, entry=entry.__name__), self.mutated_read(relative):
                    with self.assertRaises(RuntimeError):
                        entry.load_profile()

    def test_new_option_and_option_reordering_are_rejected_by_the_historical_bridge(self):
        options = json.loads(self.manifests['near-term-a-profile.json'])['native_options']
        for option in (self.bridge.FLAG, self.bridge.FLAG + '=false', self.bridge.FLAG + '=true'):
            with self.assertRaisesRegex(RuntimeError, 'requires younger-load seal deferral false'):
                self.validate_a(options=options + [option])
            for entry in (self.r3, self.a):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    entry.main(['--output', 'never-created', option])
        with self.assertRaisesRegex(RuntimeError, 'ordered OFF options differ'):
            self.validate_a(options=list(reversed(options)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
