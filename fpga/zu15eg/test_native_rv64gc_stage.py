"""Evidence-gate unit tests only; not hardware/CDC/timing qualification."""
import json
from pathlib import Path
import tempfile
import unittest

from stage_native_rv64gc import LINE_WRITER_SOURCE, REVALIDATED_TL, gate_path_batch, gate_refactor, gate_window_batch, sha


class BatchProofGate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.short = self.root / "native.json"
        self.short.write_text("CPU proof fixture")
        self.source = {}
        for name in REVALIDATED_TL:
            file = self.root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("independent source fixture " + name)
            self.source[name] = sha(file)
        self.model = self.root / "model/run"
        self.model.parent.mkdir()
        self.model.write_text("model fixture")
        self.proof = dict(status="PASS_RV64GC_PATH_BATCH_AFFECTED_SHORT", isa="rv64gc",
                          issue_width=2, cpu_hz=100000000, uart_baud=460800,
                          source_sha256=self.source, native_receipt_sha256=sha(self.short),
                          reused_models={"fixture": {"model/run": sha(self.model)}}, checks={})
        for name in ("crossbar-legacy", "crossbar-raw"):
            self.proof["checks"][name] = "GSIM TileLink crossbar: PASS requests=16"
            self.proof["checks"][name + "-burst"] = "GSIM TileLink burst fabric: PASS PutFullData=2x8 Get=2x8 deniedGet=8"
            (self.root / (name + "-negative.log")).write_text("TileLink crossbar D source, data or owner mismatch")
        self.proof["checks"].update({
            "router-errors": "GSIM TileLink router: PASS requests=16",
            "timing-smoke": "GSIM control/memory timing + NEMU: PASS",
            "pipeline-recovery": "GSIM pipeline recovery + NEMU: PASS",
        })
        (self.root / "router-errors-negative.log").write_text("TileLink router response data, source or route mismatch")
        (self.root / "router-errors").mkdir()
        (self.root / "router-errors/wrong-owner.log").write_text("TileLink bank response has no matching source")
        self.receipt = self.root / "receipt.json"

    def run_gate(self):
        self.receipt.write_text(json.dumps(self.proof))
        return gate_path_batch(self.root, self.receipt, self.short)

    def test_only_two_explicit_dependencies_replaced(self):
        self.assertEqual(self.run_gate(), self.source)

    def test_missing_burst_refused(self):
        del self.proof["checks"]["crossbar-raw-burst"]
        with self.assertRaises(KeyError):
            self.run_gate()

    def test_changed_source_refused(self):
        (self.root / REVALIDATED_TL[0]).write_text("changed source")
        with self.assertRaises(AssertionError):
            self.run_gate()

    def test_changed_reused_model_refused(self):
        self.model.write_text("changed model")
        with self.assertRaises(AssertionError):
            self.run_gate()

    def test_different_cpu_proof_refused(self):
        self.short.write_text("different CPU proof")
        with self.assertRaises(AssertionError):
            self.run_gate()

    def test_wrong_bank_oracle_required(self):
        (self.root / "router-errors/wrong-owner.log").write_text("unrelated failure")
        with self.assertRaises(AssertionError):
            self.run_gate()

    def test_four_issue_proof_not_board_baseline(self):
        self.proof["issue_width"] = 4
        with self.assertRaises(AssertionError):
            self.run_gate()


    def test_isolated_tl_reuse_does_not_require_old_cpu_proof(self):
        self.receipt.write_text(json.dumps(self.proof))
        self.short.write_text("fresh CPU proof")
        self.assertEqual(gate_path_batch(self.root, self.receipt, self.short, components_only=True), self.source)

    def test_isolated_tl_reuse_still_refuses_source_drift(self):
        self.receipt.write_text(json.dumps(self.proof))
        (self.root / REVALIDATED_TL[0]).write_text("changed TL implementation")
        with self.assertRaises(AssertionError):
            gate_path_batch(self.root, self.receipt, self.short, components_only=True)

    def test_isolated_tl_reuse_still_refuses_model_drift(self):
        self.proof["reused_models"] = {"crossbar-legacy": {"model/run": sha(self.model)}}
        self.receipt.write_text(json.dumps(self.proof))
        self.model.write_text("changed TL model")
        with self.assertRaises(AssertionError):
            gate_path_batch(self.root, self.receipt, self.short, components_only=True)


class RefactorProofGate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.short = self.root / "native.json"
        self.short.write_text("fresh native CPU proof fixture")
        self.source = self.root / "source.scala"
        self.source.write_text("production source fixture")
        self.proof = dict(status="PASS_SOC_PIPELINE_REFACTOR_AFFECTED_SHORT", isa="rv64gc",
                          issue_width=2, cpu_hz=100000000, uart_baud=460800,
                          source_sha256={"source.scala": sha(self.source)},
                          native_receipt_sha256=sha(self.short), integer_measurements=[{}] * 13, checks={})
        for name, prefix, diagnostic in (
            ("cursor-neighbor", "CURSOR_NEIGHBOR_PASS vectors=10445", "cursor neighbor independent oracle mismatch"),
            ("natural-pmp", "GSIM PMP checker: PASS", "PMP oracle mismatch"),
            ("fp-memory", "FP_MEMORY_PIPELINE_PASS", "FP memory boundary oracle mismatch"),
            ("translation-context", "TRANSLATION_CONTEXT_PASS", "VM context independent oracle mismatch"),
            ("fetch-2-32", "GSIM registered fetch packet: PASS width=2", "fetch packet oracle mismatch"),
            ("fetch-4-8", "GSIM registered fetch packet: PASS width=4", "fetch packet oracle mismatch"),
        ):
            self.proof["checks"][name] = prefix
            self.proof["checks"][name + "-negative"] = diagnostic
            (self.root / name).mkdir()
            (self.root / name / "negative.log").write_text(diagnostic)
        self.proof["checks"].update({
            "timing-smoke": "GSIM control/memory timing + NEMU: PASS",
            "pipeline-recovery": "GSIM pipeline recovery + NEMU: PASS",
            "integer-core": "GSIM short two-issue throughput + NEMU: PASS programs=13",
        })
        (self.root / "integer-core").mkdir()
        (self.root / "integer-core/negative.log").write_text("NEMU register mismatch")
        self.receipt = self.root / "receipt.json"

    def run_gate(self):
        self.receipt.write_text(json.dumps(self.proof))
        return gate_refactor(self.root, self.receipt, self.short)

    def test_fresh_structural_cpu_evidence(self):
        self.assertEqual(self.run_gate(), sha(self.receipt))

    def test_stale_native_proof_refused(self):
        self.short.write_text("different native CPU proof")
        with self.assertRaises(AssertionError):
            self.run_gate()

    def test_source_drift_refused(self):
        self.source.write_text("different production source")
        with self.assertRaises(AssertionError):
            self.run_gate()

    def test_missing_vm_context_check_refused(self):
        del self.proof["checks"]["translation-context"]
        with self.assertRaises(KeyError):
            self.run_gate()

    def test_bogus_negative_log_refused(self):
        (self.root / "fp-memory/negative.log").write_text("unrelated failure")
        with self.assertRaises(AssertionError):
            self.run_gate()

    def test_incomplete_ipc_refused(self):
        self.proof["integer_measurements"].pop()
        with self.assertRaises(AssertionError):
            self.run_gate()


class WindowProofGate(RefactorProofGate):
    def setUp(self):
        super().setUp()
        self.proof["status"] = "PASS_SOC_WINDOW_BATCH_AFFECTED_SHORT"
        writer = self.root / LINE_WRITER_SOURCE
        writer.parent.mkdir(parents=True, exist_ok=True)
        writer.write_text("changed writer source fixture")
        self.proof["source_sha256"][LINE_WRITER_SOURCE] = sha(writer)
        model = self.root / "model/run"
        model.parent.mkdir()
        model.write_text("checked numerical/writer model fixture")
        self.proof["model_sha256"] = {}
        for name, prefix, diagnostic in (
            ("fetch-window-3", "GSIM registered fetch window: PASS", "fetch window independent oracle mismatch"),
            ("fetch-window-5", "GSIM registered fetch window: PASS", "fetch window independent oracle mismatch"),
            ("fp-state", "FP_STATE_PASS", "FP oracle mismatch"),
            ("fp-numerical-fd", "FP_FULL_PASS profile=fd", "FP full mismatch"),
            ("fp-numerical-f", "FP_FULL_PASS profile=f", "FP full mismatch"),
            ("fp-numerical-small", "FP_FULL_PASS profile=small", "FP full mismatch"),
            ("line-writer", "GSIM TileLink line write: PASS II1 adjacentFinalAck", "line write oracle mismatch"),
        ):
            self.proof["checks"][name] = prefix
            self.proof["checks"][name + "-negative"] = diagnostic
            (self.root / name).mkdir()
            (self.root / name / "negative.log").write_text(diagnostic)
            self.proof["model_sha256"][name] = {"/home/openion/Valence/model/run": sha(model)}
        self.proof["checks"]["line-read-write"] = "GSIM TileLink line read/write RAM: PASS"
        self.proof["model_sha256"]["line-read-write"] = {"/home/openion/Valence/model/run": sha(model)}

    def run_gate(self):
        self.receipt.write_text(json.dumps(self.proof))
        return gate_window_batch(self.root, self.receipt, self.short)

    def test_missing_vm_context_check_refused(self):
        # VM pipeline is unchanged in this batch, but both numerical profiles
        # and the current board/native CPU proof remain mandatory.
        del self.proof["checks"]["fp-numerical-f"]
        with self.assertRaises(KeyError):
            self.run_gate()

    def test_bogus_negative_log_refused(self):
        (self.root / "line-writer/negative.log").write_text("unrelated failure")
        with self.assertRaises(AssertionError):
            self.run_gate()

    def test_changed_writer_refused(self):
        (self.root / LINE_WRITER_SOURCE).write_text("different writer")
        with self.assertRaises(AssertionError):
            self.run_gate()

    def test_changed_model_refused(self):
        (self.root / "model/run").write_text("different model")
        with self.assertRaises(AssertionError):
            self.run_gate()

    def test_missing_adjacent_burst_contract_refused(self):
        self.proof["checks"]["line-writer"] = "GSIM TileLink line write: PASS"
        with self.assertRaises(AssertionError):
            self.run_gate()


if __name__ == "__main__":
    unittest.main()
