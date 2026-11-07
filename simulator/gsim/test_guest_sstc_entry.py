"""Entry orchestration tests only; build and hardware execution are mocked."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class GuestSstcEntryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.msu = "GUEST_SSTC_MSU_PASS cases=1 commands=2 checks=3\n"
        self.core = ("GUEST_SSTC_CORE_PASS schedule=open\n"
                     "GUEST_SSTC_CORE_PASS schedule=stalled\n"
                     "GUEST_SSTC_CORE_ALL_PASS cases=2\n")
        self.codes = {"wrong-compare": 1, "wrong-timer": 1}
        self.diagnostics = {
            "wrong-compare": "FAIL independent guest compare signature",
            "wrong-timer": "FAIL independent guest timer signature",
        }
        self.common = types.ModuleType("run")
        self.common.ROOT = self.root
        self.common.setup = Mock(return_value=("gsim", "clang++-19"))
        self.common.test = Mock(side_effect=self.generate)
        spec = importlib.util.spec_from_file_location(
            "guest_sstc_entry_under_test", Path(__file__).with_name("guest_sstc.py"))
        self.entry = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"run": self.common}):
            spec.loader.exec_module(self.entry)

    def generate(self, gsim, cxx, name, *args, **kwargs):
        output = self.root / "build/gsim" / name
        output.mkdir(parents=True, exist_ok=True)
        (output / "test.log").write_text(self.msu if name.endswith("/msu") else self.core)
        return output

    def negative(self, args, **kwargs):
        mode = args[-1].removeprefix("--")
        kwargs["stdout"].write(self.diagnostics[mode])
        return subprocess.CompletedProcess(args, self.codes[mode])

    def invoke(self):
        with patch.object(sys, "argv", ["guest_sstc.py"]), \
             patch.object(self.entry.subprocess, "run", side_effect=self.negative) as run:
            self.entry.main()
            return run

    def test_fresh_msu_and_core_builds_with_exact_controls(self):
        run = self.invoke()
        self.common.setup.assert_called_once_with(False)
        self.assertEqual(self.common.test.call_count, 2)
        expected = [
            ("guest-sstc/msu", "ooo.HypervisorSystemGsimMain", "HypervisorSystemGsim", "guest_sstc.cpp"),
            ("guest-sstc/core", "ooo.GuestSstcCoreGsimMain", "GuestSstcCoreGsim", "guest_sstc_core.cpp"),
        ]
        for call, names in zip(self.common.test.call_args_list, expected):
            self.assertEqual(call.args, ("gsim", "clang++-19", *names))
            self.assertEqual(call.kwargs, {"defines": {}, "cxx_flags": ("-fbracket-depth=4096",), "timeout": 600})
        self.assertEqual([c.args[0][-1] for c in run.call_args_list], ["--wrong-compare", "--wrong-timer"])
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["cwd"], self.root)
            self.assertEqual(call.kwargs["timeout"], 600)
            self.assertEqual(call.kwargs["env"]["UBSAN_OPTIONS"], "halt_on_error=1")

    def test_setup_failure_stops_build(self):
        self.common.setup.side_effect = RuntimeError("bad binding")
        with self.assertRaisesRegex(RuntimeError, "bad binding"):
            self.invoke()
        self.common.test.assert_not_called()

    def test_build_failure_stops_controls(self):
        self.common.test.side_effect = RuntimeError("build failed")
        with patch.object(self.entry.subprocess, "run") as run:
            with patch.object(sys, "argv", ["guest_sstc.py"]):
                with self.assertRaisesRegex(RuntimeError, "build failed"):
                    self.entry.main()
            run.assert_not_called()

    def test_missing_or_duplicate_msu_summary(self):
        original = self.msu
        for value in ("", original * 2):
            self.msu = value
            with self.assertRaisesRegex(RuntimeError, "one MSU summary"):
                self.invoke()

    def test_nonpositive_or_missing_msu_counts(self):
        for value in ("cases=0 commands=1 checks=1", "cases=1 checks=1", "cases=1 commands=2 checks=-1"):
            self.msu = "GUEST_SSTC_MSU_PASS " + value
            with self.assertRaisesRegex(RuntimeError, "positive cases"):
                self.invoke()

    def test_incomplete_or_duplicate_core_schedules(self):
        for value in ("", "GUEST_SSTC_CORE_PASS schedule=open\n",
                      "GUEST_SSTC_CORE_PASS schedule=open\n" * 2):
            self.core = value + "GUEST_SSTC_CORE_ALL_PASS cases=2\n"
            with self.assertRaisesRegex(RuntimeError, "core summaries"):
                self.invoke()

    def test_missing_or_duplicate_core_completion(self):
        original = self.core
        for value in (original.replace("GUEST_SSTC_CORE_ALL_PASS cases=2", "partial"),
                      original + "GUEST_SSTC_CORE_ALL_PASS cases=2\n"):
            self.core = value
            with self.assertRaisesRegex(RuntimeError, "complete core marker"):
                self.invoke()

    def test_positive_failure_diagnostic_is_rejected(self):
        self.msu += "FAIL incomplete\n"
        with self.assertRaisesRegex(RuntimeError, "failure diagnostic"):
            self.invoke()

    def test_negative_exit_must_be_one(self):
        for mode in self.codes:
            for code in (0, 2, -11):
                self.codes[mode] = code
                with self.assertRaisesRegex(RuntimeError, mode + " returned"):
                    self.invoke()
            self.codes[mode] = 1

    def test_unrelated_or_nonfinal_negative_is_rejected(self):
        for mode in self.diagnostics:
            original = self.diagnostics[mode]
            for value in ("FAIL unrelated", original + "\nlater error"):
                self.diagnostics[mode] = value
                with self.assertRaisesRegex(RuntimeError, "missing from end"):
                    self.invoke()
            self.diagnostics[mode] = original

    def test_sanitizer_failure_is_not_expected_negative(self):
        self.diagnostics["wrong-compare"] = "AddressSanitizer: failed\n" + self.diagnostics["wrong-compare"]
        with self.assertRaisesRegex(RuntimeError, "sanitizer failure"):
            self.invoke()

    def test_help_never_sets_up_tools(self):
        with patch.object(sys, "argv", ["guest_sstc.py", "--help"]):
            with self.assertRaises(SystemExit) as result:
                self.entry.main()
        self.assertEqual(result.exception.code, 0)
        self.common.setup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
