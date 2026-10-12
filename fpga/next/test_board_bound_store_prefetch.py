"""Complete optional profile, rollback, and fail-closed source-only contracts."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board_bound_store_prefetch as candidate
import board_pmp_publication as rollback
import export as exporter


class BoardBoundStorePrefetchTests(unittest.TestCase):
    def test_exact_complete_preflight_and_five_argument_delta(self):
        spec = candidate.load_manifest()
        delta = ["--frozen-store-proof-transport", "--pending-virtual-store-proof",
                 "--pending-virtual-store-proof-slots=1", "--bound-head-store-overlap",
                 "--read-prefetch-store-hold"]
        self.assertEqual(candidate.native_options(), rollback.native_options() + delta)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "absent"
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                candidate.main(["--output", str(output)])
            self.assertFalse(output.exists())
            actual = json.loads(stream.getvalue())
        self.assertEqual(actual["configuration"], spec["export_profile"])
        self.assertEqual(actual["command"][5:], spec["canonical_export_native_options"])
        self.assertEqual(set(actual["command"][5:]), set(candidate.native_options()))
        self.assertFalse(actual["physical_qualification"])
        old = rollback.load_manifest()["export_profile"]
        self.assertEqual({k for k in old.keys() | spec["export_profile"].keys()
                          if old.get(k) != spec["export_profile"].get(k)},
                         {"name", "frozen_store_proof_transport", "pending_virtual_store_proof",
                          "pending_virtual_store_proof_slots", "bound_head_store_overlap", "read_prefetch_store_hold"})
        self.assertEqual(hashlib.sha256(rollback.MANIFEST.read_bytes()).hexdigest(),
                         "7e12930ef8c787532c5a3ee8712fc8f639f4a3dff20d80d343cf11a0f024216c")

    def test_complete_expectation_is_bound_to_executed_reference(self):
        expected = candidate.expected_constructor()
        reference = candidate.load_manifest()["constructor_profile"]
        historical = copy.deepcopy(expected)
        for section in ("profile", "cache"):
            for field in ("internalLineGrant", "concurrentReadStorePrefetch", "memoryScheduleOverlap"):
                self.assertIs(historical[section].pop(field), False)
        for section in ("profile", "core"):
            self.assertIs(historical[section].pop("taggedStoreReturns"), False)
            self.assertEqual(historical[section].pop("pendingStoreEarlyLoadCredits"), 1)
            self.assertIs(historical[section].pop("pendingReadyStoreBypass"), False)
        for section in ("profile", "cache"):
            for field in ("durableReadPrefetchCandidate", "readPrefetchBehindStore"):
                self.assertIs(historical[section].pop(field), False)
        self.assertEqual(historical, reference)
        self.assertEqual(tuple(len(expected[s]) for s in ("profile", "core", "cache")), (61, 151, 22))
        self.assertEqual(tuple(len(reference[s]) for s in ("profile", "core", "cache")), (53, 148, 17))
        self.assertIsNone(reference["profile"]["robEntries"])
        self.assertIsNone(reference["profile"]["physicalRegs"])
        self.assertEqual(reference["core"]["robEntries"], 16)
        self.assertEqual(reference["core"]["physicalRegs"], 48)
        old = rollback.expected_constructor()
        allowed = {"profile": {"frozenStoreProofTransport", "pendingVirtualStoreProof",
                              "boundHeadStoreOverlap", "readPrefetchStoreHold"},
                   "core": {"frozenStoreProofTransport", "pendingVirtualStoreProof", "boundHeadStoreOverlap"},
                   "cache": {"readPrefetchStoreHold"}}
        for section, fields in expected.items():
            if isinstance(fields, dict):
                self.assertEqual({k for k in fields.keys() | old[section].keys()
                                  if fields.get(k) != old[section].get(k)}, allowed.get(section, set()))
            else:
                self.assertEqual(fields, old[section])
        for section in ("core", "profile"):
            self.assertEqual(reference[section]["pendingVirtualStoreProofSlots"], 1)
        candidate.compare_constructor(expected)
        with self.assertRaises(RuntimeError):
            candidate.compare_constructor(reference)
        with self.assertRaises(RuntimeError):
            candidate.compare_constructor(old)

    def test_each_missing_changed_and_unknown_field_fails_closed(self):
        expected = candidate.expected_constructor()
        for section, fields in expected.items():
            if not isinstance(fields, dict):
                continue
            for key, value in fields.items():
                for mutation in ("missing", "changed"):
                    actual = copy.deepcopy(expected)
                    if mutation == "missing":
                        del actual[section][key]
                    else:
                        actual[section][key] = not value if isinstance(value, bool) else "invalid-value"
                    with self.subTest(section=section, key=key, mutation=mutation), self.assertRaises(RuntimeError):
                        candidate.compare_constructor(actual)
            actual = copy.deepcopy(expected)
            actual[section]["unknownFutureField"] = False
            with self.assertRaises(RuntimeError):
                candidate.compare_constructor(actual)
        for section in ("profile", "core"):
            actual = copy.deepcopy(expected)
            actual[section]["pendingVirtualStoreProofSlots"] = 2
            with self.assertRaises(RuntimeError):
                candidate.compare_constructor(actual)

    def test_no_overrides_or_manifest_drift(self):
        for option in ("--bound-head-store-overlap", "--read-prefetch-store-hold=false", "--reference",
                       "--lsu-entries=2", "--pending-virtual-store-proof-slots=2", "--experimental-jtag-bscan=1"):
            with self.subTest(option=option), mock.patch.object(exporter, "main") as emit, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    candidate.main(["--output", "/unused", option])
                emit.assert_not_called()
        with mock.patch.object(candidate, "MANIFEST_SHA256", "0" * 64), mock.patch.object(exporter, "main") as emit:
            with self.assertRaises(RuntimeError):
                candidate.main(["--output", "/unused", "--emit"])
            emit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
