"""Same-capacity A/B argument selection and complete-constructor drift gates."""
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
import export as exporter
import performance


class BoardProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "not-created"
        self.manifest = board_profile.load_manifest()

    def preflight(self, mode, entry=board_profile.main):
        stream = io.StringIO()
        args = ["--output", str(self.output)]
        if entry is board_profile.main:
            args += ["--mode", mode]
        with contextlib.redirect_stdout(stream):
            entry(args)
        self.assertFalse(self.output.exists())
        return json.loads(stream.getvalue())

    def test_A_is_exact_unchanged_v3_and_both_expand_shared_arguments(self):
        self.assertEqual(self.preflight("A"), self.preflight("A", performance.main))
        for mode in ("A", "B"):
            result = self.preflight(mode)
            self.assertEqual(result["command"][5:], board_profile.native_options(mode))
            self.assertEqual(result["configuration"], self.manifest["modes"][mode]["export_profile"])
            for field, value in self.manifest["fixed_configuration"].items():
                self.assertEqual(result["configuration"][field], value, field)

    def test_B_changes_only_the_eight_reviewed_settings(self):
        A = self.preflight("A")["configuration"]
        B = self.preflight("B")["configuration"]
        changed = {key for key in A.keys() | B.keys() if key != "name" and A.get(key, False) != B.get(key, False)}
        self.assertEqual(changed, set(self.manifest["treatment_fields"]))
        self.assertEqual((A["prefetch_candidate_cycles"], B["prefetch_candidate_cycles"]), (1, 16))
        for field in changed - {"prefetch_candidate_cycles"}:
            self.assertFalse(A.get(field, False))
            self.assertIs(B[field], True)

    def test_complete_constructor_extra_missing_and_changed_fields_fail(self):
        frozen = json.loads((board_profile.HERE / "board-performance-constructors.json").read_text())
        for mode in ("A", "B"):
            board_profile.compare_constructor(mode, frozen[mode])
            for mutation in ("change", "missing", "extra"):
                actual = copy.deepcopy(frozen[mode])
                if mutation == "change":
                    actual["core"]["memoryEntries"] = 2
                elif mutation == "missing":
                    actual["cache"].pop("splitPrefetchTracking")
                else:
                    actual["core"]["futureOption"] = False
                with self.subTest(mode=mode, mutation=mutation), self.assertRaises(RuntimeError):
                    board_profile.compare_constructor(mode, actual)

    def test_manifest_drift_and_cli_overrides_fail_before_emit(self):
        with mock.patch.object(board_profile, "MANIFEST_SHA256", "0" * 64), \
                mock.patch.object(exporter, "main") as emit:
            with self.assertRaises(RuntimeError):
                board_profile.main(["--output", str(self.output), "--emit"])
            emit.assert_not_called()
        for option in ("--lsu-entries=2", "--experimental-trispeed-ethernet", "--experimental-jtag-bscan=1",
                       "--translated-response-empty-flow", "--mod", "--reference"):
            with self.subTest(option=option), mock.patch.object(exporter, "main") as emit, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    board_profile.main(["--output", str(self.output), option])
                emit.assert_not_called()

    def test_native_option_api_requires_valid_mode_and_explicit_selector(self):
        with self.assertRaises(ValueError):
            board_profile.native_options("unknown")
        for mode in ("A", "B"):
            options = board_profile.native_options(mode)
            self.assertEqual(len(options), len(set(options)))
            self.assertEqual(options[0], "--selected")
            self.assertNotIn("--experimental-trispeed-ethernet", options)
            self.assertFalse(any("jtag" in option for option in options))


if __name__ == "__main__":
    unittest.main()
