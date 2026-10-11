"""Frozen candidate identity and fail-closed host contracts; no DUT qualification."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board_release
import board_timing_cdc
import export as exporter


class BoardTimingCdcTests(unittest.TestCase):
    def test_new_optional_fields_are_explicit_false_and_fail_closed(self):
        self.check_optional_defaults(board_timing_cdc.expected_constructor(), board_timing_cdc.compare_constructor)

    def check_optional_defaults(self, expected, compare):
        compare(expected)
        self.assertEqual(tuple(len(expected[s]) for s in ("profile", "core", "cache")), (53, 148, 17))
        fields = [(s, f) for s in ("profile", "core")
                  for f in ("frozenStoreProofTransport", "pendingVirtualStoreProof", "boundHeadStoreOverlap")]
        fields += [(s, "readPrefetchStoreHold") for s in ("profile", "cache")]
        for section, field in fields:
            self.assertIs(expected[section][field], False)
            for mutation in ("missing", "enabled"):
                actual = copy.deepcopy(expected)
                if mutation == "missing":
                    del actual[section][field]
                else:
                    actual[section][field] = True
                with self.subTest(section=section, field=field, mutation=mutation), self.assertRaises(RuntimeError):
                    compare(actual)
        for section in ("profile", "core"):
            self.assertEqual(expected[section]["pendingVirtualStoreProofSlots"], 1)
            for value in (None, 0, 2):
                actual = copy.deepcopy(expected)
                if value is None:
                    del actual[section]["pendingVirtualStoreProofSlots"]
                else:
                    actual[section]["pendingVirtualStoreProofSlots"] = value
                with self.assertRaises(RuntimeError):
                    compare(actual)
        for section in expected:
            if not isinstance(expected[section], dict):
                continue
            actual = copy.deepcopy(expected)
            actual[section]["unknownOptionalField"] = False
            with self.assertRaises(RuntimeError):
                compare(actual)

    def test_exact_complete_profile_and_only_three_policy_changes(self):
        spec = board_timing_cdc.load_manifest()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "not-created"
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                board_timing_cdc.main(["--output", str(output)])
            actual = json.loads(capture.getvalue())
            self.assertFalse(output.exists())
        self.assertEqual(actual["command"][5:], spec["native_options"])
        self.assertEqual(actual["configuration"], spec["export_profile"])
        self.assertEqual(set(spec["native_options"]) - set(board_release.native_options()),
                         {"--registered-pmp-regions", "--read-prefetch-dirty-retry", "--read-prefetch-demand-adoption"})
        self.assertEqual(set(board_release.native_options()) - set(spec["native_options"]), set())
        old = board_release.load_manifest()["export_profile"]
        self.assertEqual({key for key in old.keys() | actual["configuration"].keys()
                          if old.get(key) != actual["configuration"].get(key)},
                         {"name", "read_prefetch_dirty_retry", "read_prefetch_demand_adoption", "registered_pmp_regions"})

    def test_complete_constructor_rejects_each_missing_or_additional_product_field(self):
        expected = board_timing_cdc.expected_constructor()
        board_timing_cdc.compare_constructor(expected)
        for section, fields in expected.items():
            if not isinstance(fields, dict):
                continue
            for key in fields:
                actual = copy.deepcopy(expected)
                del actual[section][key]
                with self.subTest(section=section, key=key), self.assertRaises(RuntimeError):
                    board_timing_cdc.compare_constructor(actual)
            actual = copy.deepcopy(expected)
            actual[section]["unknownFutureOption"] = False
            with self.subTest(section=section), self.assertRaises(RuntimeError):
                board_timing_cdc.compare_constructor(actual)
        for section, field in (("profile", "registeredPmpRegions"), ("core", "registeredPmpRegions"),
                               ("profile", "readPrefetchDirtyRetry"), ("cache", "readPrefetchDirtyRetry"),
                               ("profile", "readPrefetchDemandAdoption"), ("cache", "readPrefetchDemandAdoption")):
            actual = copy.deepcopy(expected)
            actual[section][field] = False
            with self.subTest(section=section, field=field), self.assertRaises(RuntimeError):
                board_timing_cdc.compare_constructor(actual)

    def test_published_pmp_change_is_false_in_the_preserved_release(self):
        expected = board_timing_cdc.expected_constructor()
        for section in ("profile", "core"):
            self.assertIs(expected[section]["publishedPmpChanges"], False)
            changed = copy.deepcopy(expected)
            changed[section]["publishedPmpChanges"] = True
            with self.assertRaises(RuntimeError):
                board_timing_cdc.compare_constructor(changed)

    def test_overrides_and_manifest_drift_do_not_emit(self):
        for option in ("--experimental-jtag-bscan=1", "--lsu-entries=2", "--registered-pmp", "--mode=A", "--reference"):
            with self.subTest(option=option), mock.patch.object(exporter, "main") as emit, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    board_timing_cdc.main(["--output", "/unused", option])
                emit.assert_not_called()
        with mock.patch.object(board_timing_cdc, "MANIFEST_SHA256", "0" * 64), \
                mock.patch.object(exporter, "main") as emit:
            with self.assertRaises(RuntimeError):
                board_timing_cdc.main(["--output", "/unused", "--emit"])
            emit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
