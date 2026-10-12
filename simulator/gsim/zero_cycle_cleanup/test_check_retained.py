#!/usr/bin/env python3
"""Small receipt/source-contract mutation tests; no compiler, simulator or FPGA tools."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("minimal_check", HERE / "check_retained.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
SOURCE = HERE.parents[2]


class MinimalReceiptTests(unittest.TestCase):
    def setUp(self):
        self.receipt = checker.read_receipt(SOURCE)

    def test_positive_scope_and_no_external_revalidation_claim(self):
        result = checker.check(SOURCE)
        self.assertEqual(result["status"], "PASS_MINIMAL_RECEIPT_AND_LOCAL_SOURCE_CONFIG_SUBSET")
        self.assertFalse(result["full_qualification_reexecuted"])
        self.assertFalse(result["synthesis_consumer_executed"])
        self.assertEqual(result["external_bundles_hash_verified"], [])
        self.assertEqual(len(result["external_unverified_references"]), 3)

    def test_receipt_byte_mutation_and_missing_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / checker.RECEIPT_PATH
            target.parent.mkdir(parents=True)
            target.write_bytes((SOURCE / checker.RECEIPT_PATH).read_bytes() + b" ")
            with self.assertRaisesRegex(RuntimeError, "receipt identity"):
                checker.read_receipt(root)
            target.unlink()
            with self.assertRaisesRegex(RuntimeError, "missing or symlink"):
                checker.read_receipt(root)

    def test_rehashed_schema_and_external_reference_mutations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / checker.RECEIPT_PATH
            target.parent.mkdir(parents=True)
            for kind in ("schema", "external"):
                bad = copy.deepcopy(self.receipt)
                if kind == "schema":
                    bad["unreviewed_inventory"] = {}
                else:
                    bad["external_evidence_sha256"]["complete_qualification"] = "0" * 64
                target.write_text(json.dumps(bad))
                with mock.patch.object(checker, "RECEIPT_SHA256", checker.sha(target)), self.assertRaises(RuntimeError):
                    checker.read_receipt(root)

    def test_recorded_result_scope_and_option_mutations(self):
        mutations = [
            lambda b: b["recorded_qualification"].update(physical_qualification=True),
            lambda b: b["recorded_qualification"]["cpu"]["inclusive_cycles"].update(bare=1),
            lambda b: b["recorded_qualification"]["native"].update(module_count=238),
            lambda b: b["recorded_qualification"]["nemu"]["zero_work"].update(dut_object_compiles=1),
            lambda b: b["configuration"]["native_options"].remove("--local-payload-write-enable"),
            lambda b: b["configuration"].update(native_mac_t1=False),
            lambda b: b["configuration"].update(jtag_user_chain=1),
            lambda b: b["configuration"]["fixture_overrides"].update(lsuEntries=2),
        ]
        for number, mutate in enumerate(mutations):
            bad = copy.deepcopy(self.receipt)
            mutate(bad)
            with self.subTest(number=number), mock.patch.object(checker, "read_receipt", return_value=bad), self.assertRaises(RuntimeError):
                checker.check(SOURCE)

    def test_source_removal_changed_bytes_and_aggregate_mutations(self):
        name = next(iter(self.receipt["source_fingerprints"]))
        for kind in ("remove", "bytes", "scope", "aggregate"):
            bad = copy.deepcopy(self.receipt)
            if kind == "remove":
                bad["source_fingerprints"].pop(name)
            elif kind == "bytes":
                bad["source_fingerprints"][name] = "0" * 64
            elif kind == "scope":
                bad["production_source_closure"]["scope"].pop()
            else:
                bad["production_source_closure"]["canonical_sha256"] = "0" * 64
            with self.subTest(kind=kind), mock.patch.object(checker, "read_receipt", return_value=bad), self.assertRaises(RuntimeError):
                checker.check(SOURCE)

    def test_paths_and_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            file = root / "file"
            file.write_text("safe")
            (root / "link").symlink_to(file)
            for name in ("../escape", "/outside", "link", "missing"):
                with self.subTest(name=name), self.assertRaises(RuntimeError):
                    checker.safe_file(root, name)

    def test_wrong_external_bundle_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / "wrong-bundle"
            file.write_text("not the qualified bundle")
            with self.assertRaisesRegex(RuntimeError, "external bundle content hash"):
                checker.check(SOURCE, {"complete_qualification": file})


if __name__ == "__main__":
    unittest.main()
