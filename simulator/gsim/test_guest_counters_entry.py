"""Orchestration tests only; all hardware generation and execution are mocked."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class GuestCountersEntryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.common = types.ModuleType("run")
        self.common.ROOT = self.root
        self.common.setup = Mock(return_value=("gsim", "clang++-19"))
        self.common.test = Mock(side_effect=self.generate)
        spec = importlib.util.spec_from_file_location(
            "guest_counters_entry_under_test", Path(__file__).with_name("guest_counters.py"))
        self.entry = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"run": self.common}):
            spec.loader.exec_module(self.entry)
        self.positive = {"bank": self.line("BASIC_COUNTER_BANK_PASS", edges=56, checks=165, **self.entry.BANK_COVERAGE)}
        for profile in ("system", "absent"):
            present = profile == "system"
            counts = {"permission_cases": 80, "permission_cy": 40, "permission_ir": 40,
                      **{"permission_" + mode: 16 for mode in ("M", "HS", "U", "VS", "VU")},
                      **{"permission_mask" + str(mask): 10 for mask in range(8)}}
            counts = {key: value if present else 0 for key, value in counts.items()}
            self.positive[profile] = self.line(self.entry.MARKERS[profile], commands=1000, edges=20000,
                                              checks=100000, absence_cases=0 if present else 23, **counts)
        self.positive["platform"] = "".join(
            self.line("GUEST_COUNTERS_PLATFORM_PASS", case=case, schedule=schedule, cycles=3000,
                      activeCycles=1976, commits=150, checks=10000, dual=2, commitHolds=777,
                      compressed=11, writeHolds=1, traps=traps, cycle=100, instret=500,
                      inhibit=0, terminalFetchOwners=1, accepted=f"{traps},100", returned=f"{traps},99")
            for case, traps in self.entry.CASE_TRAPS.items() for schedule in (1, 2)
        ) + "GUEST_COUNTERS_ALL_PASS cases=4 runs=8\n"
        self.negative_logs = {(profile, name): diagnostic.replace("[0-9]+", "9") + "\n"
                              for profile, negatives in self.entry.NEGATIVES.items()
                              for name, diagnostic in negatives.items()}
        self.codes = dict.fromkeys(self.negative_logs, 1)

    @staticmethod
    def line(marker, **fields):
        return marker + " " + " ".join(f"{key}={value}" for key, value in fields.items()) + "\n"

    def generate(self, gsim, cxx, name, *args, **kwargs):
        profile = name.rsplit("/", 1)[1]
        output = self.root / "build/gsim" / name
        output.mkdir(parents=True, exist_ok=True)
        (output / "test.log").write_text(self.positive[profile])
        return output

    def negative(self, args, **kwargs):
        key = (Path(args[0]).parent.name, args[1].split("=", 1)[1])
        kwargs["stdout"].write(self.negative_logs[key])
        return subprocess.CompletedProcess(args, self.codes[key])

    def invoke(self):
        with patch.object(sys, "argv", ["guest_counters.py"]), \
             patch.object(self.entry.subprocess, "run", side_effect=self.negative) as run:
            self.entry.main()
            return run

    def check_direct(self, profile, text):
        path = self.root / "direct.log"
        path.write_text(text)
        self.entry.check_positive(path, profile)

    def test_exact_four_models_and_fourteen_named_negatives(self):
        run = self.invoke()
        self.common.setup.assert_called_once_with(False)
        self.assertEqual(self.common.test.call_count, 4)
        for call, (profile, model, driver, defines) in zip(self.common.test.call_args_list, self.entry.PROFILES):
            self.assertEqual(call.args, ("gsim", "clang++-19", "guest-counters/" + profile,
                                        "ooo." + model + "Main", model, driver))
            self.assertEqual(call.kwargs, {"defines": defines, "cxx_flags": ("-fbracket-depth=4096",),
                                          "timeout": 600, "mill_module": "IonSoC.guestCounters"})
        self.assertEqual(run.call_count, 14)
        keys = [(Path(call.args[0][0]).parent.name, call.args[0][1].split("=", 1)[1]) for call in run.call_args_list]
        self.assertEqual(set(keys), set(self.negative_logs))
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["cwd"], self.root)
            self.assertEqual(call.kwargs["timeout"], 600)
            self.assertEqual(call.kwargs["env"]["UBSAN_OPTIONS"], "halt_on_error=1")

    def test_failed_binding_prevents_build(self):
        self.common.setup.side_effect = RuntimeError("binding failed")
        with self.assertRaisesRegex(RuntimeError, "binding failed"):
            self.invoke()
        self.common.test.assert_not_called()

    def test_failed_build_prevents_negatives(self):
        self.common.test.side_effect = RuntimeError("build failed")
        with patch.object(self.entry.subprocess, "run") as run, patch.object(sys, "argv", ["guest_counters.py"]):
            with self.assertRaisesRegex(RuntimeError, "build failed"):
                self.entry.main()
            run.assert_not_called()

    def test_bank_requires_every_exact_coverage_witness(self):
        original = self.positive["bank"]
        for key, value in {**self.entry.BANK_COVERAGE, "edges": 56, "checks": 165}.items():
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.check_direct("bank", original.replace(f"{key}={value}", f"{key}={value + 1}"))

    def test_system_and_absent_matrix_cannot_be_partial(self):
        for profile in ("system", "absent"):
            original = self.positive[profile]
            for key in ("permission_cases", "permission_cy", "permission_ir", "permission_M", "permission_HS",
                        "permission_U", "permission_VS", "permission_VU", "permission_mask0", "permission_mask7", "absence_cases"):
                field = next(part for part in original.split() if part.startswith(key + "="))
                with self.subTest(profile=profile, key=key), self.assertRaises(RuntimeError):
                    self.check_direct(profile, original.replace(field, key + "=999"))

    def test_platform_requires_exact_unique_matrix(self):
        original = self.positive["platform"]
        lines = original.splitlines()
        for text in ("\n".join(lines[1:]), original + lines[0] + "\n",
                     original.replace("case=vs ", "case=unknown ", 1),
                     original.replace("schedule=1", "schedule=3", 1)):
            with self.assertRaisesRegex(RuntimeError, "every counter platform"):
                self.check_direct("platform", text)

    def test_platform_rejects_false_execution_proofs(self):
        original = self.positive["platform"]
        for old, new in (("cycles=3000", "cycles=0"), ("commits=150", "commits=-1"),
                         ("checks=10000", "checks=no"), ("dual=2", "dual=0"),
                         ("commitHolds=777", "commitHolds=0"), ("compressed=11", "compressed=9"),
                         ("writeHolds=1", "writeHolds=2"), ("traps=3", "traps=4"),
                         ("activeCycles=1976", "activeCycles=4000"), ("inhibit=0", "inhibit=2")):
            with self.subTest(old=old), self.assertRaises(RuntimeError):
                self.check_direct("platform", original.replace(old, new, 1))

    def test_platform_requires_balanced_physical_owners(self):
        original = self.positive["platform"]
        for old, new in (("accepted=3,100", "accepted=3"), ("returned=3,99", "returned=2,99"),
                         ("accepted=3,100", "accepted=3,98"), ("terminalFetchOwners=1", "terminalFetchOwners=0"),
                         ("returned=3,99", "returned=3,0")):
            with self.assertRaises(RuntimeError):
                self.check_direct("platform", original.replace(old, new, 1))

    def test_missing_or_duplicate_complete_markers(self):
        for profile, original in self.positive.items():
            marker = original.splitlines()[-1]
            for text in (original.replace(marker, "partial"), original + marker + "\n"):
                with self.subTest(profile=profile), self.assertRaises(RuntimeError):
                    self.check_direct(profile, text)

    def test_missing_duplicate_or_malformed_summary_fields(self):
        original = self.positive["bank"]
        for text in (original.replace("edges=56", "missing=56"), original.replace("edges=56", "edges=56 edges=56"),
                     original.replace("edges=56", "malformed"), original.replace("checks=165", "checks=0")):
            with self.assertRaises(RuntimeError):
                self.check_direct("bank", text)

    def test_nontext_failure_and_sanitizer_positive_logs_rejected(self):
        for profile, original in self.positive.items():
            for suffix in ("\x00", "\x01", "FAIL unexpected", "AddressSanitizer", "runtime error:"):
                with self.subTest(profile=profile, suffix=suffix), self.assertRaises(RuntimeError):
                    self.check_direct(profile, original + suffix)

    def test_negative_requires_exact_exit_one(self):
        key = ("bank", "cycle")
        for code in (0, 2, -11):
            self.codes[key] = code
            with self.assertRaisesRegex(RuntimeError, "exit exactly one"):
                self.invoke()

    def test_negative_requires_specific_final_diagnostic(self):
        key = ("bank", "cycle")
        for text in ("BASIC_COUNTER_BANK_FAIL instret edge oracle edge=9\n", "unrelated failure\n",
                     "BASIC_COUNTER_BANK_FAIL cycle edge oracle edge=9\nmore output\n"):
            self.negative_logs[key] = text
            with self.assertRaisesRegex(RuntimeError, "named independent oracle"):
                self.invoke()

    def test_negative_rejects_success_sanitizer_and_control_bytes(self):
        key = ("bank", "cycle")
        original = self.negative_logs[key]
        for prefix in ("BASIC_COUNTER_BANK_PASS ", "GUEST_COUNTERS_ALL_PASS ", "AddressSanitizer ", "runtime error: ", "\x00"):
            self.negative_logs[key] = prefix + "\n" + original
            with self.assertRaises(RuntimeError):
                self.invoke()

    def test_help_and_unknown_flags_do_not_start_hardware(self):
        for arg, code in (("--help", 0), ("--reuse-unverified", 2)):
            with patch.object(sys, "argv", ["guest_counters.py", arg]), self.assertRaises(SystemExit) as caught:
                self.entry.main()
            self.assertEqual(caught.exception.code, code)
        self.common.setup.assert_not_called()

    def test_shared_builder_keeps_default_and_selects_explicit_source_module(self):
        spec = importlib.util.spec_from_file_location(
            "guest_counters_real_builder_under_test", Path(__file__).with_name("run.py"))
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)

        def fake_run(args, **kwargs):
            if kwargs.get("log"):
                kwargs["log"].write_text("")

        for explicit in (False, True):
            with patch.object(builder, "BUILD", self.root / "builder"), \
                 patch.object(builder, "run", side_effect=fake_run) as run:
                args = {"mill_module": "IonSoC.guestCounters"} if explicit else {}
                builder.test("gsim", "clang++", "mocked", "ooo.TestMain", "Test", "test.cpp", **args)
                commands = [call.args[0] for call in run.call_args_list]
                self.assertEqual(commands[0][0:3], ["mill", "-i", "IonSoC.guestCounters.runMain" if explicit else "IonSoC.test.runMain"])
                self.assertEqual(commands[1][0:2], ["gsim", "--threads=1"])
                self.assertIn("-fsanitize=address,undefined", commands[2])
                self.assertIn("-fno-sanitize-recover=all", commands[2])
                self.assertEqual(run.call_count, 4)


if __name__ == "__main__":
    unittest.main()
