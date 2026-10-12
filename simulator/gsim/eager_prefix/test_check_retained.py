#!/usr/bin/env python3
"""Bounded public receipt and source-contract negative checks; no hardware."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('eager_prefix_check', HERE / 'check_retained.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
SOURCE = HERE.parents[2]


class PublicReceiptTests(unittest.TestCase):
    def setUp(self):
        self.receipt = checker.read_receipt(SOURCE)

    def test_positive_scope(self):
        result = checker.check(SOURCE)
        self.assertEqual(result['status'], 'PASS_PUBLIC_RECEIPT_AND_LOCAL_SOURCE_CONFIG_SUBSET')
        self.assertEqual((result['default_native_option_count'], result['optional_native_option_count']), (52, 53))
        self.assertFalse(result['full_qualification_reexecuted'])
        self.assertFalse(result['default52_cpu_rerun'])
        self.assertEqual(result['external_bundles_hash_verified'], [])
        self.assertTrue(result['external_unverified_references'])

    def test_receipt_bytes_missing_schema_and_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / checker.RECEIPT_PATH
            path.parent.mkdir(parents=True)
            path.write_bytes((SOURCE / checker.RECEIPT_PATH).read_bytes() + b' ')
            with self.assertRaisesRegex(RuntimeError, 'receipt identity'):
                checker.read_receipt(root)
            bad = copy.deepcopy(self.receipt); bad['unreviewed_inventory'] = {}
            path.write_text(json.dumps(bad))
            with mock.patch.object(checker, 'RECEIPT_SHA256', checker.sha(path)), self.assertRaisesRegex(RuntimeError, 'schema'):
                checker.read_receipt(root)
            path.unlink()
            with self.assertRaisesRegex(RuntimeError, 'missing or symlink'):
                checker.read_receipt(root)
            file = root / 'plain'; file.write_text('test')
            (root / 'link').symlink_to(file)
            for name in ('../escape', '/absolute', 'link', 'missing'):
                with self.subTest(name=name), self.assertRaises(RuntimeError):
                    checker.safe_file(root, name)

    def test_recorded_scope_mutations(self):
        mutations = [
            lambda b: b['recorded_qualification'].update(physical_qualification=True),
            lambda b: b['recorded_qualification']['cpu']['inclusive_cycles'].update(bare=1),
            lambda b: b['recorded_qualification']['cpu'].update(off_models=1),
            lambda b: b['recorded_qualification']['native'].update(removed_indexed_64bit_selectors=4),
            lambda b: b['recorded_qualification']['native'].update(wide_masks_before_after=[3, 3]),
            lambda b: b['recorded_qualification']['nemu']['zero_work'].update(dut_object_compiles=1),
            lambda b: b['default52_bridge'].update(raw_native_byte_identical=True),
            lambda b: b['default52_bridge'].update(automatic_local_declarations=3),
        ]
        for number, mutate in enumerate(mutations):
            bad = copy.deepcopy(self.receipt); mutate(bad)
            with self.subTest(number=number), self.assertRaises(RuntimeError):
                checker.check_record(bad)

    def test_source_configuration_mutations(self):
        mutations = [
            lambda b: b['source_fingerprints'].pop(next(iter(b['source_fingerprints']))),
            lambda b: b['production_source_closure'].update(canonical_sha256='0' * 64),
            lambda b: b['qualified_scala_source_closure'].update(file_count=1),
            lambda b: b['configuration']['native_options'].remove('--eager-fetch-prefix-select'),
            lambda b: b['configuration'].update(native_mac_t1=False),
            lambda b: b['configuration'].update(jtag_user_chain=1),
            lambda b: b['configuration']['fixture_overrides'].update(lsuEntries=2),
            lambda b: b['configuration']['actual_eager_prefix'].update(selectedPacketEagerPrefixSelect=False),
        ]
        for number, mutate in enumerate(mutations):
            bad = copy.deepcopy(self.receipt); mutate(bad)
            with self.subTest(number=number), mock.patch.object(checker, 'read_receipt', return_value=bad), self.assertRaises(RuntimeError):
                checker.check(SOURCE)

    def test_wrong_external_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'incorrect'; path.write_text('not the evidence')
            with self.assertRaisesRegex(RuntimeError, 'external bundle content hash'):
                checker.check(SOURCE, {'complete_qualification': path})


if __name__ == '__main__':
    unittest.main()
