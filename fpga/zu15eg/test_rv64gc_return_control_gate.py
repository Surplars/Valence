"""Intake gate fixtures only, not CPU or FPGA qualification."""
import json
from pathlib import Path
import tempfile
import unittest

from rv64gc_return_control_gate import (PURE_SPECS, LINE_WRITER, absolute_model_path,
                                        gate_contract_update, gate_unchanged_writer, sha)


class ContractUpdateGate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "build/fpga/r3"
        self.supplement = self.base / "scala-contract-update/receipt.json"
        self.functional = self.root / "functional.json"
        self.native = self.root / "native.json"
        self.export = self.base / "export"
        self.changes = {}
        self.sources = {"src/main/scala/Dut.scala": self.write("src/main/scala/Dut.scala", "DUT")}
        for name in PURE_SPECS:
            archive = "build/fpga/r3/scala-contract-update/" + Path(name).name
            before = self.write(archive, "old pure contract")
            after = self.write(name, "corrected pure contract")
            self.changes[name] = dict(before_sha256=before, after_sha256=after, archived_before=archive)
            self.sources[name] = before
        self.functional.write_text(json.dumps(dict(source_sha256=self.sources)))
        self.native.write_text(json.dumps(dict(
            source_sha256={"src/main/scala/Dut.scala": self.sources["src/main/scala/Dut.scala"]},
            cpu_artifact_sha256={"build/gsim/current/run": self.write("build/gsim/current/run", "executed CPU model")})))
        self.s = dict(status="PASS_PURE_SCALA_CONTRACT_UPDATE_UNCHANGED_BOARD_RTL",
                      command=["mill", "-i", "IonSoC.test"], command_exit=0,
                      functional_receipt_sha256=sha(self.functional), native_receipt_sha256=sha(self.native),
                      changed_pure_specs=self.changes, rtl_files_compared=236,
                      previous_failed_log_sha256=self.write("build/fpga/r3/scala-contract-update/testForked.log", "old failure"),
                      updated_log_sha256=self.write("build/fpga/r3/scala-contract-update/updated-testForked.log", "45/45 completed."))
        rtl = {}
        for i in range(236):
            name = f"rtl/Fixture{i}.sv"
            rtl[name] = self.write("build/fpga/r3/export/" + name, f"RTL fixture {i}")
            self.write("build/fpga/r3/export-after-contract/" + name, f"RTL fixture {i}")
        shard = self.export / "rtl-sha256-0.json"
        shard.write_text(json.dumps(rtl))
        self.m = dict(status="EXPORTED_FUNCTIONALLY_CHECKED_NOT_ROUTED",
                      functional_receipt_sha256=sha(self.functional), rtl_file_count=236,
                      rtl_sha256_shards={shard.name: sha(shard)},
                      firmware_sha256={"firmware/bootrom.bin": self.write("build/fpga/r3/export/firmware/bootrom.bin", "ROM fixture")})

    def write(self, name, content):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return sha(p)

    def run_gate(self):
        self.supplement.write_text(json.dumps(self.s))
        self.m["source_contract_update_receipt_sha256"] = sha(self.supplement)
        (self.export / "receipt.json").write_text(json.dumps(self.m))
        return gate_contract_update(self.root, self.functional, self.native, self.supplement, self.export)

    def test_two_pure_contracts_and_identical_rtl_allowed(self):
        self.assertEqual(self.run_gate(), sha(self.supplement))

    def test_hardware_drift_never_exempted(self):
        self.write("src/main/scala/Dut.scala", "changed DUT")
        with self.assertRaises(AssertionError): self.run_gate()

    def test_third_test_exception_refused(self):
        self.s["changed_pure_specs"]["src/test/scala/Other.scala"] = next(iter(self.changes.values()))
        with self.assertRaises(AssertionError): self.run_gate()

    def test_archived_before_must_be_original(self):
        self.write(next(iter(self.changes.values()))["archived_before"], "overwritten archive")
        with self.assertRaises(AssertionError): self.run_gate()

    def test_current_spec_must_match_supplement(self):
        self.write(next(iter(PURE_SPECS)), "another test change")
        with self.assertRaises(AssertionError): self.run_gate()

    def test_current_rtl_drift_refused(self):
        self.write("build/fpga/r3/export/rtl/Fixture0.sv", "changed current RTL")
        with self.assertRaises(AssertionError): self.run_gate()

    def test_reexport_rtl_drift_refused(self):
        self.write("build/fpga/r3/export-after-contract/rtl/Fixture0.sv", "changed re-export")
        with self.assertRaises(AssertionError): self.run_gate()

    def test_unsealed_rtl_refused(self):
        self.write("build/fpga/r3/export/rtl/Extra.sv", "unsealed RTL")
        with self.assertRaises(AssertionError): self.run_gate()

    def test_firmware_drift_refused(self):
        self.write("build/fpga/r3/export/firmware/bootrom.bin", "changed ROM")
        with self.assertRaises(AssertionError): self.run_gate()

    def test_cpu_model_drift_refused(self):
        self.write("build/gsim/current/run", "changed CPU model")
        with self.assertRaises(AssertionError): self.run_gate()

    def test_stale_native_proof_refused(self):
        self.native.write_text("stale receipt")
        with self.assertRaises(json.JSONDecodeError): self.run_gate()

    def test_scala_log_drift_refused(self):
        self.write("build/fpga/r3/scala-contract-update/updated-testForked.log", "unrelated success")
        with self.assertRaises(AssertionError): self.run_gate()

    def test_evidence_paths_stay_in_gsim(self):
        self.assertEqual(absolute_model_path(self.root, "build/gsim/model/run"), self.root / "build/gsim/model/run")
        self.assertEqual(absolute_model_path(self.root, "/home/openion/Valence/build/gsim/model/run"), self.root / "build/gsim/model/run")
        for path in ("../run", "/home/other/Valence/build/gsim/model/run", "build/fpga/run", "D:/run"):
            with self.assertRaises(AssertionError): absolute_model_path(self.root, path)


class WriterComponentGate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        required = (LINE_WRITER, "src/test/scala/ooo/TileLinkLineWriteGsim.scala",
                    "simulator/gsim/harness/line_write.cpp", "build.mill", "simulator/gsim/run.py")
        self.sources = {}
        for name in required:
            self.sources[name] = self.write(name, "unchanged writer dependency")
        artifacts = {}
        for name in ("run", "Writer.fir"):
            p = "build/gsim/writer/" + name
            artifacts["/home/openion/Valence/" + p] = self.write(p, "unchanged model")
        text = "GSIM TileLink line write: PASS II1 adjacentFinalAck"
        self.write("line-writer/test.log", text)
        self.write("line-writer/negative.log", "line write oracle mismatch")
        self.proof = dict(status="PASS_SOC_WINDOW_BATCH_AFFECTED_SHORT", source_sha256=self.sources,
                          checks={"line-writer": text}, model_sha256={"line-writer": artifacts},
                          native_receipt_sha256="deliberately unused old CPU proof")
        self.receipt = self.root / "receipt.json"

    def write(self, name, content):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return sha(p)

    def run_gate(self):
        self.receipt.write_text(json.dumps(self.proof))
        return gate_unchanged_writer(self.root, self.receipt)

    def test_only_writer_imported_never_old_cpu(self):
        self.assertEqual(self.run_gate(), {LINE_WRITER: self.sources[LINE_WRITER]})

    def test_writer_change_refused(self):
        self.write(LINE_WRITER, "changed writer")
        with self.assertRaises(AssertionError): self.run_gate()

    def test_wrapper_change_refused(self):
        self.write("src/test/scala/ooo/TileLinkLineWriteGsim.scala", "changed wrapper")
        with self.assertRaises(AssertionError): self.run_gate()

    def test_executed_model_change_refused(self):
        self.write("build/gsim/writer/run", "changed executable")
        with self.assertRaises(AssertionError): self.run_gate()

    def test_incomplete_dependency_map_refused(self):
        del self.sources["build.mill"]
        with self.assertRaises(AssertionError): self.run_gate()


if __name__ == "__main__": unittest.main()
