"""Release-profile drift gates; no hardware or physical qualification claim."""
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
import board_profile
import board_release
import export as exporter


class BoardReleaseTests(unittest.TestCase):
    def test_new_optional_fields_are_explicit_false_and_fail_closed(self):
        import board_timing_cdc
        expected = board_timing_cdc.expected_constructor()
        for section in ("profile", "core"):
            expected[section]["registeredPmpRegions"] = False
        for section in ("profile", "cache"):
            expected[section]["readPrefetchDirtyRetry"] = False
            expected[section]["readPrefetchDemandAdoption"] = False
        self.check_optional_defaults(expected, board_release.compare_constructor)

    def check_optional_defaults(self, expected, compare):
        compare(expected)
        self.assertEqual(tuple(len(expected[s]) for s in ("profile", "core", "cache")), (57, 150, 19))
        fields = [(s, f) for s in ("profile", "core")
                  for f in ("frozenStoreProofTransport", "pendingVirtualStoreProof", "boundHeadStoreOverlap", "pendingReadyStoreBypass")]
        fields += [(s, f) for s in ("profile", "cache")
                   for f in ("readPrefetchStoreHold", "durableReadPrefetchCandidate", "readPrefetchBehindStore")]
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
            self.assertEqual(expected[section]["pendingStoreEarlyLoadCredits"], 1)
            for value in (None, 0, 2):
                actual = copy.deepcopy(expected)
                if value is None:
                    del actual[section]["pendingStoreEarlyLoadCredits"]
                else:
                    actual[section]["pendingStoreEarlyLoadCredits"] = value
                with self.assertRaises(RuntimeError):
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

    def test_exact_cpu_B_and_only_explicit_perimeter_changes(self):
        base = board_profile.native_options("B")
        options = board_release.native_options()
        self.assertEqual([x for x in options if not x.startswith("--experimental-")], base)
        self.assertEqual(set(options) - set(base),
            {"--experimental-trispeed-ethernet", "--experimental-jtag-bscan=2"})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "not-created"
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                board_release.main(["--output", str(output)])
            actual = json.loads(capture.getvalue())
            self.assertFalse(output.exists())
            self.assertEqual(actual["command"][5:], options)
            self.assertEqual(actual["configuration"], board_release.load_manifest()["export_profile"])
        A = board_profile.load_manifest()["modes"]["B"]["export_profile"]
        B = actual["configuration"]
        self.assertEqual({key for key in A.keys() | B.keys() if A.get(key) != B.get(key)},
            {"name", "experimental_trispeed_ethernet", "tri_speed_tx_frame_slots", "jtag_pins_reserved",
             "jtag_transport_experimental", "jtag_ram_download", "jtag_backend", "bscan_chain"})

    def test_constructor_all_fields_and_drift_fail_closed(self):
        expected = json.loads((board_release.HERE / "board-performance-constructors.json").read_text())["B"]
        with self.assertRaises(RuntimeError):
            board_release.compare_constructor(expected)
        expected["profile"]["readPrefetchDirtyRetry"] = False
        expected["cache"]["readPrefetchDirtyRetry"] = False
        expected["profile"]["readPrefetchDemandAdoption"] = False
        expected["cache"]["readPrefetchDemandAdoption"] = False
        expected["profile"]["registeredPmpRegions"] = False
        expected["core"]["registeredPmpRegions"] = False
        expected["profile"]["publishedPmpChanges"] = False
        expected["core"]["publishedPmpChanges"] = False
        for section in ("profile", "core"):
            expected[section]["frozenStoreProofTransport"] = False
            expected[section]["pendingVirtualStoreProof"] = False
            expected[section]["boundHeadStoreOverlap"] = False
            expected[section]["pendingReadyStoreBypass"] = False
            expected[section]["pendingVirtualStoreProofSlots"] = 1
            expected[section]["pendingStoreEarlyLoadCredits"] = 1
        for section in ("profile", "cache"):
            expected[section]["readPrefetchStoreHold"] = False
            expected[section]["durableReadPrefetchCandidate"] = False
            expected[section]["readPrefetchBehindStore"] = False
        expected["profile"]["experimentalTriSpeedEthernet"] = True
        board_release.compare_constructor(expected)
        for field in ("readPrefetchDirtyRetry", "readPrefetchDemandAdoption"):
            for section in ("profile", "cache"):
                for mutation in ("missing", "enabled"):
                    changed = copy.deepcopy(expected)
                    if mutation == "missing":
                        changed[section].pop(field)
                    else:
                        changed[section][field] = True
                    with self.subTest(section=section, mutation=mutation), self.assertRaises(RuntimeError):
                        board_release.compare_constructor(changed)
        for section in ("profile", "core"):
            for mutation in ("missing", "enabled"):
                changed = copy.deepcopy(expected)
                if mutation == "missing":
                    changed[section].pop("registeredPmpRegions")
                else:
                    changed[section]["registeredPmpRegions"] = True
                with self.subTest(section=section, mutation=mutation), self.assertRaises(RuntimeError):
                    board_release.compare_constructor(changed)
        for section in ("profile", "core"):
            for mutation in ("missing", "enabled"):
                changed = copy.deepcopy(expected)
                if mutation == "missing":
                    changed[section].pop("publishedPmpChanges")
                else:
                    changed[section]["publishedPmpChanges"] = True
                with self.subTest(section=section, mutation=mutation), self.assertRaises(RuntimeError):
                    board_release.compare_constructor(changed)
        for section in ("profile", "core"):
            for mutation in ("missing", "enabled"):
                changed = copy.deepcopy(expected)
                if mutation == "missing":
                    changed[section].pop("boundHeadStoreOverlap")
                else:
                    changed[section]["boundHeadStoreOverlap"] = True
                with self.subTest(section=section, mutation=mutation), self.assertRaises(RuntimeError):
                    board_release.compare_constructor(changed)
        for section, key, value in (("core", "memoryEntries", 2), ("ddr", "futureFlag", False),
                                    ("cache", "splitPrefetchTracking", False)):
            changed = copy.deepcopy(expected)
            changed[section][key] = value
            with self.subTest(section=section), self.assertRaises(RuntimeError):
                board_release.compare_constructor(changed)

    def test_overrides_and_manifest_drift_never_reach_export(self):
        for option in ("--experimental-jtag-bscan=1", "--lsu-entries=2", "--mode=A", "--reference"):
            with self.subTest(option=option), mock.patch.object(exporter, "main") as emit, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    board_release.main(["--output", "/unused", option])
                emit.assert_not_called()
        with mock.patch.object(board_release, "MANIFEST_SHA256", "0" * 64), \
                mock.patch.object(exporter, "main") as emit:
            with self.assertRaises(RuntimeError):
                board_release.main(["--output", "/unused", "--emit"])
            emit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
