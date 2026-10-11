"""Complete executed constructor bridge and strict optional entry checks."""
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
import board_durable_read_prefetch as candidate
import board_bound_store_prefetch as rollback
import export as exporter


class BoardDurableReadPrefetchTests(unittest.TestCase):
    def test_full_executed_constructor_and_exact_three_option_delta(self):
        spec = candidate.load_manifest()
        expected = candidate.expected_constructor()
        self.assertEqual(candidate.native_options(), rollback.native_options() + [
            "--pending-ready-store-bypass", "--durable-read-prefetch-candidate", "--read-prefetch-behind-store"])
        self.assertEqual(expected, spec["constructor_profile"])
        self.assertEqual({k: len(expected[k]) for k in ("profile", "core", "cache")},
                         {"profile": 56, "core": 149, "cache": 19})
        self.assertEqual(spec["executed_fabric"]["cpu"], expected["core"])
        self.assertEqual(spec["executed_fabric"]["cache"], expected["cache"])
        self.assertEqual(expected["core"]["robEntries"], 16)
        self.assertEqual(expected["core"]["physicalRegs"], 48)
        self.assertEqual(expected["core"]["memoryEntries"], 4)
        self.assertEqual(expected["derived"]["dataTranslationEntries"], 16)
        self.assertEqual(expected["profile"]["dmaLineEntries"], 4)
        candidate.compare_constructor(expected)
        with self.assertRaises(RuntimeError):
            candidate.compare_constructor(rollback.expected_constructor())

    def test_source_preflight_exact_options_profile_and_no_output(self):
        spec = candidate.load_manifest()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "absent"
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                candidate.main(["--output", str(output)])
            self.assertFalse(output.exists())
            result = json.loads(stream.getvalue())
        self.assertEqual(result["configuration"], spec["export_profile"])
        self.assertEqual(result["command"][5:], spec["canonical_export_native_options"])
        self.assertEqual(set(result["command"][5:]), set(candidate.native_options()))
        self.assertFalse(result["physical_qualification"])

    def test_each_nested_field_missing_changed_or_unknown_fails(self):
        expected = candidate.expected_constructor()
        def walk(value, path=()):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield path + (key,)
                    yield from walk(child, path + (key,))
        for path in walk(expected):
            for action in ("missing", "changed"):
                actual = copy.deepcopy(expected)
                parent = actual
                for key in path[:-1]:
                    parent = parent[key]
                if action == "missing":
                    del parent[path[-1]]
                else:
                    parent[path[-1]] = "invalid-constructor-value"
                with self.subTest(path=path, action=action), self.assertRaises(RuntimeError):
                    candidate.compare_constructor(actual)
        actual = copy.deepcopy(expected)
        actual["core"]["unknownFutureField"] = False
        with self.assertRaises(RuntimeError):
            candidate.compare_constructor(actual)

    def test_rollback_defaults_and_metadata_stay_frozen(self):
        old = rollback.expected_constructor()
        for section in ("profile", "core"):
            self.assertIs(old[section]["pendingReadyStoreBypass"], False)
        for section in ("profile", "cache"):
            self.assertIs(old[section]["durableReadPrefetchCandidate"], False)
            self.assertIs(old[section]["readPrefetchBehindStore"], False)
        self.assertEqual(hashlib.sha256(rollback.MANIFEST.read_bytes()).hexdigest(),
                         "6f098035333e6a0d9ccf035df0a4f5da23fdd67e4aa60dfa3c305522e5ae8708")
        self.assertEqual(candidate.load_manifest()["rollback"]["source_commit"],
                         "81ed0a53a066ff724101f6d9f2d19f764c32c520")

    def test_fail_closed_overrides_and_manifest_drift(self):
        for option in ("--pending-ready-store-bypass", "--read-prefetch-behind-store=false",
                       "--lsu-entries=2", "--reference", "--experimental-jtag-bscan=1"):
            with self.subTest(option=option), mock.patch.object(exporter, "main") as emit:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    candidate.main(["--output", "/unused", option])
                emit.assert_not_called()
        with mock.patch.object(candidate, "MANIFEST_SHA256", "0" * 64):
            with self.assertRaises(RuntimeError):
                candidate.main(["--output", "/unused", "--emit"])


if __name__ == "__main__":
    unittest.main()
