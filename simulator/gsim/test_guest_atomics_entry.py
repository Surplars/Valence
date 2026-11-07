"""Entry orchestration tests, with hardware build and execution explicitly mocked."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class GuestAtomicsEntryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.common = types.ModuleType("run")
        self.common.ROOT = self.root
        self.common.setup = Mock(return_value=("gsim", "clang++-19"))
        self.common.test = Mock(side_effect=self.generate)
        spec = importlib.util.spec_from_file_location(
            "guest_atomics_entry_under_test", Path(__file__).with_name("guest_atomics.py"))
        self.entry = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"run": self.common}):
            spec.loader.exec_module(self.entry)
        self.rows = [f"GUEST_ATOMICS_PASS case={case} schedule={schedule} cycles=3 commits=2 checks=1"
                     for case in self.entry.CASES for schedule in self.entry.SCHEDULES]
        self.marker = f"GUEST_ATOMICS_ALL_PASS cases={len(self.entry.CASES)} runs={len(self.rows)}"
        self.positive = "\n".join(self.rows + [self.marker]) + "\n"
        self.negative_code = 1
        self.negative_log = self.entry.NEGATIVE_DIAGNOSTIC + "\n"

    def generate(self, *args, **kwargs):
        output = self.root / "build/gsim/guest-atomics"
        output.mkdir(parents=True, exist_ok=True)
        (output / "test.log").write_text(self.positive)
        return output

    def negative(self, args, **kwargs):
        kwargs["stdout"].write(self.negative_log)
        return subprocess.CompletedProcess(args, self.negative_code)

    def invoke(self):
        with patch.object(sys, "argv", ["guest_atomics.py"]), \
             patch.object(self.entry.subprocess, "run", side_effect=self.negative) as run:
            self.entry.main()
            return run

    def test_exact_real_entry_and_negative_contract(self):
        run = self.invoke()
        self.common.setup.assert_called_once_with(False)
        self.common.test.assert_called_once_with(
            "gsim", "clang++-19", "guest-atomics", "ooo.GuestAtomicsPlatformGsimMain",
            "GuestAtomicsPlatformGsim", "guest_atomics.cpp", defines={},
            cxx_flags=("-fbracket-depth=4096",), timeout=600)
        self.assertEqual(run.call_count, 1)
        call = run.call_args
        self.assertEqual(call.args[0][-1], "--wrong-atomic")
        self.assertEqual(call.kwargs["cwd"], self.root)
        self.assertEqual(call.kwargs["timeout"], 600)
        self.assertEqual(call.kwargs["env"]["UBSAN_OPTIONS"], "halt_on_error=1")

    def test_setup_failure_prevents_build(self):
        self.common.setup.side_effect = RuntimeError("bad tool binding")
        with self.assertRaisesRegex(RuntimeError, "bad tool binding"):
            self.invoke()
        self.common.test.assert_not_called()

    def test_build_failure_prevents_execution(self):
        self.common.test.side_effect = RuntimeError("build failed")
        with patch.object(self.entry.subprocess, "run") as run:
            with patch.object(sys, "argv", ["guest_atomics.py"]):
                with self.assertRaisesRegex(RuntimeError, "build failed"):
                    self.entry.main()
            run.assert_not_called()

    def test_missing_duplicate_or_unknown_case_is_rejected(self):
        for rows in (self.rows[:-1], self.rows + self.rows[:1],
                     [self.rows[0].replace("case=clean", "case=unknown"), *self.rows[1:]]):
            self.positive = "\n".join(rows + [self.marker])
            with self.assertRaisesRegex(RuntimeError, "every guest atomic case"):
                self.invoke()

    def test_unknown_schedule_is_rejected(self):
        self.positive = self.positive.replace("schedule=1", "schedule=3", 1)
        with self.assertRaisesRegex(RuntimeError, "every guest atomic case"):
            self.invoke()

    def test_nonpositive_or_missing_counts_are_rejected(self):
        original = self.positive
        for before, after in (("cycles=3", "cycles=0"), ("commits=2", "commits=-1"),
                              ("checks=1", "ignored=1")):
            self.positive = original.replace(before, after, 1)
            with self.assertRaisesRegex(RuntimeError, "positive execution counts"):
                self.invoke()

    def test_missing_or_duplicate_completion_is_rejected(self):
        original = self.positive
        for value in (original.replace(self.marker, "partial"), original + self.marker + "\n"):
            self.positive = value
            with self.assertRaisesRegex(RuntimeError, "one complete"):
                self.invoke()

    def test_positive_error_or_sanitizer_diagnostics_are_rejected(self):
        original = self.positive
        for diagnostic in ("FAIL unfinished", "AddressSanitizer: error", "runtime error: invalid"):
            self.positive = original + diagnostic
            with self.assertRaisesRegex(RuntimeError, "failure diagnostic"):
                self.invoke()

    def test_negative_requires_exact_exit(self):
        for code in (0, 2, -11):
            self.negative_code = code
            with self.assertRaisesRegex(RuntimeError, "returned"):
                self.invoke()

    def test_wrong_or_nonfinal_negative_diagnostic_is_rejected(self):
        for value in ("FAIL unrelated", self.entry.NEGATIVE_DIAGNOSTIC + "\nlater error"):
            self.negative_log = value
            with self.assertRaisesRegex(RuntimeError, "missing from end"):
                self.invoke()

    def test_sanitizer_is_not_a_negative_control(self):
        self.negative_log = "AddressSanitizer: error\n" + self.negative_log
        with self.assertRaisesRegex(RuntimeError, "sanitizer failure"):
            self.invoke()

    def test_help_never_sets_up_tools(self):
        with patch.object(sys, "argv", ["guest_atomics.py", "--help"]):
            with self.assertRaises(SystemExit) as result:
                self.entry.main()
        self.assertEqual(result.exception.code, 0)
        self.common.setup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
