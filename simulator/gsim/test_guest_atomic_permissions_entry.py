"""Orchestration-only tests. Hardware generation and execution are explicitly mocked."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class GuestAtomicPermissionsEntryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.common = types.ModuleType("run")
        self.common.ROOT = self.root
        self.common.setup = Mock(return_value=("gsim", "clang++-19"))
        self.common.test = Mock(side_effect=self.generate)
        spec = importlib.util.spec_from_file_location(
            "guest_atomic_permissions_entry_under_test", Path(__file__).with_name("guest_atomic_permissions.py"))
        self.entry = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"run": self.common}):
            spec.loader.exec_module(self.entry)
        self.positive = {}
        for profile, _, _ in self.entry.PROFILES:
            rows = [f"GUEST_ATOMIC_PERMISSIONS_PASS profile={profile} case={case} schedule={schedule} "
                    f"cycles=3 commits=2 checks=1 readbacks={3 if profile == 'pmp' and case.startswith('lr_') else 5} "
                    f"traps=1 atomicRequests=0 ptes=2 parcels=1 clears=1 forbiddenOffers=0 "
                    f"dataTranslationsBeforeTrap={1 if profile == 'pmp' else 0} "
                    f"dataPteOffersBeforeTrap={2 if profile == 'pmp' else 0}"
                    for case in self.entry.CASES for schedule in self.entry.SCHEDULES]
            rows.append(f"GUEST_ATOMIC_PERMISSIONS_ALL_PASS profile={profile} cases=6 runs=12")
            self.positive[profile] = "\n".join(rows) + "\n"
        self.codes = {p: 1 for p in self.positive}
        self.negative_logs = {p: self.entry.NEGATIVE_DIAGNOSTIC + "\n" for p in self.positive}

    def generate(self, gsim, cxx, name, *args, **kwargs):
        profile = name.rsplit("/", 1)[1]
        output = self.root / "build/gsim" / name
        output.mkdir(parents=True, exist_ok=True)
        (output / "test.log").write_text(self.positive[profile])
        return output

    def negative(self, args, **kwargs):
        profile = Path(args[0]).parent.name
        kwargs["stdout"].write(self.negative_logs[profile])
        return subprocess.CompletedProcess(args, self.codes[profile])

    def invoke(self):
        with patch.object(sys, "argv", ["guest_atomic_permissions.py"]), \
             patch.object(self.entry.subprocess, "run", side_effect=self.negative) as run:
            self.entry.main()
            return run

    def test_exact_two_profiles_and_negative_contract(self):
        run = self.invoke()
        self.common.setup.assert_called_once_with(False)
        self.assertEqual(self.common.test.call_count, 2)
        for call, (profile, model, defines) in zip(self.common.test.call_args_list, self.entry.PROFILES):
            self.assertEqual(call.args, ("gsim", "clang++-19", "guest-atomic-permissions/" + profile,
                                        "ooo." + model + "Main", model, "guest_atomic_permissions.cpp"))
            self.assertEqual(call.kwargs, {"defines": defines, "cxx_flags": ("-fbracket-depth=4096",), "timeout": 600})
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.args[0][-1], "--wrong-cause")
            self.assertEqual(call.kwargs["cwd"], self.root)
            self.assertEqual(call.kwargs["timeout"], 600)
            self.assertEqual(call.kwargs["env"]["UBSAN_OPTIONS"], "halt_on_error=1")

    def test_setup_failure_stops_build(self):
        self.common.setup.side_effect = RuntimeError("bad binding")
        with self.assertRaisesRegex(RuntimeError, "bad binding"):
            self.invoke()
        self.common.test.assert_not_called()

    def test_build_failure_stops_execution(self):
        self.common.test.side_effect = RuntimeError("build failure")
        with patch.object(self.entry.subprocess, "run") as run:
            with patch.object(sys, "argv", ["guest_atomic_permissions.py"]):
                with self.assertRaisesRegex(RuntimeError, "build failure"):
                    self.entry.main()
            run.assert_not_called()

    def test_incomplete_duplicate_unknown_matrix_is_rejected(self):
        original = self.positive["pmp"]
        lines = original.splitlines()
        for value in ("\n".join(lines[1:]), original + lines[0] + "\n",
                      original.replace("case=lr_w", "case=unknown", 1),
                      original.replace("schedule=1", "schedule=3", 1),
                      original.replace("profile=pmp", "profile=a_off", 1)):
            self.positive["pmp"] = value
            with self.assertRaisesRegex(RuntimeError, "every profile case"):
                self.invoke()

    def test_invalid_execution_counts_are_rejected(self):
        original = self.positive["pmp"]
        for before, after in (("cycles=3", "cycles=0"), ("commits=2", "commits=-1"),
                              ("checks=1", "ignored=1"), ("readbacks=3", "readbacks=0")):
            self.positive["pmp"] = original.replace(before, after, 1)
            with self.assertRaisesRegex(RuntimeError, "positive execution counts"):
                self.invoke()

    def test_wrong_trap_or_physical_atomic_count_is_rejected(self):
        original = self.positive["pmp"]
        for before, after in (("traps=1", "traps=0"), ("traps=1", "traps=2"),
                              ("atomicRequests=0", "atomicRequests=1")):
            self.positive["pmp"] = original.replace(before, after, 1)
            with self.assertRaisesRegex(RuntimeError, "one trap and zero"):
                self.invoke()

    def test_missing_or_wrong_permission_proof_counts_are_rejected(self):
        originals = self.positive.copy()
        for profile, before, after in (
            ("pmp", "forbiddenOffers=0", "forbiddenOffers=1"),
            ("pmp", "clears=1", "ignored=1"),
            ("pmp", "readbacks=3", "readbacks=5"),
            ("pmp", "dataTranslationsBeforeTrap=1", "dataTranslationsBeforeTrap=0"),
            ("pmp", "dataPteOffersBeforeTrap=2", "ignored=2"),
            ("a_off", "dataTranslationsBeforeTrap=0", "dataTranslationsBeforeTrap=1"),
            ("a_off", "dataPteOffersBeforeTrap=0", "dataPteOffersBeforeTrap=1"),
        ):
            self.positive = originals.copy()
            self.positive[profile] = originals[profile].replace(before, after, 1)
            with self.assertRaisesRegex(RuntimeError, "permission proof"):
                self.invoke()

    def test_missing_or_duplicate_completion_is_rejected(self):
        original = self.positive["a_off"]
        marker = original.splitlines()[-1]
        for value in (original.replace(marker, "partial"), original + marker + "\n"):
            self.positive["a_off"] = value
            with self.assertRaisesRegex(RuntimeError, "one complete"):
                self.invoke()

    def test_positive_failure_or_sanitizer_is_rejected(self):
        original = self.positive["pmp"]
        for diagnostic in ("FAIL incomplete", "AddressSanitizer", "runtime error:"):
            self.positive["pmp"] = original + diagnostic
            with self.assertRaisesRegex(RuntimeError, "failure diagnostic"):
                self.invoke()

    def test_negative_exit_must_be_one_in_both_profiles(self):
        for profile in self.codes:
            for code in (0, 2, -11):
                self.codes[profile] = code
                with self.assertRaisesRegex(RuntimeError, profile + " wrong-cause returned"):
                    self.invoke()
            self.codes[profile] = 1

    def test_unrelated_or_nonfinal_negative_is_rejected(self):
        for profile in self.negative_logs:
            original = self.negative_logs[profile]
            for value in ("FAIL unrelated", original + "later error"):
                self.negative_logs[profile] = value
                with self.assertRaisesRegex(RuntimeError, "missing from end"):
                    self.invoke()
            self.negative_logs[profile] = original

    def test_sanitizer_failure_is_not_expected_negative(self):
        self.negative_logs["a_off"] = "AddressSanitizer\n" + self.negative_logs["a_off"]
        with self.assertRaisesRegex(RuntimeError, "sanitizer failure"):
            self.invoke()

    def test_help_never_sets_up_tools(self):
        with patch.object(sys, "argv", ["guest_atomic_permissions.py", "--help"]):
            with self.assertRaises(SystemExit) as result:
                self.entry.main()
        self.assertEqual(result.exception.code, 0)
        self.common.setup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
