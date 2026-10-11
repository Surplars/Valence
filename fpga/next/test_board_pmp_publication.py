"""Versioned PMP entry and complete constructor contracts; no hardware builds."""
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
import board_pmp_publication as candidate
import board_timing_cdc as rollback
import export as exporter


class BoardPmpPublicationTests(unittest.TestCase):
    def test_new_optional_fields_are_explicit_false_and_fail_closed(self):
        self.check_optional_defaults(candidate.expected_constructor(), candidate.compare_constructor)

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

    def test_complete_preflight_and_exact_options(self):
        spec = candidate.load_manifest()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "absent"
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                candidate.main(["--output", str(output)])
            self.assertFalse(output.exists())
            actual = json.loads(stream.getvalue())
        self.assertEqual(candidate.native_options(), rollback.native_options() + ["--published-pmp-changes"])
        self.assertEqual(actual["command"][5:], spec["canonical_export_native_options"])
        self.assertEqual(actual["configuration"], spec["export_profile"])
        self.assertEqual([x for x in actual["command"][5:] if x != "--published-pmp-changes"], rollback.native_options())
        self.assertEqual(actual["command"].count("--published-pmp-changes"), 1)
        self.assertFalse(actual["physical_qualification"])
        old = rollback.load_manifest()["export_profile"]
        self.assertEqual({k for k in old.keys() | spec["export_profile"].keys()
                          if old.get(k) != spec["export_profile"].get(k)}, {"name", "published_pmp_changes"})

    def test_all_constructor_fields_fail_closed(self):
        expected = candidate.expected_constructor()
        candidate.compare_constructor(expected)
        old = rollback.expected_constructor()
        for section, fields in expected.items():
            if not isinstance(fields, dict):
                self.assertEqual(fields, old[section])
                continue
            self.assertEqual({k for k in fields if fields[k] != old[section][k]},
                             {"publishedPmpChanges"} if section in ("core", "profile") else set())
            for key in fields:
                actual = copy.deepcopy(expected)
                del actual[section][key]
                with self.subTest(section=section, key=key), self.assertRaises(RuntimeError):
                    candidate.compare_constructor(actual)
            actual = copy.deepcopy(expected)
            actual[section]["unexpectedFutureField"] = False
            with self.assertRaises(RuntimeError):
                candidate.compare_constructor(actual)
        with self.assertRaises(RuntimeError):
            candidate.compare_constructor(old)

    def test_no_overrides_or_manifest_drift(self):
        for option in ("--published-pmp-changes", "--reference", "--lsu-entries=2", "--experimental-jtag-bscan=1"):
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
