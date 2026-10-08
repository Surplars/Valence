import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("qualification", Path(__file__).with_name("qualification.py"))
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, content in {"module.scala": "RTL", "positive.log": "ORACLE_PASS", "negative.log": "owner mismatch",
                              "baseline.json": "{\"status\":\"PASS\"}"}.items():
            (self.root / name).write_text(content)
        self.e = {
            "schema": q.SCHEMA, "module": "test-module", "change_kind": "optimization",
            "candidate_sources": {"module.scala": q.sha(self.root / "module.scala")},
            "required_sources": ["module.scala"],
            "artifacts": {n: q.sha(self.root / n) for n in ("positive.log", "negative.log", "baseline.json")},
            "baseline": {"source_commit": "a" * 40, "status": "PASS", "receipt": "baseline.json"},
            "tests": [
                {"name": "oracle", "kind": "positive", "independent_oracle": True,
                 "command": ["run"], "log": "positive.log", "expected_exit": 0, "actual_exit": 0,
                 "required_anchors": ["ORACLE_PASS"]},
                {"name": "mutation", "kind": "negative", "command": ["run", "--corrupt-owner"],
                 "log": "negative.log", "expected_exit": 1, "actual_exit": 1, "rejection_anchor": "owner mismatch"}
            ],
            "storage_topology": [{"name": "bank", "width_bits": 64, "depth": 16, "read_ports": 2,
                "write_ports": 1, "read_latency_cycles": 0, "collision_policy": "new-data-bypass"}],
            "performance": [{"name": "latency", "unit": "cycles", "baseline": 3, "candidate": 3, "direction": "equal", "evidence": "positive.log"}]
        }

    def result(self):
        return q.validate(self.e, self.root, self.root)

    def rejected(self, fragment):
        result = self.result()
        self.assertFalse(result["experimental_integration_eligible"])
        self.assertTrue(any(fragment in e for e in result["errors"]), result)

    def test_snapshot_binds_blackbox_and_explicit_native_inputs(self):
        files = {"build.mill": "build", ".mill-version": "version",
                 "src/main/scala/Top.scala": "top", "src/main/resources/debug/transport.sv": "transport",
                 "fpga/next/board.sv": "board", "fpga/next/clock.xdc": "clock"}
        for name, content in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        selected = ["fpga/next/board.sv", "fpga/next/clock.xdc"]
        before = q.snapshot(self.root, selected)
        self.assertIn("src/main/resources/debug/transport.sv", before)
        self.assertTrue(set(selected) <= set(before))
        (self.root / "src/main/resources/debug/transport.sv").write_text("changed transport")
        self.assertNotEqual(before, q.snapshot(self.root, selected))
        with self.assertRaisesRegex(ValueError, "missing evidence"):
            q.snapshot(self.root, ["fpga/next/absent.sv"])

    def test_valid_functional_is_not_physical_signoff(self):
        result = self.result()
        self.assertTrue(result["experimental_integration_eligible"])
        self.assertFalse(result["source_matched_routed_result"])
        self.assertEqual(result["status"], "FUNCTIONAL_CANDIDATE_PHYSICAL_PENDING")

    def test_source_drift_rejected(self):
        (self.root / "module.scala").write_text("changed RTL")
        self.rejected("changed evidence")

    def test_artifact_drift_rejected(self):
        (self.root / "negative.log").write_text("everything passed")
        self.rejected("changed evidence")

    def test_absent_required_source_rejected(self):
        self.e["required_sources"].append("other.scala")
        self.rejected("incomplete")

    def test_false_negative_and_missing_anchor_rejected(self):
        self.e["tests"][1]["expected_exit"] = 0
        self.e["tests"][1]["actual_exit"] = 0
        self.rejected("intended rejection")
        self.e["tests"][1]["expected_exit"] = 1
        self.e["tests"][1]["actual_exit"] = 1
        self.e["tests"][1]["rejection_anchor"] = "different failure"
        self.rejected("anchor absent")

    def test_no_independent_oracle_rejected(self):
        self.e["tests"][0]["independent_oracle"] = False
        self.rejected("independent positive")

    def test_capacity_regression_requires_review(self):
        self.e["performance"][0]["candidate"] = 4
        self.rejected("unreviewed performance regression")
        self.e["performance"][0]["accepted_tradeoff"] = "Reviewed one-stage resource tradeoff"
        self.assertTrue(self.result()["experimental_integration_eligible"])

    def test_nonfinite_metric_rejected(self):
        self.e["performance"][0]["candidate"] = float("nan")
        self.rejected("invalid performance")

    def test_path_escape_and_symlink_rejected(self):
        self.e["candidate_sources"] = {"../escape": "0" * 64}
        self.rejected("unsafe relative")
        (self.root / "linked").symlink_to(self.root / "module.scala")
        self.e["candidate_sources"] = {"linked": q.sha(self.root / "module.scala")}
        self.rejected("linked evidence")

    def test_unspecified_collision_rejected(self):
        self.e["storage_topology"][0]["collision_policy"] = "undefined"
        self.rejected("collision policy")

    def test_failed_baseline_cannot_be_relabeled(self):
        (self.root / "baseline.json").write_text('{"status":"FAIL"}')
        self.e["artifacts"]["baseline.json"] = q.sha(self.root / "baseline.json")
        self.rejected("baseline receipt itself is not passed")

    def test_metrics_need_evidence_and_optimization_needs_measurement(self):
        self.e["performance"][0].pop("evidence")
        self.rejected("lacks hash-bound evidence")
        self.e["performance"] = []
        self.rejected("no measured latency")

    def test_synthesis_and_loosened_clock_never_promote_physical(self):
        self.e["physical"] = {"kind": "synthesized", "clock_hz": 50000000,
            "candidate_sources": self.e["candidate_sources"], "setup_wns_ns": 1.0,
            "hold_whs_ns": 0.1, "constraints_changed": True}
        result = self.result()
        self.assertTrue(result["experimental_integration_eligible"])
        self.assertFalse(result["source_matched_routed_result"])
        self.assertGreaterEqual(len(result["physical_pending"]), 4)

    def test_routed_remains_board_pending(self):
        for name in ("timing.rpt", "constraints.xdc"):
            (self.root / name).write_text(name)
        self.e["physical"] = {"kind": "routed", "clock_hz": 100000000,
            "candidate_sources": self.e["candidate_sources"], "setup_wns_ns": 0.0,
            "hold_whs_ns": 0.0, "constraints_changed": False,
            "reports": {"timing.rpt": q.sha(self.root / "timing.rpt")},
            "constraints": {"constraints.xdc": q.sha(self.root / "constraints.xdc")}}
        result = self.result()
        self.assertTrue(result["source_matched_routed_result"])
        self.assertEqual(result["status"], "ROUTED_CANDIDATE_BOARD_PENDING")


if __name__ == "__main__":
    unittest.main()
