"""Orchestration checks only; every build, model and native execution is mocked."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class DualFsPreparationEntryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.common = types.ModuleType("run")
        self.common.ROOT = self.root
        self.common.setup = Mock(return_value=("gsim", "clang++-19"))
        self.common.test = Mock(side_effect=self.generate)
        spec = importlib.util.spec_from_file_location(
            "dual_fs_entry_under_test", Path(__file__).with_name("dual_fs_preparation.py"))
        self.entry = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"run": self.common}):
            spec.loader.exec_module(self.entry)
        self.row = {**self.entry.EXACT, **self.entry.MINIMUM, "cycles": 3,
                    "evidence": "component_only", "synthetic_results": True, "guest_fd_execution": False}
        self.trace = "".join("DUAL_FS_TRACE " + json.dumps({"cycle": i, "in": {}, "out": {}}) + "\n"
                             for i in range(3))
        self.positive = {
            "dual": self.dual_text(),
            "host": "FP_STATE_PASS cycles=9000 issued=647 retired=600 stale=619 blocked_context=700 "
                    "box_canonicalized=60 illegal=28 flush_send=10 flush_wait=10 flush_done=10 "
                    "reset_boundaries=4 simultaneous_response_flush=1 immediate_forwarding=32x3 "
                    "older_commit_younger_flush=32\n",
        }
        self.negative_logs = {(profile, name): (self.trace if profile == "dual" else "") +
                              diagnostic.replace(r"\[", "[").replace(r"\]", "]") + "\n"
                              for profile, negatives in self.entry.NEGATIVES.items()
                              for name, diagnostic in negatives.items()}
        self.codes = dict.fromkeys(self.negative_logs, 1)

    def dual_text(self, row=None):
        return self.trace + "DUAL_FS_PREPARATION_PASS " + json.dumps(self.row if row is None else row) + "\n"

    def generate(self, gsim, cxx, name, *args, **kwargs):
        profile = name.rsplit("/", 1)[1]
        output = self.root / "build/gsim" / name
        output.mkdir(parents=True, exist_ok=True)
        (output / "test.log").write_text(self.positive[profile])
        return output

    def negative(self, args, **kwargs):
        profile = Path(args[0]).parent.name
        name = args[1].split("=", 1)[1] if profile == "dual" else "inject-mismatch"
        key = (profile, name)
        kwargs["stdout"].write(self.negative_logs[key])
        return subprocess.CompletedProcess(args, self.codes[key])

    def invoke(self):
        with patch.object(sys, "argv", ["dual_fs_preparation.py"]), \
             patch.object(self.entry.subprocess, "run", side_effect=self.negative) as run:
            self.entry.main()
            return run

    def positive_check(self, profile, text):
        path = self.root / "positive.log"
        path.write_text(text)
        return self.entry.check_positive(path, profile)

    def test_two_fresh_models_and_six_named_negatives(self):
        run = self.invoke()
        self.common.setup.assert_called_once_with(False)
        self.assertEqual(self.common.test.call_count, 2)
        for call, (profile, main, model, driver) in zip(self.common.test.call_args_list, self.entry.PROFILES):
            self.assertEqual(call.args, ("gsim", "clang++-19", "dual-fs-preparation/" + profile,
                                         main, model, driver))
            self.assertEqual(call.kwargs, {"cxx_flags": ("-fbracket-depth=4096",), "timeout": 120,
                                          "mill_module": "IonSoC.dualFsPreparation"})
        self.assertEqual(run.call_count, 6)
        self.assertEqual([call.args[0][1] for call in run.call_args_list],
                         ["--negative=" + name for name in self.entry.NEGATIVES["dual"]] + ["--inject-mismatch"])
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["cwd"], self.root)
            self.assertEqual(call.kwargs["timeout"], 120)
            self.assertEqual(call.kwargs["env"]["ASAN_OPTIONS"], "detect_leaks=0")
            self.assertEqual(call.kwargs["env"]["UBSAN_OPTIONS"], "halt_on_error=1")

    def test_binding_failure_prevents_all_builds(self):
        self.common.setup.side_effect = RuntimeError("binding failure")
        with self.assertRaisesRegex(RuntimeError, "binding failure"):
            self.invoke()
        self.common.test.assert_not_called()

    def test_build_failure_prevents_negative_execution(self):
        self.common.test.side_effect = RuntimeError("build failure")
        with patch.object(self.entry.subprocess, "run") as run, patch.object(sys, "argv", ["entry"]):
            with self.assertRaisesRegex(RuntimeError, "build failure"):
                self.entry.main()
        run.assert_not_called()

    def test_every_exact_cardinality_is_required(self):
        for key, value in self.entry.EXACT.items():
            for bad in (value + 1, -1, True, str(value)):
                with self.subTest(key=key, bad=bad), self.assertRaises(RuntimeError):
                    self.positive_check("dual", self.dual_text({**self.row, key: bad}))

    def test_every_boundary_counter_is_required(self):
        for key, minimum in self.entry.MINIMUM.items():
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.positive_check("dual", self.dual_text({**self.row, key: minimum - 1}))

    def test_component_scope_must_remain_explicit(self):
        for key, bad in (("evidence", "guest_core"), ("synthetic_results", 1), ("guest_fd_execution", 0),
                         ("synthetic_results", False), ("guest_fd_execution", True)):
            with self.subTest(key=key, bad=bad), self.assertRaises(RuntimeError):
                self.positive_check("dual", self.dual_text({**self.row, key: bad}))

    def test_raw_trace_is_complete_ordered_and_bounded(self):
        original = self.positive["dual"]
        for text in (original.replace(self.trace, ""), original.replace('"cycle": 1', '"cycle": 0'),
                     original.replace('"in": {}', '"in": 0', 1),
                     original.replace('"cycles": 3', '"cycles": 20001')):
            with self.assertRaises(RuntimeError):
                self.positive_check("dual", text)

    def test_missing_duplicate_malformed_and_nonfinal_summaries(self):
        for profile, original in self.positive.items():
            marker = original.splitlines()[-1]
            for text in (original.replace(marker, "partial"), original + marker + "\n", original + "after\n"):
                with self.subTest(profile=profile), self.assertRaises(RuntimeError):
                    self.positive_check(profile, text)
        with self.assertRaises(RuntimeError):
            self.positive_check("dual", self.positive["dual"].replace('"schema": 1', '"schema": 1, "schema": 1'))
        with self.assertRaises(RuntimeError):
            self.positive_check("host", self.positive["host"].replace("cycles=9000", "cycles=9000 cycles=9000"))

    def test_host_coverage_is_not_optional(self):
        for old, bad in (("issued=647", "issued=450"), ("retired=600", "retired=0"),
                         ("stale=619", "stale=no"), ("blocked_context=700", "blocked_context=-1"),
                         ("illegal=28", "illegal=27"), ("reset_boundaries=4", "reset_boundaries=0"),
                         ("immediate_forwarding=32x3", "immediate_forwarding=1x1"),
                         ("flush_send=10", "flush_send=5")):
            with self.subTest(old=old), self.assertRaises(RuntimeError):
                self.positive_check("host", self.positive["host"].replace(old, bad))

    def test_positive_failures_sanitizers_and_control_bytes_rejected(self):
        for profile, original in self.positive.items():
            for prefix in ("DUAL_FS_CHECK[bad]", "FP oracle mismatch:", "FAIL bad", "AddressSanitizer", "runtime error:", "\x00"):
                with self.subTest(profile=profile, prefix=prefix), self.assertRaises(RuntimeError):
                    self.positive_check(profile, prefix + "\n" + original)

    def test_negative_requires_exact_exit_one(self):
        key = ("dual", "host-permission")
        for code in (0, 2, -11):
            self.codes[key] = code
            with self.assertRaisesRegex(RuntimeError, "exit exactly one"):
                self.invoke()

    def test_negative_requires_named_final_failure_and_trace(self):
        key = ("dual", "host-permission")
        original = self.negative_logs[key]
        for text in (original.replace(self.trace, ""), self.trace + "unrelated failure\n", original + "after\n"):
            self.negative_logs[key] = text
            with self.assertRaises(RuntimeError):
                self.invoke()

    def test_negative_rejects_pass_sanitizer_and_control_bytes(self):
        key = ("dual", "host-permission")
        original = self.negative_logs[key]
        for prefix in ("DUAL_FS_PREPARATION_PASS", "FP_STATE_PASS", "AddressSanitizer", "runtime error:", "\x01"):
            self.negative_logs[key] = prefix + "\n" + original
            with self.assertRaises(RuntimeError):
                self.invoke()

    def test_help_and_unknown_options_do_not_start_hardware(self):
        for arg, code in (("--help", 0), ("--reuse-unverified", 2)):
            with patch.object(sys, "argv", ["entry", arg]), self.assertRaises(SystemExit) as caught:
                self.entry.main()
            self.assertEqual(caught.exception.code, code)
        self.common.setup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
