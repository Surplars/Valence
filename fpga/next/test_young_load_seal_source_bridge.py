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
        cls.held = module('tested_young_held_bridge', HERE / 'held_alu_source_bridge.py')
        cls.mac = module('tested_young_mac_bridge', HERE / 'mac_platform_source_bridge.py')
        # Literal source-only expected fixtures, never actual constructor evidence.
        cls.contract = json.loads((HERE / 'held-alu-source-compat.json').read_text())
        cls.original_a = json.loads((HERE / 'near-term-a-before-mac-platform.json').read_text())
        cls.manifests = {name: (HERE / name).read_bytes() for name in cls.bridge.MANIFEST_SHA256}
        cls.manifests['near-term-a-raw-handoff-profile.json'] = (HERE / 'near-term-a-raw-handoff-profile.json').read_bytes()

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
        self.assertIs(receipt['heldAluIssueForwarding'], False)
        self.assertIs(receipt['qualificationInherited'], False)
        self.assertIs(receipt['fullCpuQualification'], False)
        self.assertIs(receipt['physicalQualification'], False)

    def test_direct_mac_and_young_source_bridges_compose_through_exact_frozen_base(self):
        current = self.bridge.checked_young_base(ROOT)
        mac = self.mac.checked_sources()
        self.assertEqual(set(mac), set(self.bridge.MAC_PLATFORM_REPLACEMENTS))
        for name, row in mac.items():
            self.assertEqual(row['new_sha256'], current['current_source_sha256'][name])
        path = HERE / 'near-term-a-raw-handoff-profile.json'
        profile = json.loads(path.read_text())
        self.bridge.validate_mac_raw_contract(ROOT, path, profile)
        name = 'src/main/scala/core/ooo/FpgaNextConfig.scala'
        self.assertEqual(self.bridge.mac_raw_source_digest(name, profile['production_leaf_sha256'][name]),
                         current['current_source_sha256'][name])
        with mock.patch.object(self.bridge, 'PRODUCTION_TREE_SHA256', '0' * 64):
            with self.assertRaisesRegex(RuntimeError, 'frozen complete Young production'):
                self.bridge.checked_young_base(ROOT)

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
        profile = json.loads(self.manifests['near-term-a-profile.json'])
        profile['physical_qualification'] = 0
        with self.assertRaisesRegex(RuntimeError, 'original historical manifest'):
            self.validate_a(profile=profile)
        path = HERE / 'near-term-a-raw-handoff-profile.json'
        profile = json.loads(path.read_text())
        profile['physical_qualification'] = 0
        with self.assertRaisesRegex(RuntimeError, 'original MAC raw entry manifest values'):
            self.bridge.validate_mac_raw_contract(ROOT, path, profile)
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

    def young_fixture(self, young=False, raw=False):
        value = copy.deepcopy(self.original_a)
        value['core']['postedYoungerLoadSealDeferral'] = young
        value['core']['heldAluIssueForwarding'] = False
        value['profile']['triSpeedRawClockHandoff'] = raw
        value['profile']['postedYoungerLoadSealDeferral'] = young
        value['profile']['heldAluIssueForwarding'] = False
        return value

    def project_young_fixture(self, document, core_names=None, profile_names=None, **switches):
        # Isolate value-admission controls from full source identity. The live
        # closure and original manifests are independently exercised above.
        with mock.patch.object(self.bridge, 'checked_young_base', return_value=self.contract):
            return self.bridge.historical_young_document(ROOT, document,
                self.contract['current_core_names'] if core_names is None else core_names,
                self.contract['current_profile_names'] if profile_names is None else profile_names, **switches)

    def test_old_young_projection_preserves_all_values_order_and_explicit_switches(self):
        for young, raw in ((False, False), (True, False), (False, True)):
            with self.subTest(young=young, raw=raw):
                document = self.young_fixture(young, raw)
                before = copy.deepcopy(document)
                projected = self.project_young_fixture(document,
                    younger_load_seal_deferral=young, raw_clock_handoff=raw)
                self.assertEqual(document, before)
                for kind, tail in (('core', ['postedYoungerLoadSealDeferral']),
                        ('profile', ['triSpeedRawClockHandoff', 'postedYoungerLoadSealDeferral'])):
                    self.assertEqual(list(projected[kind]), self.contract['historical_a_' + kind + '_names'] + tail)
                    del before[kind]['heldAluIssueForwarding']
                self.assertEqual(projected, before)
                self.assertEqual((len(projected['core']), len(projected['profile'])), (173, 90))

    def test_young_projection_requires_typed_false_in_both_products(self):
        for kind in ('core', 'profile'):
            for invalid in (True, 0, 1, 'false', None, [], {}):
                with self.subTest(kind=kind, invalid=invalid):
                    document = self.young_fixture()
                    document[kind]['heldAluIssueForwarding'] = invalid
                    with self.assertRaisesRegex(RuntimeError, 'named Boolean held ALU false'):
                        self.project_young_fixture(document)

    def test_young_projection_rejects_unknown_missing_reordered_or_duplicate_names(self):
        for kind in ('core', 'profile'):
            for mutation in ('missing', 'extra', 'reordered', 'duplicate', 'held-misplaced'):
                with self.subTest(kind=kind, mutation=mutation):
                    names = list(self.contract['current_' + kind + '_names'])
                    if mutation == 'missing':
                        names.pop()
                    elif mutation == 'extra':
                        names.append('unknownField')
                    elif mutation == 'reordered':
                        names[0], names[1] = names[1], names[0]
                    elif mutation == 'duplicate':
                        names[-1] = names[-2]
                    else:
                        names[-1], names[-2] = names[-2], names[-1]
                    with self.assertRaisesRegex(RuntimeError, 'product names/order changed'):
                        self.project_young_fixture(self.young_fixture(), **{kind + '_names': names})
            for mutation in ('missing', 'extra'):
                document = self.young_fixture()
                if mutation == 'missing':
                    del document[kind]['heldAluIssueForwarding']
                else:
                    document[kind]['unknownField'] = False
                with self.assertRaisesRegex(RuntimeError, 'missing or extra constructed Young field'):
                    self.project_young_fixture(document)
        document = self.young_fixture()
        document['unknownDocument'] = {}
        with self.assertRaisesRegex(RuntimeError, 'complete Young document keys'):
            self.project_young_fixture(document)

    def test_young_projection_rejects_every_original_scalar_or_nested_value_drift(self):
        for kind, field, value in (('core', 'tagBits', 32),
                ('core', 'postedYoungerLoadSealDeferral', 0),
                ('profile', 'triSpeedRawClockHandoff', 0),
                ('profile', 'postedYoungerLoadSealDeferral', True),
                ('derived', 'cpuHz', 99999999), ('cache', 'readMshrs', 3),
                ('floatingPointResources', 'committedStateMemory', 1)):
            with self.subTest(kind=kind, field=field):
                document = self.young_fixture()
                document[kind][field] = value
                with self.assertRaisesRegex(RuntimeError, 'original Young complete scalar/nested values changed'):
                    self.project_young_fixture(document)
        for switches in ({'younger_load_seal_deferral': 0}, {'raw_clock_handoff': 1}):
            with self.assertRaisesRegex(RuntimeError, 'reference switches must be exact Booleans'):
                self.project_young_fixture(self.young_fixture(), **switches)

    def test_old_a_projection_still_requires_all_named_additions_false(self):
        for young, raw in ((True, False), (False, True)):
            with mock.patch.object(self.held, 'checked_sources', return_value=self.contract):
                with self.assertRaisesRegex(RuntimeError, 'exact named Boolean false'):
                    self.held.project_document(self.young_fixture(young, raw),
                        self.contract['current_core_names'], self.contract['current_profile_names'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
