"""Host-only provenance tests; none of these fixtures proves hardware behavior."""
import copy
from pathlib import Path
import tempfile
import unittest

import stage_incremental as stage


# Independent CLI contract: changing implementation constants must not silently
# change the configuration these tests accept.
SELECTED = ["ddr", "100000000", "staged-fetch-turnover", "460800", "2", "2",
    "1", "rv64gc", "2147483648", "0", "512", "0", "512", "4", "16", "2", "2", "1",
    "--compact-tags", "--identity-data-flow", "--banked-rob", "--shared-store-reads",
    "--ddr-write-slots=2", "--cache-writebacks=2", "--overlap-writeback-refill",
    "--unordered-ddr-responses", "--lvt-prf", "--data-next-line-prefetch"]


def put(path, content="fixture"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def cpu_fixture(root):
    sources = [put(root / name) for name in
               ("build.mill", ".mill-version", "src/main/scala/Example.scala")]
    artifact = put(root / "build/model.fir")
    return {"status": "PASS_SELECTED_BOARD_FUNCTIONAL", "parameters": SELECTED.copy(),
            "inputs": {str(path): stage.sha(path) for path in sources},
            "artifacts": {str(artifact): stage.sha(artifact)}}


class SelectedCpuProof(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cpu = cpu_fixture(self.root)

    def test_exact_candidate_passes(self):
        stage.validate_cpu_proof(self.cpu, self.root)

    def test_every_parameter_is_part_of_the_gate(self):
        for index in range(len(SELECTED)):
            with self.subTest(parameter=SELECTED[index]):
                wrong = copy.deepcopy(self.cpu)
                wrong["parameters"][index] = "wrong"
                with self.assertRaisesRegex(RuntimeError, "Wrong selected CPU parameters"):
                    stage.validate_cpu_proof(wrong, self.root)

    def test_omitting_opt_in_flags_is_rejected(self):
        self.cpu["parameters"] = SELECTED[:18]
        with self.assertRaisesRegex(RuntimeError, "Wrong selected CPU parameters"):
            stage.validate_cpu_proof(self.cpu, self.root)

    def test_new_scala_file_invalidates_old_proof(self):
        put(self.root / "src/main/scala/NewHardware.scala")
        with self.assertRaisesRegex(RuntimeError, "missing current source"):
            stage.validate_cpu_proof(self.cpu, self.root)

    def test_input_drift_invalidates_pass_status(self):
        put(self.root / "src/main/scala/Example.scala", "changed")
        with self.assertRaisesRegex(RuntimeError, "CPU frozen source drift"):
            stage.validate_cpu_proof(self.cpu, self.root)

    def test_model_drift_invalidates_pass_status(self):
        put(self.root / "build/model.fir", "changed")
        with self.assertRaisesRegex(RuntimeError, "CPU proof artifact drift"):
            stage.validate_cpu_proof(self.cpu, self.root)

    def test_empty_hash_manifest_is_rejected(self):
        self.cpu["inputs"] = {}
        with self.assertRaisesRegex(RuntimeError, "empty hash manifest"):
            stage.validate_cpu_proof(self.cpu, self.root)

    def test_another_checkout_cannot_satisfy_current_source_gate(self):
        other = self.root / "other-checkout"
        other.mkdir()
        with self.assertRaisesRegex(RuntimeError, "outside current root"):
            stage.validate_cpu_proof(self.cpu, other)


class StagedInputProof(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out, self.old = self.root / "candidate", self.root / "baseline"
        for name in ("rtl", "board", "scripts", "firmware", "mig"):
            put(self.out / name / "input")
        put(self.old / "inputs.json", "{}")
        reference = put(self.old / "implementation/routed.dcp")
        self.proof, self.net = put(self.root / "cpu.json"), put(self.root / "net.json")
        self.state = {"status": "STAGED_SELECTED_ROM_IP_PENDING",
            "proof_sha256": stage.sha(self.proof), "network_proof_sha256": stage.sha(self.net),
            "baseline_manifest_sha256": stage.sha(self.old / "inputs.json"),
            "incremental_routed_reference": str(reference),
            "incremental_routed_reference_sha256": stage.sha(reference),
            "staged_sha256": stage.snapshot(self.out, ("rtl", "board", "scripts", "firmware", "mig"))}

    def validate(self):
        stage.validate_staged(self.state, self.out, self.old, self.proof, self.net)

    def test_frozen_stage_passes(self):
        self.validate()

    def test_added_rtl_is_not_silently_signed_at_finalization(self):
        put(self.out / "rtl/StaleModule.sv")
        with self.assertRaisesRegex(RuntimeError, "inventory/content drift"):
            self.validate()

    def test_removed_rtl_is_rejected(self):
        (self.out / "rtl/input").unlink()
        with self.assertRaisesRegex(RuntimeError, "inventory/content drift"):
            self.validate()

    def test_changed_rtl_is_rejected(self):
        put(self.out / "rtl/input", "changed")
        with self.assertRaisesRegex(RuntimeError, "inventory/content drift"):
            self.validate()

    def test_replaced_baseline_manifest_is_rejected(self):
        put(self.old / "inputs.json", '{"different": true}')
        with self.assertRaisesRegex(RuntimeError, "Baseline manifest changed"):
            self.validate()

    def test_replaced_routed_reference_is_rejected(self):
        put(self.old / "implementation/routed.dcp", "different")
        with self.assertRaisesRegex(RuntimeError, "Routed reference changed"):
            self.validate()

    def test_replaced_proof_is_rejected(self):
        put(self.net, "changed")
        with self.assertRaisesRegex(RuntimeError, "Proof changed"):
            self.validate()

    def test_finalized_manifest_is_never_overwritten(self):
        put(self.out / "inputs.json", "existing")
        with self.assertRaisesRegex(RuntimeError, "Preserve finalized inputs"):
            self.validate()

    def test_missing_fixed_ip_manifest_member_is_rejected(self):
        ip = "ip-build/board_ip.gen/sources_1/ip/clk_wiz_ddr"
        source = put(self.old / ip / "clock.xci")
        hashes = {str(source.relative_to(self.old)): stage.sha(source), ip + "/clock.dcp": "0" * 64}
        with self.assertRaisesRegex(RuntimeError, "Fixed IP drift"):
            stage.check_tree(self.old, hashes, (ip,), "Fixed IP drift")

    def test_symlink_cannot_escape_inventory(self):
        (self.out / "rtl/external").symlink_to(self.old, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "Linked input"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
