#!/usr/bin/env python3
"""Source-only option/topology checks in the current complete checkout.

Optional --baseline-root PATH enables historical A/B against a pre-overlay tree.
Without that reference only the historical comparison is explicitly skipped.
All subprocess execution is intercepted. No RTL/model/tool invocation is allowed.
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


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class Timing64ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_root = BASE if BASE is not None else HERE.parents[1]
        if BASE is not None and (BASE / 'fpga/next/export.py').read_bytes() == (HERE / 'export.py').read_bytes():
            raise ValueError('--baseline-root must contain the immutable pre-overlay exporter; refusing self-comparison')
        cls.scratch = tempfile.TemporaryDirectory(prefix='timing64-source-only-')
        cls.root = Path(cls.scratch.name) / 'source'
        cls.root.mkdir()
        # Assemble an overlay view without writing the immutable source tree.
        for source in cls.source_root.iterdir():
            if source.name != 'fpga':
                (cls.root / source.name).symlink_to(source, target_is_directory=source.is_dir())
        (cls.root / 'fpga').mkdir()
        for source in (cls.source_root / 'fpga').iterdir():
            if source.name != 'next':
                (cls.root / 'fpga' / source.name).symlink_to(source, target_is_directory=source.is_dir())
        target = cls.root / 'fpga/next'
        target.mkdir()
        replacements = {'export.py', 'board_timing64.py', 'timing-batch-locality64-profile.json'}
        for source in (cls.source_root / 'fpga/next').iterdir():
            if source.name not in replacements:
                (target / source.name).symlink_to(source, target_is_directory=source.is_dir())
        for name in replacements:
            (target / name).write_bytes((HERE / name).read_bytes())
        cls.old = module('timing64_original_export', BASE / 'fpga/next/export.py') if BASE is not None else None
        cls.new = module('timing64_overlay_export', target / 'export.py')
        cls.entry = module('timing64_overlay_entry', target / 'board_timing64.py')
        cls.profile = json.loads((target / 'timing-batch-locality64-profile.json').read_text())
        cls.options52 = json.loads((cls.source_root / 'fpga/next/timing-batch-owner-row-profile.json').read_text())['native_options']
        cls.options59 = cls.profile['retained59_options']
        cls.options64 = cls.entry.load_profile()

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def invoke(self, exporter, options):
        output = Path(self.scratch.name) / 'never-created'
        def git_only(command, **kwargs):
            self.assertEqual(command, ['git', 'rev-parse', 'HEAD'])
            return '0' * 40 + '\n'
        with mock.patch.object(exporter.subprocess, 'check_output', side_effect=git_only), \
                mock.patch.object(exporter.subprocess, 'run', side_effect=AssertionError('unexpected emitter/tool')), \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            exporter.main(['--output', str(output), *(x for x in options if x != '--selected')])
        self.assertFalse(output.exists())
        return json.loads(stdout.getvalue())

    def reject(self, options):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.invoke(self.new, options)

    def test_old52_and_old59_commands_and_configuration_are_unchanged(self):
        if self.old is None:
            self.skipTest('Historical A/B requires --baseline-root with the immutable pre-overlay candidate tree')
        for options in (self.options52, self.options59):
            with self.subTest(count=len(options)):
                before = self.invoke(self.old, options)
                after = self.invoke(self.new, options)
                self.assertEqual(after['command'], before['command'])
                self.assertEqual(after['configuration'], before['configuration'])
                self.assertEqual(after['native_mac_mode'], before['native_mac_mode'])
                for field in self.new.LOCALITY_FLAGS:
                    self.assertNotIn(field, after['configuration'])

    def test_native_audit_helper_source_binding(self):
        after = self.new.sources()
        before = self.old.sources() if self.old is not None else None
        for name in ('MemoryPreparationLocalityActualAudit', 'ZeroCycleCleanupActualAudit'):
            path = 'src/test/scala/ooo/' + name + '.scala'
            if before is not None:
                self.assertNotIn(path, before)
            self.assertIn(path, after)
            self.assertEqual(after[path], self.new.sha(self.source_root / path))

    def test_new64_consumes_exactly_five_flags_and_rolls_back_exactly(self):
        before = self.invoke(self.new, self.options59)
        after = self.invoke(self.new, self.options64)
        self.assertEqual(after['command'][:-5], before['command'])
        self.assertEqual(after['command'][-5:], list(self.entry.FLAGS))
        self.assertEqual(len(after['command'][5:]), 64)
        self.assertEqual(set(after['command'][5:]), set(self.options64))
        restored = copy.deepcopy(after['configuration'])
        for field, flag in zip(self.new.LOCALITY_FLAGS, self.entry.FLAGS):
            self.assertIs(restored.pop(field), True)
            restored['name'] = restored['name'].replace(flag[1:], '')
        self.assertEqual(restored, before['configuration'])

    def test_new_flags_reject_duplicate_valued_unknown_and_abbreviation(self):
        for flag in self.entry.FLAGS:
            self.reject(self.options64 + [flag])
            for value in ('', 'true', 'false', '0', '1'):
                self.reject([x for x in self.options64 if x != flag] + [flag + '=' + value])
            self.reject([x for x in self.options64 if x != flag] + [flag[:-1]])
        self.reject(self.options64 + ['--unrecognized-locality'])

    def test_variable_cli_topology_constraints(self):
        self.reject(['--retirement-slot-identity'])
        self.reject(['--retirement-slot-identity', '--retirement-intent', '--rob-entries=32'])
        self.reject(['--retirement-slot-identity', '--retirement-intent', '--rob-entries=64'])
        self.reject(['--direct-rank0-memory-source-ids', '--memory-proof-frontier'])
        self.invoke(self.new, ['--retirement-slot-identity', '--retirement-intent', '--rob-entries=16'])
        for flag in self.entry.FLAGS:
            if flag != '--retirement-slot-identity':
                self.invoke(self.new, [flag])

    def test_all_scala_leaf_requirement_terms_are_checked(self):
        core = json.loads((self.source_root / 'fpga/next/retirement-slot-actual59-core.json').read_text())
        # This is a saved actual core record, not the checker's constants.
        if 'core' in core:
            core = core['core']
        core['retirementIntent'] = True
        enabled = dict.fromkeys(self.new.LOCALITY_FLAGS, True)
        self.new.check_locality_topology(enabled, core, coherent_line_cache=True, read_mshrs=2)
        terms = {
            'fetch_ready_data_clear': {'registeredTranslationHeads': False},
            'memory_preparation_head_mask': {'registeredIssueHeadMask': False, 'registeredMemoryAddress': False,
                                            'parallelMemoryPreparation': False},
            'direct_rank0_memory_source_ids': {'registeredMemoryAddress': False, 'parallelMemoryPreparation': False,
                'parallelMemoryPayload': False, 'compactMemoryOperandSelect': False, 'memoryProofFrontier': True},
            'retirement_slot_identity': {'retirementIntent': False, 'registeredRobRetirement': False,
                'completionWidth': 4, 'commitWidth': 4, 'robEntries': 32, 'tagBits': 32},
        }
        for flag, mutations in terms.items():
            for key, value in mutations.items():
                with self.subTest(flag=flag, key=key), self.assertRaises(ValueError):
                    self.new.check_locality_topology({x: x == flag for x in enabled},
                        {**core, key: value}, coherent_line_cache=True, read_mshrs=2)
        for coherent, mshrs in ((False, 2), (True, 1)):
            with self.assertRaises(ValueError):
                self.new.check_locality_topology(enabled, core, coherent_line_cache=coherent, read_mshrs=mshrs)

    def test_explicit_entry_uses_existing_t1_media_user2_and_never_emits_by_default(self):
        output = Path(self.scratch.name) / 'never-created'
        with mock.patch.object(self.entry, 'exporter_module', return_value=self.new), \
                mock.patch.object(self.new.subprocess, 'check_output', return_value='0' * 40 + '\n'), \
                mock.patch.object(self.new.subprocess, 'run', side_effect=AssertionError('unexpected emitter/tool')), \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.entry.main(['--output', str(output)])
        result = json.loads(stdout.getvalue())
        self.assertEqual(result['status'], 'PREFLIGHT_ONLY')
        self.assertEqual(result['native_mac_mode'], self.new.board_t1.selection(True))
        self.assertEqual(set(result['command'][5:]), set(self.options64))
        self.assertEqual(result['configuration']['bscan_chain'], 2)
        self.assertEqual(result['configuration']['jtag_backend'], 'bscan-user-v1')
        self.assertFalse(result['configuration']['debug_module_implemented'])
        self.assertFalse(result['physical_qualification'])
        self.assertFalse(output.exists())
        with mock.patch.object(self.entry, 'exporter_module', return_value=self.new), \
                mock.patch.object(self.new, 'main') as exporter:
            self.entry.main(['--output', str(output), '--emit'])
        args = exporter.call_args.args[0]
        self.assertEqual(args[-1], '--emit')
        self.assertEqual(args.count(self.new.board_t1.FLAG), 1)
        for wrong in ('--reference', '--fetch-ready-data-clear', '--em'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.entry.main(['--output', str(output), wrong])

    def test_new_entry_binds_changed_production_and_rejects_historical_certificate_reuse(self):
        original = self.entry.MANIFEST.read_bytes()
        try:
            profile = json.loads(original)
            first = next(iter(profile['production_leaf_sha256']))
            profile['production_leaf_sha256'][first] = '0' * 64
            self.entry.MANIFEST.write_text(json.dumps(profile))
            with self.assertRaisesRegex(RuntimeError, 'production leaf differs'):
                self.entry.load_profile()
            profile = json.loads(original)
            profile['historical_mapped_library_certificate']['reused_for_new_rtl'] = True
            self.entry.MANIFEST.write_text(json.dumps(profile))
            with self.assertRaisesRegex(RuntimeError, 'cannot qualify the new RTL'):
                self.entry.load_profile()
        finally:
            self.entry.MANIFEST.write_bytes(original)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--baseline-root', type=Path)
    args = parser.parse_args()
    BASE = args.baseline_root.resolve() if args.baseline_root is not None else None
    unittest.main(argv=[__file__], verbosity=2)
