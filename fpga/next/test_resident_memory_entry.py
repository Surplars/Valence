#!/usr/bin/env python3
"""Pure-Python source/entry fixture checks; no actual constructors or emitters.

Fixtures below are expected data, never actual hardware evidence. External
processes are blocked. These tests require the final resident source seal.
"""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIELD = 'residentMemoryPayloadReuse'
FLAG = '--resident-memory-payload-reuse'


def load(name):
    spec = importlib.util.spec_from_file_location('resident_test_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResidentMemoryEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = load('resident_memory_source_bridge')
        cls.exporter = load('export')
        cls.contract = cls.bridge.checked_sources()
        cls.reference = json.loads((ROOT / cls.contract['reference']['profile_file']).read_text())
        cls.a = json.loads((HERE / 'near-term-a-before-mac-platform.json').read_text())
        cls.entry = json.loads((HERE / 'resident-memory-profile.json').read_text())

    def setUp(self):
        self.stack = contextlib.ExitStack()
        for method in ('run', 'check_output'):
            self.stack.enter_context(mock.patch.object(subprocess, method, side_effect=AssertionError('unexpected process')))

    def tearDown(self):
        self.stack.close()

    def fixture(self, resident=False, reference=None):
        document = copy.deepcopy(self.reference if reference is None else reference)
        for kind in ('core', 'profile'):
            values = document[kind]
            for name in self.contract['current_' + kind + '_names']:
                if name not in values:
                    values[name] = False
            values[FIELD] = resident
            document[kind] = {name: values[name] for name in self.contract['current_' + kind + '_names']}
        return document

    def project(self, document, reference='young', **names):
        with mock.patch.object(self.bridge, 'checked_sources', return_value=self.contract):
            return self.bridge.project_document(document,
                names.get('core', self.contract['current_core_names']),
                names.get('profile', self.contract['current_profile_names']), reference=reference)

    def test_compact_contract_preserves_full_maps_and_rejects_bad_deltas(self):
        compact = json.loads((HERE / 'resident-memory-source-compat.json').read_text())
        held = self.bridge.frozen_held_contract()
        expanded = self.bridge.expand_source_contract(compact, held)
        self.assertEqual(expanded, self.contract)
        self.assertLess((HERE / 'resident-memory-source-compat.json').stat().st_size, 120000)
        self.assertEqual(set(expanded['current_source_sha256']),
                         set(expanded['base_source_sha256']) | set(expanded['changed_sources']))
        for key in ('base_source_sha256', 'current_source_sha256', 'immutable_manifest_sha256'):
            bad = copy.deepcopy(compact)
            bad[key] = {}
            with self.assertRaisesRegex(RuntimeError, 'cannot override'):
                self.bridge.expand_source_contract(bad, held)
        name = next(iter(compact['changed_sources']))
        for field, value in (('old_sha256', '0' * 64), ('new_sha256', None),
                             ('new_sha256', 'not-a-hash'), ('reviewed_delta', ''),
                             ('reviewed_delta', False)):
            bad = copy.deepcopy(compact)
            bad['changed_sources'][name][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                self.bridge.expand_source_contract(bad, held)
        bad = copy.deepcopy(compact)
        bad['base_source_closure_sha256'] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'base digest'):
            self.bridge.expand_source_contract(bad, held)

    def test_live_source_and_all_public_loaders_preserve_exact_option_domains(self):
        self.bridge.checked_sources()
        self.assertEqual(len(load('board_timing64').load_profile()), 64)
        a = load('board_near_term_a').load_profile()
        raw = load('board_near_term_a_raw_handoff').load_profile()
        held = load('board_held_alu').load_profile()
        resident = load('board_resident_memory').load_profile()
        self.assertEqual(len(a['native_options']), 68)
        self.assertEqual(raw['native_options'], a['native_options'] + ['--tri-speed-raw-clock-handoff'])
        self.assertEqual(held['native_options'], a['native_options'] + ['--held-alu-issue-forwarding'])
        self.assertEqual(resident['reference_native_options'], a['native_options'] + ['--posted-younger-load-seal-deferral'])
        self.assertEqual(resident['native_options'], resident['reference_native_options'] + [FLAG])
        for old in (a, raw, held):
            self.assertNotIn(FLAG, old['native_options'])
        self.assertIs(resident['dynamic_qualification'], False)
        self.assertIs(resident['physical_qualification'], False)

    def test_measured_young_projection_preserves_true_younger_and_all_old_values(self):
        off = self.fixture()
        self.assertEqual(self.bridge.canonical(self.project(off)), self.bridge.canonical(self.reference))
        for kind in ('core', 'profile'):
            self.assertIs(self.project(off)[kind]['postedYoungerLoadSealDeferral'], True)
        self.assertEqual((len(self.project(off)['core']), len(self.project(off)['profile'])), (173, 89))
        self.assertEqual(self.bridge.canonical(self.project(self.fixture(reference=self.a), reference='a')),
                         self.bridge.canonical(self.a))

    def test_exact64_raw_and_held_false_resident_views_preserve_complete_old_values(self):
        exact64 = json.loads((HERE / 'near-term-a-original-profile.json').read_text())
        self.assertEqual(self.bridge.canonical(self.project(self.fixture(reference=exact64), reference='exact64')),
                         self.bridge.canonical(exact64))
        raw = self.fixture(reference=self.a)
        raw['profile']['triSpeedRawClockHandoff'] = True
        old_raw = copy.deepcopy(self.a)
        old_raw['profile']['triSpeedRawClockHandoff'] = True
        self.assertEqual(self.bridge.canonical(self.project(raw, reference='raw')), self.bridge.canonical(old_raw))
        held = self.fixture(reference=self.a)
        for kind in ('core', 'profile'):
            held[kind]['heldAluIssueForwarding'] = True
        with mock.patch.object(self.bridge, 'checked_sources', return_value=self.contract):
            old_held = self.bridge.project_document(held, self.contract['current_core_names'],
                self.contract['current_profile_names'], reference='held', held_alu_forwarding=True)
        self.assertEqual((len(old_held['core']), len(old_held['profile'])), (174, 91))
        for kind in ('core', 'profile'):
            expected = dict(held[kind])
            del expected[FIELD]
            self.assertEqual(self.bridge.canonical(old_held[kind]), self.bridge.canonical(expected))

    def test_all_removed_fields_require_literal_false(self):
        for kind in ('core', 'profile'):
            additions = [name for name in self.contract['current_' + kind + '_names'] if name not in self.reference[kind]]
            for name in additions:
                for invalid in (True, 0, 1, 'false', None, [], {}):
                    with self.subTest(kind=kind, field=name, value=invalid):
                        document = self.fixture()
                        document[kind][name] = invalid
                        with self.assertRaisesRegex(RuntimeError, 'named Boolean false'):
                            self.project(document)

    def test_full_names_order_count_and_same_arity_substitutions_rejected(self):
        for kind in ('core', 'profile'):
            for mode in ('missing', 'extra', 'reorder', 'same-arity-substitution', 'move-resident', 'duplicate'):
                names = list(self.contract['current_' + kind + '_names'])
                if mode == 'missing':
                    names.pop()
                elif mode == 'extra':
                    names.append('unknownField')
                elif mode == 'reorder':
                    names[0], names[1] = names[1], names[0]
                elif mode == 'same-arity-substitution':
                    names[-2] = 'unknownHeldField'
                elif mode == 'move-resident':
                    names[-2], names[-1] = names[-1], names[-2]
                else:
                    names[-1] = names[-2]
                with self.subTest(kind=kind, mode=mode), self.assertRaises(RuntimeError):
                    self.project(self.fixture(), **{kind: names})
            for remove in (True, False):
                document = self.fixture()
                if remove:
                    del document[kind][FIELD]
                else:
                    document[kind]['unknownField'] = False
                with self.assertRaises(RuntimeError):
                    self.project(document)

    def test_complete_original_scalar_type_and_nested_changes_rejected(self):
        for kind, field, changed in (('core', 'tagBits', 32), ('core', 'postedYoungerLoadSealDeferral', 1),
                ('profile', 'postedYoungerLoadSealDeferral', False), ('derived', 'cpuHz', 1),
                ('cache', 'readMshrs', 3), ('floatingPointResources', 'committedStateMemory', 1)):
            document = self.fixture()
            document[kind][field] = changed
            with self.subTest(kind=kind, field=field), self.assertRaisesRegex(RuntimeError, 'original complete'):
                self.project(document)

    def test_only_complete_resident_pair_delta_can_precede_projection(self):
        off, on = self.fixture(), self.fixture(True)
        with mock.patch.object(self.bridge, 'checked_sources', return_value=self.contract):
            self.bridge.validate_resident_pair(off, on, self.contract['current_core_names'], self.contract['current_profile_names'])
            for kind, field, changed in (('profile', FIELD, 1), ('core', 'heldAluIssueForwarding', True),
                                        ('ddr', 'maxOutstanding', 99)):
                bad = copy.deepcopy(on)
                bad[kind][field] = changed
                with self.assertRaises(RuntimeError):
                    self.bridge.validate_resident_pair(off, bad, self.contract['current_core_names'], self.contract['current_profile_names'])

    def test_each_guard_predicate_and_type_is_required_on_resolved_core(self):
        core = self.fixture(True)['core']
        self.exporter.check_resident_memory_topology(True, core)
        positive = ('registeredMemoryAddress', 'parallelMemoryPreparation', 'parallelMemoryPayload',
                    'compactMemoryOperandSelect', 'parallelMemoryAddressSum', 'lvtPhysicalRegisterFile',
                    'ownerLocalOperandReady', 'registeredIssueExecute')
        negative = ('moveAlias', 'loadCompletionBypass', 'mulWordPreviewBypass', 'memoryProofFrontier',
                    'fastBufferedStoreRetire', 'fastHeadLoadRetire')
        sizes = ('robEntries', 'physicalRegs', 'tagBits', 'renameWidth', 'completionWidth', 'commitWidth', 'memoryEntries')
        for field in positive + negative + sizes:
            for changed in ((False, 1) if field in positive else (True, 0) if field in negative else (0, True)):
                bad = dict(core, **{field: changed})
                with self.subTest(field=field, changed=changed), self.assertRaises(ValueError):
                    self.exporter.check_resident_memory_topology(True, bad)
        self.exporter.check_resident_memory_topology(False, {})
        with self.assertRaises(ValueError):
            self.exporter.check_resident_memory_topology(1, core)

    def preflight(self, options, output_path=None):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(subprocess, 'check_output', return_value='1' * 40 + '\n'), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.exporter.main(['--output', str(output_path if output_path is not None else Path(directory) / 'unused'), *options])
            return json.loads(output.getvalue())

    def test_exact_cli_native_forwarding_and_default_false(self):
        options = [x for x in self.entry['reference_native_options'] if x != '--selected']
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / 'unused'
            off = self.preflight(options, output_path)
            on = self.preflight(options + [FLAG], output_path)
        self.assertNotIn(FLAG, off['command'])
        self.assertEqual(on['command'].count(FLAG), 1)
        self.assertEqual(on['command'], off['command'] + [FLAG])
        self.assertIs(off['resident_memory_payload_reuse'], False)
        self.assertIs(on['resident_memory_payload_reuse'], True)
        self.assertNotIn('resident_memory_payload_reuse', off['configuration'])
        self.assertIs(on['configuration']['resident_memory_payload_reuse'], True)
        self.assertIn('resident-memory-payload-reuse', on['profile'])
        for invalid in ([FLAG, FLAG], [FLAG + '=true'], [FLAG + '=false'], ['--resident-memory-payload-reus']):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.preflight(options + invalid)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.preflight([FLAG])

    def test_actual_readback_requires_typed_complete_core_backend_ledger_and_names(self):
        for enabled in (False, True):
            resolved = self.fixture(enabled)
            actual = {'schema': 'actual-resident-memory-integration-v1', 'scope': 'actual-constructor-only',
                      FIELD: enabled, 'residentMemoryStartAllowed': enabled,
                      'residentSelectorCount': int(enabled), 'ordinarySelectorCount': int(not enabled),
                      'residentSelectorClasses': ['soc.core.ooo.ResidentMemoryPreparationSelector'] if enabled else [],
                      'core': copy.deepcopy(resolved['core']), 'backend': copy.deepcopy(resolved['core']),
                      'ledger': copy.deepcopy(resolved['core']), 'coreNames': self.contract['current_core_names'],
                      'profileNames': self.contract['current_profile_names'], 'coreFields': 175, 'profileFields': 92,
                      'executionStages': 2, 'memoryEntries': 4, 'dynamicQualification': False, 'physicalQualification': False}
            self.exporter.check_resident_memory_actual(enabled, resolved, actual)
            mutations = [(FIELD, int(enabled)), ('residentMemoryStartAllowed', int(enabled)),
                         ('coreNames', list(reversed(actual['coreNames']))), ('coreFields', True),
                         ('executionStages', True), ('memoryEntries', 2), ('dynamicQualification', 0),
                         ('residentSelectorCount', enabled), ('ordinarySelectorCount', enabled),
                         ('residentSelectorClasses', ['unknown.Selector'])]
            for field, value in mutations:
                bad = copy.deepcopy(actual)
                bad[field] = value
                with self.subTest(field=field, enabled=enabled), self.assertRaises(RuntimeError):
                    self.exporter.check_resident_memory_actual(enabled, resolved, bad)
            # Equal-but-wrong JSON types on every leaf must still fail the declared schema.
            bad_resolved = copy.deepcopy(resolved)
            bad_resolved['core']['registeredMemoryAddress'] = 1
            bad_actual = copy.deepcopy(actual)
            for leaf in ('core', 'backend', 'ledger'):
                bad_actual[leaf]['registeredMemoryAddress'] = 1
            with self.assertRaises(RuntimeError):
                self.exporter.check_resident_memory_actual(enabled, bad_resolved, bad_actual)
            for leaf in ('core', 'backend', 'ledger'):
                bad = copy.deepcopy(actual)
                bad[leaf][FIELD] = int(enabled)
                with self.assertRaises(RuntimeError):
                    self.exporter.check_resident_memory_actual(enabled, resolved, bad)

    def test_unknown_missing_or_changed_source_leaf_rejected(self):
        names = sorted(self.contract['current_source_sha256'])
        for changed in (names[:-1], sorted(names + ['unknown-source.txt'])):
            with mock.patch.object(self.bridge, 'source_paths', return_value=changed), self.assertRaises(RuntimeError):
                self.bridge.checked_sources()
        original = Path.read_bytes
        for relative in ('src/main/scala/core/ooo/OooParams.scala', 'src/main/scala/core/ooo/IntegerCore.scala',
                         'fpga/next/held-alu-source-compat.json', 'fpga/next/held-alu-profile.json'):
            target = ROOT / relative
            def read(path):
                data = original(path)
                return data + b'\nsource mutation\n' if path == target else data
            with mock.patch.object(Path, 'read_bytes', read), self.assertRaises(RuntimeError):
                self.bridge.checked_sources()


if __name__ == '__main__':
    unittest.main(verbosity=2)
