"""Host-only full-profile parity, strict drift gates, and optional export checks."""
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
import board_dual_proof_credit as candidate
import board_durable_read_prefetch as rollback
import export as exporter


class BoardDualProofCreditTests(unittest.TestCase):
    def test_complete_constructor_changes_only_rows_and_credits(self):
        spec = candidate.load_manifest()
        old = rollback.expected_constructor()
        expected = copy.deepcopy(old)
        for section in ("profile", "core"):
            for field in candidate.CAPACITIES:
                self.assertEqual(expected[section][field], 1)
                expected[section][field] = 2
        self.assertEqual(candidate.expected_constructor(), expected)
        historical = copy.deepcopy(expected)
        for section in ("profile", "cache"):
            for field in ("internalLineGrant", "concurrentReadStorePrefetch", "memoryScheduleOverlap"):
                self.assertIs(historical[section].pop(field), False)
        for section in ("profile", "core"):
            self.assertIs(historical[section].pop("taggedStoreReturns"), False)
        self.assertEqual(historical, spec["constructor_profile"])
        self.assertEqual({k: len(expected[k]) for k in ("profile", "core", "cache")},
                         {"profile": 61, "core": 151, "cache": 22})
        self.assertEqual(expected["core"]["robEntries"], 16)
        self.assertEqual(expected["core"]["physicalRegs"], 48)
        self.assertEqual(expected["core"]["memoryEntries"], 4)
        self.assertEqual(expected["derived"]["dataTranslationEntries"], 16)
        self.assertEqual(expected["profile"]["dmaLineEntries"], 4)
        candidate.compare_constructor(expected)
        with self.assertRaises(RuntimeError):
            candidate.compare_constructor(old)
        self.assertEqual(rollback.expected_constructor(), old)

    def test_complete_fabric_has_only_expected_side_schema_bridge_and_capacities(self):
        spec = candidate.load_manifest()
        expected = copy.deepcopy(rollback.load_manifest()["executed_fabric"])
        self.assertNotIn("pendingStoreEarlyLoadCredits", expected["cpu"])
        expected["cpu"]["pendingStoreEarlyLoadCredits"] = 1
        for field in candidate.CAPACITIES:
            self.assertEqual(expected["cpu"][field], 1)
            expected["cpu"][field] = 2
        historical = copy.deepcopy(expected)
        expected["cpu"]["taggedStoreReturns"] = False
        expected["cache"]["internalLineGrant"] = False
        expected["cache"]["concurrentReadStorePrefetch"] = False
        expected["cache"]["memoryScheduleOverlap"] = False
        self.assertEqual(candidate.expected_fabric(), expected)
        self.assertEqual(historical, spec["executed_fabric"])
        constructor = candidate.expected_constructor()
        for fabric_key, constructor_key in (("cpu", "core"), ("cache", "cache"), ("ddr", "ddr")):
            self.assertEqual(expected[fabric_key], constructor[constructor_key])
        self.assertEqual(spec["expected_only_schema_bridge"], {
            "baseline_default": 1, "new_field": "pendingStoreEarlyLoadCredits",
            "other_missing_fields_allowed": False})
        self.assertEqual(spec["capacity_delta"], {field: [1, 2] for field in candidate.CAPACITIES})
        candidate.compare_fabric(expected)

    def test_native_options_are_exact_rollback_plus_two_capacities(self):
        options = rollback.native_options()
        options[options.index("--pending-virtual-store-proof-slots=1")] = "--pending-virtual-store-proof-slots=2"
        options.append("--pending-store-early-load-credits=2")
        self.assertEqual(candidate.native_options(), options)
        self.assertEqual(len(options), 39)
        self.assertEqual(len(options), len({option.split("=", 1)[0] for option in options}))
        output = io.StringIO()
        with contextlib.redirect_stdout(output), mock.patch.object(exporter, "main") as export:
            candidate.main(["--print-native-options"])
        export.assert_not_called()
        self.assertEqual(json.loads(output.getvalue()), options)

    def test_source_preflight_exact_options_profile_digest_and_no_output(self):
        spec = candidate.load_manifest()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "absent"
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                candidate.main(["--output", str(output)])
            self.assertFalse(output.exists())
            result = json.loads(stream.getvalue())
        self.assertEqual(result["status"], "PREFLIGHT_ONLY")
        self.assertEqual(result["configuration"], spec["export_profile"])
        self.assertEqual(result["command"][5:], spec["canonical_export_native_options"])
        self.assertEqual(sorted(result["command"][5:]), sorted(candidate.native_options()))
        digest = hashlib.sha256(json.dumps(result["configuration"], sort_keys=True,
                                          separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(digest, spec["export_profile_sha256"])
        self.assertFalse(result["physical_qualification"])
        previous = copy.deepcopy(rollback.load_manifest()["export_profile"])
        previous["pending_virtual_store_proof_slots"] = 2
        previous["pending_store_early_load_credits"] = 2
        previous["name"] = previous["name"].replace(
            "-pending-virtual-store-proof1-", "-pending-virtual-store-proof2-pending-store-early-load-credits2-")
        self.assertEqual(result["configuration"], previous)

    def test_emit_forwards_exact_options_and_pinned_profile_hash_without_building(self):
        spec = candidate.load_manifest()
        with mock.patch.object(exporter, "main") as export:
            candidate.main(["--output", "/unused", "--emit"])
        export.assert_called_once_with(
            ["--output", "/unused", *(o for o in candidate.native_options() if o != "--selected"), "--emit"],
            expected_profile_sha256=spec["export_profile_sha256"])

    def test_every_nested_constructor_and_fabric_field_fails_closed(self):
        def walk(value, path=()):
            yield path, value
            if isinstance(value, dict):
                for key, child in value.items():
                    yield from walk(child, path + (key,))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    yield from walk(child, path + (index,))

        for label, expected, compare in (
                ("constructor", candidate.expected_constructor(), candidate.compare_constructor),
                ("fabric", candidate.expected_fabric(), candidate.compare_fabric)):
            for path, value in walk(expected):
                actions = (["missing", "changed"] if path else []) + (["unknown"] if isinstance(value, dict) else [])
                for action in actions:
                    actual = copy.deepcopy(expected)
                    target = actual
                    for key in path if action == "unknown" else path[:-1]:
                        target = target[key]
                    if action == "unknown":
                        target["unknownFutureField"] = False
                    elif action == "missing":
                        del target[path[-1]]
                    else:
                        target[path[-1]] = "invalid-profile-value"
                    with self.subTest(label=label, path=path, action=action), self.assertRaises(RuntimeError):
                        compare(actual)
            actual = copy.deepcopy(expected)
            actual["core" if label == "constructor" else "cpu"]["pendingStoreEarlyLoadCredits"] = 2.0
            with self.assertRaises(RuntimeError):
                compare(actual)
            actual = copy.deepcopy(expected)
            actual["core" if label == "constructor" else "cpu"]["pendingVirtualStoreProof"] = 1
            with self.assertRaises(RuntimeError):
                compare(actual)

    def test_generic_defaults_and_rollback_manifests_stay_frozen(self):
        old = rollback.expected_constructor()
        for section in ("profile", "core"):
            for field in candidate.CAPACITIES:
                self.assertEqual(old[section][field], 1)
        frozen = {
            "board-bound-store-prefetch-profile-v1.json": "6f098035333e6a0d9ccf035df0a4f5da23fdd67e4aa60dfa3c305522e5ae8708",
            "board-durable-read-prefetch-profile-v1.json": "0dbe7ba7360a6314a8f9bf289a7d42cc6c5c68ed94c02cd147e263b24d97210e",
            "board-pmp-publication-profile-v1.json": "7e12930ef8c787532c5a3ee8712fc8f639f4a3dff20d80d343cf11a0f024216c",
            "board-timing-cdc-profile-v1.json": "f8d871a68a29d506e2303047450a04694f6c08c8532c2df3f2405381b8228610"}
        for name, digest in frozen.items():
            self.assertEqual(hashlib.sha256(candidate.MANIFEST.with_name(name).read_bytes()).hexdigest(), digest)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "absent"
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                exporter.main(["--output", str(output)])
            self.assertFalse(output.exists())
            result = json.loads(stream.getvalue())
        for field in ("pending_virtual_store_proof_slots", "pending_store_early_load_credits"):
            self.assertEqual(result[field], 1)
        for option in ("--pending-virtual-store-proof-slots", "--pending-store-early-load-credits"):
            self.assertFalse(any(arg.startswith(option) for arg in result["command"][5:]))

    def test_overrides_abbreviations_and_invalid_combinations_are_rejected(self):
        for args in ([], ["--emit"], ["--out", "/unused"], ["--em"],
                     ["--print-native-options", "--output", "/unused"],
                     ["--print-native-options", "--emit"]):
            with self.subTest(args=args), mock.patch.object(exporter, "main") as export:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    candidate.main(args)
                export.assert_not_called()
        for option in ("--pending-virtual-store-proof-slots=1", "--pending-virtual-store-proof-slots=2",
                       "--pending-store-early-load-credits=1", "--pending-store-early-load-credits=2",
                       "--read-prefetch-behind-store=false", "--lsu-entries=2", "--reference",
                       "--experimental-jtag-bscan=1"):
            with self.subTest(option=option), mock.patch.object(exporter, "main") as export:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    candidate.main(["--output", "/unused", option])
                export.assert_not_called()

    def test_manifest_rollback_and_export_profile_drift_are_rejected(self):
        for module in (candidate, rollback):
            with mock.patch.object(module, "MANIFEST_SHA256", "0" * 64):
                with mock.patch.object(exporter, "main") as export, self.assertRaises(RuntimeError):
                    candidate.main(["--output", "/unused", "--emit"])
                export.assert_not_called()
        spec = candidate.load_manifest()
        spec["export_profile_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "absent"
            with mock.patch.object(candidate, "load_manifest", return_value=spec):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    candidate.main(["--output", str(output), "--emit"])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
