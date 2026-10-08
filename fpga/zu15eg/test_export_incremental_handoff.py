"""Export gate unit tests using synthetic local receipts, without hardware runs."""
import json
from pathlib import Path
import tempfile
import unittest

import export_incremental_handoff as handoff
import stage_incremental as stage
from test_stage_incremental import cpu_fixture, put


class LocalProofExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        cpu = cpu_fixture(self.root)
        self.source = self.root / "src/main/scala/Example.scala"
        self.proofs = {}
        statuses = {"prefetch": "PASS", "prf": "PASS_PRF_RAM_ONLY", "monitor": "passed", "network": "passed"}
        for role, status in statuses.items():
            path = self.root / "build" / role / "receipt.json"
            document = {"status": status, "source_sha256": {
                "src/main/scala/Example.scala": handoff.sha(self.source)}}
            if role == "monitor":
                self.rom = put(path.parent / "firmware/bootrom.bin", "tested ROM")
                document["rom_sha256"] = handoff.sha(self.rom)
                cpu["inputs"][str(self.rom)] = handoff.sha(self.rom)
            put(path, json.dumps(document))
            self.proofs[role] = path
            if role != "network":
                cpu["inputs"][str(path)] = handoff.sha(path)
        self.proofs["cpu"] = put(self.root / "build/cpu/receipt.json", json.dumps(cpu))

    def update(self, role, **changes):
        path = self.proofs[role]
        document = json.loads(path.read_text())
        document.update(changes)
        path.write_text(json.dumps(document))

    def validate(self):
        return handoff.validate_proofs(self.proofs, self.root)

    def test_matching_local_receipts_pass(self):
        self.assertEqual(self.validate()["cpu"]["status"], "PASS_SELECTED_BOARD_FUNCTIONAL")

    def test_pass_prefix_does_not_count_as_pass(self):
        self.update("network", status="passed_but_incomplete")
        with self.assertRaisesRegex(RuntimeError, "Unpassed local prerequisite: network"):
            self.validate()

    def test_stale_network_source_is_rejected(self):
        self.update("network", source_sha256={"src/main/scala/Example.scala": "0" * 64})
        with self.assertRaisesRegex(RuntimeError, "network frozen source drift"):
            self.validate()

    def test_empty_source_map_cannot_qualify_receipt(self):
        self.update("network", source_sha256={})
        with self.assertRaisesRegex(RuntimeError, "empty hash manifest"):
            self.validate()

    def test_changed_source_cannot_be_exported_as_passed(self):
        self.source.write_text("hardware changed")
        with self.assertRaisesRegex(RuntimeError, "frozen source drift"):
            self.validate()

    def test_same_receipt_contents_at_new_path_are_not_cpu_prerequisite(self):
        replacement = put(self.root / "build/other/receipt.json", self.proofs["prf"].read_text())
        self.proofs["prf"] = replacement
        with self.assertRaisesRegex(RuntimeError, "CPU did not test this prerequisite: prf"):
            self.validate()

    def test_cpu_rom_and_monitor_rom_must_match(self):
        self.update("monitor", rom_sha256="0" * 64)
        cpu = json.loads(self.proofs["cpu"].read_text())
        cpu["inputs"][str(self.proofs["monitor"])] = handoff.sha(self.proofs["monitor"])
        self.update("cpu", **cpu)
        with self.assertRaisesRegex(RuntimeError, "Monitor/CPU ROM identity mismatch"):
            self.validate()

    def test_physical_file_existence_is_not_finalization(self):
        with self.assertRaisesRegex(RuntimeError, "not finalized"):
            handoff.validate_physical_state({"status": "STAGED_SELECTED_ROM_IP_PENDING"}, self.root, self.proofs)

    def test_stale_physical_proof_cannot_be_labeled_current(self):
        state = {"status": "STAGED_SELECTED_DDR2G_RV64GC100_NOT_ROUTED",
                 "proof_sha256": "0" * 64, "network_proof_sha256": handoff.sha(self.proofs["network"])}
        with self.assertRaisesRegex(RuntimeError, "different functional proofs"):
            handoff.validate_physical_state(state, self.root, self.proofs)

    def physical_fixture(self):
        candidate = self.root / "candidate"
        for folder in ("rtl", "board", "scripts", "firmware", "mig",
                       "ip-build/board_ip.srcs", "ip-build/board_ip.gen"):
            put(candidate / folder / "fixture")
        put(candidate / "firmware/bootrom.bin", self.rom.read_text())
        state = {"status": "STAGED_SELECTED_DDR2G_RV64GC100_NOT_ROUTED",
                 "proof_sha256": handoff.sha(self.proofs["cpu"]),
                 "network_proof_sha256": handoff.sha(self.proofs["network"]),
                 "candidate_sha256": stage.snapshot(candidate, (
                     "rtl", "board", "scripts", "firmware", "mig", "ip-build/board_ip.srcs", "ip-build/board_ip.gen"))}
        return candidate, state

    def test_unchanged_finalized_candidate_passes(self):
        candidate, state = self.physical_fixture()
        handoff.validate_physical_state(state, candidate, self.proofs)

    def test_changed_finalized_candidate_fails(self):
        candidate, state = self.physical_fixture()
        put(candidate / "rtl/fixture", "changed")
        with self.assertRaisesRegex(RuntimeError, "Candidate input inventory/content drift"):
            handoff.validate_physical_state(state, candidate, self.proofs)

    def test_even_rehashed_candidate_rom_must_match_tested_image(self):
        candidate, state = self.physical_fixture()
        path = put(candidate / "firmware/bootrom.bin", "different ROM")
        state["candidate_sha256"]["firmware/bootrom.bin"] = handoff.sha(path)
        with self.assertRaisesRegex(RuntimeError, "different tested ROM"):
            handoff.validate_physical_state(state, candidate, self.proofs)


if __name__ == "__main__":
    unittest.main()
