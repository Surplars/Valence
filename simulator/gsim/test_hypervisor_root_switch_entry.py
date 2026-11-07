"""Entry control-flow checks only; compilation and GSIM calls are mocked."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class RootSwitchEntryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "build/gsim/hypervisor-root-switch"
        self.output.mkdir(parents=True)
        self.marker = "HYPERVISOR_ROOT_SWITCH_ALL_PASS cases=2"
        self.summaries = "HYPERVISOR_ROOT_SWITCH_PASS schedule=open\nHYPERVISOR_ROOT_SWITCH_PASS schedule=stalled\n"
        self.codes = {"wrong-fetch": 1, "wrong-data": 1}
        self.diagnostics = {
            "wrong-fetch": "FAIL independent root fetch signature",
            "wrong-data": "FAIL independent root data signature",
        }
        self.common = types.ModuleType("run")
        self.common.ROOT = self.root
        self.common.setup = Mock(return_value=("gsim", "clang++-19"))
        self.common.test = Mock(side_effect=self.generate)
        spec = importlib.util.spec_from_file_location(
            "root_switch_entry_under_test", Path(__file__).with_name("hypervisor_root_switch.py"))
        self.entry = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"run": self.common}):
            spec.loader.exec_module(self.entry)

    def generate(self, *args, **kwargs):
        (self.output / "test.log").write_text(self.summaries + self.marker)
        return self.output

    def negative(self, args, **kwargs):
        mode = args[-1].removeprefix("--")
        kwargs["stdout"].write(self.diagnostics[mode])
        return subprocess.CompletedProcess(args, self.codes[mode])

    def invoke(self):
        with patch.object(sys, "argv", ["hypervisor_root_switch.py"]), \
             patch.object(self.entry.subprocess, "run", side_effect=self.negative) as run:
            self.entry.main()
            return run

    def test_success_uses_one_generation_and_two_exact_controls(self):
        run = self.invoke()
        self.common.setup.assert_called_once_with(False)
        self.common.test.assert_called_once_with(
            "gsim", "clang++-19", "hypervisor-root-switch", "ooo.HypervisorTranslatedCoreGsimMain",
            "HypervisorTranslatedCoreGsim", "hypervisor_root_switch.cpp", defines={},
            cxx_flags=("-fbracket-depth=4096",), timeout=600,
        )
        self.assertEqual([c.args[0][-1] for c in run.call_args_list], ["--wrong-fetch", "--wrong-data"])
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["cwd"], self.root)
            self.assertEqual(call.kwargs["timeout"], 600)
            self.assertEqual(call.kwargs["env"]["UBSAN_OPTIONS"], "halt_on_error=1")

    def test_setup_failure_stops_before_build(self):
        self.common.setup.side_effect = RuntimeError("missing toolchain")
        with self.assertRaisesRegex(RuntimeError, "missing toolchain"):
            self.invoke()
        self.common.test.assert_not_called()

    def test_build_failure_stops_before_controls(self):
        self.common.test.side_effect = RuntimeError("build failed")
        with patch.object(self.entry.subprocess, "run") as run, \
             patch.object(sys, "argv", ["hypervisor_root_switch.py"]):
            with self.assertRaisesRegex(RuntimeError, "build failed"):
                self.entry.main()
            run.assert_not_called()

    def test_missing_positive_marker_is_rejected(self):
        self.marker = "partial result only"
        with self.assertRaisesRegex(RuntimeError, "HYPERVISOR_ROOT_SWITCH_ALL_PASS cases=2 missing"):
            self.invoke()

    def test_duplicate_positive_marker_is_rejected(self):
        self.marker = self.marker + "\n" + self.marker
        with self.assertRaisesRegex(RuntimeError, "missing"):
            self.invoke()

    def test_nonfinal_negative_diagnostic_is_rejected(self):
        self.diagnostics["wrong-fetch"] += "\nFAIL unrelated later"
        with self.assertRaisesRegex(RuntimeError, "missing from end"):
            self.invoke()

    def test_wrong_negative_exit_is_rejected(self):
        for mode in self.codes:
            for code in (0, 2, -11):
                with self.subTest(mode=mode, code=code):
                    self.codes[mode] = code
                    with self.assertRaisesRegex(RuntimeError, mode + " returned"):
                        self.invoke()
            self.codes[mode] = 1

    def test_incomplete_or_duplicate_schedules_are_rejected(self):
        for summaries in ("", "HYPERVISOR_ROOT_SWITCH_PASS schedule=open\n",
                          "HYPERVISOR_ROOT_SWITCH_PASS schedule=open\n" * 2):
            with self.subTest(summaries=summaries):
                self.summaries = summaries
                with self.assertRaisesRegex(RuntimeError, "schedule summaries"):
                    self.invoke()

    def test_unrelated_negative_failure_is_rejected(self):
        for mode in self.diagnostics:
            with self.subTest(mode=mode):
                saved = self.diagnostics[mode]
                self.diagnostics[mode] = "FAIL unrelated"
                with self.assertRaisesRegex(RuntimeError, "missing from"):
                    self.invoke()
                self.diagnostics[mode] = saved

    def test_sanitizer_failure_is_not_an_expected_control(self):
        self.diagnostics["wrong-fetch"] = "AddressSanitizer: fatal\n" + self.diagnostics["wrong-fetch"]
        with self.assertRaisesRegex(RuntimeError, "sanitizer failure"):
            self.invoke()

    def test_help_does_not_setup(self):
        with patch.object(sys, "argv", ["hypervisor_root_switch.py", "--help"]):
            with self.assertRaises(SystemExit) as raised:
                self.entry.main()
        self.assertEqual(raised.exception.code, 0)
        self.common.setup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
