"""No CAD/simulation: strict rejection checks for the RV64GC evidence auditor."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("audit", Path(__file__).with_name("audit-rv64gc-evidence.py"))
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class EvidenceTests(unittest.TestCase):
    def test_only_exact_metadata_correction_allowed(self):
        old = b"prefix " + AUDIT.OLD_LIMIT + b" suffix"
        new = old.replace(AUDIT.OLD_LIMIT, AUDIT.NEW_LIMIT)
        self.assertTrue(AUDIT.metadata_only(old, new))
        self.assertFalse(AUDIT.metadata_only(old, new + b"# changed test"))
        self.assertFalse(AUDIT.metadata_only(old, old))
        self.assertFalse(AUDIT.metadata_only(old + old, new + new))

    def test_routed_10ns_report_required(self):
        text = ("| Design            : MachineCore\n| Design State      : Routed\n"
                "xczu15eg-ffvb1156 -2  PRODUCTION\n"
                "module_clock  {0.000 5.000}  10.000  100.000\n"
                "checking no_clock (0)\nchecking unconstrained_internal_endpoints (0)\n"
                "checking loops (0)\nchecking latch_loops (0)\n"
                "| Design Timing Summary\n"
                "1.603 0.000 0 13977 -0.080 -23.169 485 13977 4.725 0.000 0 6127\n"
                "| Clock Summary\n")
        AUDIT.check_core_report(text)
        self.assertEqual(AUDIT.check_core_report(text)["whs_ns"], -0.080)
        self.assertEqual(AUDIT.check_core_report(text)["pulse_failures"], 0)
        for before, after in (("Routed", "Placed"), ("10.000", "20.000"),
                              ("-2  PRODUCTION", "-1  PRODUCTION"),
                              ("checking no_clock (0)", "checking no_clock (1)"),
                              ("unconstrained_internal_endpoints (0)", "unconstrained_internal_endpoints (1)"),
                              ("MachineCore", "MeasurementWrapper"),
                              ("| Design Timing Summary", "| Summary missing")):
            with self.subTest(after=after), self.assertRaises(RuntimeError):
                AUDIT.check_core_report(text.replace(before, after))

    def test_missing_or_weak_controls_rejected(self):
        with self.assertRaises(RuntimeError):
            AUDIT.check_controls([])
        tests = ("numerical-fd", "numerical-f", "numerical-small", "compressed", "cpu",
                 "memory-direct", "memory-buffered", "integer-disabled", "integer-enabled")
        positive = [{"test": name, "exit": 0, "log": "PASS misa_gc=1"} for name in tests]
        reasons = {"numerical-fd": "FP full mismatch: SoftFloat value",
                   "numerical-f": "FP full mismatch: SoftFloat value",
                   "numerical-small": "FP full mismatch: SoftFloat value",
                   "cpu": "FP full CPU mismatch: independent integer result",
                   "integer-disabled": "commit data/nextPC", "integer-enabled": "commit data/nextPC"}
        for mode in ("direct", "buffered"):
            for flag, reason in (("--inject-mismatch", "FP CPU mismatch: commit value/metadata"),
                                 ("--inject-fp-memory", "FP CPU mismatch: FP architectural RF"),
                                 ("--inject-memory-request", "FP CPU mismatch: FP memory request payload")):
                reasons["memory-" + mode + flag] = reason
        negative = [{"negative": name, "exit": 1, "reason": reason} for name, reason in reasons.items()]
        AUDIT.check_controls(positive + negative)
        for field, value in (("exit", 0), ("reason", "unrelated crash")):
            weak = [{**row} for row in negative]
            weak[0][field] = value
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                AUDIT.check_controls(positive + weak)
        cpu_missing = [{**row, "log": "PASS"} for row in positive]
        with self.assertRaises(RuntimeError):
            AUDIT.check_controls(cpu_missing + negative)

    def test_resource_regressions_are_preserved(self):
        before = {"paths": {key: {"slack_ns": 1} for key in
                              ("internal_max", "internal_min", "all_max", "all_min")},
                  "resources": {"lut": 100, "ff": 10, "dsp": 2}}
        after = {**before, "resources": {"lut": 120, "ff": 10, "dsp": 2}}
        result = AUDIT.compare({"modules": {"X": before}}, {"modules": {"X": after}})
        self.assertEqual(result["X"]["resources"]["delta"], {"lut": 20, "ff": 0, "dsp": 0})
        self.assertEqual(result["X"]["boundary_hold"]["before"], {"slack_ns": 1})


if __name__ == "__main__":
    unittest.main()
