"""Host-only rejection tests for lineage launch/evidence binding; no DUT tools."""
import json
import copy
from pathlib import Path
import tempfile
import unittest

import run_lineage as gate


class LauncherTest(unittest.TestCase):
    def test_negative_requires_specific_oracle_not_any_nonzero(self):
        text = gate.EPOCH_CONTROLS + "\n" + gate.CANCEL_CONTROLS + "\nGSIM CPU posted-store lineage: FAIL case=" + gate.CASES[0] + " " + gate.REJECT
        self.assertEqual(gate.outcome(text, 1, "on", gate.CASES[0], "token")["status"],
                         "EXPECTED_ORACLE_REJECTION")
        for log, code in [(text, -6), (text, 0), (text + " AddressSanitizer", 1), ("timeout", 1),
                          (text + gate.PASS, 1), (text.replace(gate.CASES[0], "other"), 1)]:
            with self.subTest(log=log, code=code), self.assertRaises(gate.GateError):
                gate.outcome(log, code, "on", gate.CASES[0], "token")

    def test_normal_requires_coverage(self):
        with self.assertRaises(gate.GateError):
            gate.outcome(gate.PASS, 0, "off", gate.CASES[0])

    def test_actual_census_rejects_silent_off_and_two_lsus(self):
        def sample(enabled, slots=4):
            return "\n".join([
                "  module IntegerBackend :", "    output io : {" + ("posted : {epoch : UInt<32>}" if enabled else "") + "}",
                "  module StoreBuffer :", "    output io : {" + ("upstreamProof : UInt<1>" if enabled else "") + "}",
                "    reg proofs : UInt<1>" if enabled else "",
                "  module DataTranslationAdapter :", "    output io : {" + ("posted : {finalChecked : UInt<1>}" if enabled else "") + "}",
                "    wire passive : {posted : UInt<1>}",
                "  module ParallelLoadStoreUnit :", "    output io : {index : UInt<4>, tag : UInt<64>}",
                *[f"    inst slots_{n} of LoadStoreUnit_{n}" for n in range(slots)]])
        self.assertFalse(gate.census(sample(False), False)["enabled"])
        self.assertTrue(gate.census(sample(True), True)["enabled"])
        for fir, enabled in [(sample(False), True), (sample(True), False), (sample(True, 2), True)]:
            with self.assertRaises(gate.GateError):
                gate.census(fir, enabled)

    def test_trace_rejects_missing_expected_or_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            events = [{"kind": "case_begin", "expected_instructions": 1}, {"kind": "expected"},
                      {"kind": "rename"}, {"kind": "case_pass"}]
            def write(items):
                path.write_text("".join(json.dumps({"case": gate.CASES[0], **e}) + "\n" for e in items))
            write(events)
            self.assertEqual(gate.trace_summary(path, gate.CASES[0])["rename"], 1)
            for subset in (events[:3], [events[0], *events[2:]], events + [{"kind": "failure"}]):
                write(subset)
                with self.assertRaises(gate.GateError):
                    gate.trace_summary(path, gate.CASES[0])

    def test_tool_hash_drift_rejects_before_environment_or_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fake-tool"
            path.write_bytes(b"original")
            receipt = {"files": {name: {"path": str(path), "sha256": gate.sha(path)}
                        for name in ("mill_wrapper", "mill_dist", "gsim", "clang", "firtool")}}
            path.write_bytes(b"changed")
            with self.assertRaisesRegex(gate.GateError, "pinned tool drift"):
                gate.check_tools(receipt)

    def test_model_reuse_allows_only_declared_host_changes(self):
        old = {"source": {"files": {"src/main/scala/Cpu.scala": "rtl", str(gate.RELATIVE): "old"}},
               "tool_receipt": {"files": {"gsim": {"sha256": "tool"}}}}
        new = copy.deepcopy(old)
        new["source"]["files"][str(gate.RELATIVE)] = "new"
        self.assertEqual(gate.reusable_source(old, new), [str(gate.RELATIVE)])
        new["source"]["files"]["src/main/scala/Cpu.scala"] = "different"
        with self.assertRaisesRegex(gate.GateError, "RTL/build/tool"):
            gate.reusable_source(old, new)
        new = copy.deepcopy(old)
        new["tool_receipt"]["files"]["gsim"]["sha256"] = "different"
        with self.assertRaisesRegex(gate.GateError, "tool identity"):
            gate.reusable_source(old, new)


if __name__ == "__main__":
    unittest.main()
