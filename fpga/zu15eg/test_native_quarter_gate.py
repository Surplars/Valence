"""Intake fixtures only, not RTL, CDC or timing evidence."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from stage_native_rv64gc import QUARTER_TX_NEGATIVES, gate_quarter_tx, sha


class QuarterTxGate(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.source = self.repo / "fpga/zu15eg"
        self.source.mkdir(parents=True)
        self.proof_dir = self.repo / "proof"
        self.proof_dir.mkdir()
        names = ("native_gmac_divided_clock.sv", "native_rgmii.sv", "native_tx_reset_boundary.sv",
                 "native_tx_word_reset_boundary.sv", "native_tx_quarter_board_tb.sv",
                 "soc_top_gmac_ddr.sv", "run_native_tx_quarter_board.py", "glbl.v")
        for name in names:
            (self.source / name).write_text("fixture only " + name)
        shutil.copy2(self.source / "run_native_tx_quarter_board.py", self.proof_dir / "executed_runner.py")
        shutil.copy2(self.source / "soc_top_gmac_ddr.sv", self.proof_dir / "sealed_soc_top_gmac_ddr.sv.txt")
        (self.proof_dir / "positive.log").write_text("PASS_NATIVE_TX_QUARTER_BOARD_SHORT bytes=3072 encodings=4 reset_epochs=3 cold_relocks=2")
        for name, diagnostic in QUARTER_TX_NEGATIVES.items():
            (self.proof_dir / (name + ".log")).write_text("Fatal: " + diagnostic[0])
        self.receipt = dict(status="PASS_NATIVE_TX_QUARTER_BOARD_SHORT", actual_board_tx=True,
                            hardware_phy_init_enabled=False, bit_generated=False,
                            clock_architecture="common_clk250_dedicated_oddr", mac_hz=125000000,
                            pad_hz=250000000, physical_tx_phase_ns=2.0,
                            phy_tx_delay_enabled=False, phy_rx_delay_enabled=True,
                            negative_checks={name: "PASS" for name in QUARTER_TX_NEGATIVES},
                            input_sha256={str(self.source / name): sha(self.source / name) for name in names})

    def gate(self):
        self.receipt["output_sha256"] = {p.name: sha(p) for p in self.proof_dir.iterdir() if p.name != "receipt.json"}
        (self.proof_dir / "receipt.json").write_text(json.dumps(self.receipt))
        return gate_quarter_tx(self.repo, self.proof_dir)

    def test_current_production_passes(self):
        self.assertEqual(self.gate(), sha(self.proof_dir / "receipt.json"))

    def test_private_probe_status_rejected(self):
        self.receipt["status"] = "PASS_NATIVE_TX_QUARTER_DDR_SHORT"
        with self.assertRaises(AssertionError): self.gate()

    def test_current_source_drift_rejected(self):
        (self.source / "native_rgmii.sv").write_text("later source")
        with self.assertRaises(AssertionError): self.gate()

    def test_missing_negative_rejected(self):
        del self.receipt["negative_checks"]["duplicate_breach"]
        with self.assertRaises(AssertionError): self.gate()

    def test_rehashed_wrong_negative_diagnostic_rejected(self):
        (self.proof_dir / "duplicate_breach.log").write_text("Fatal: unrelated model timeout")
        with self.assertRaises(AssertionError): self.gate()

    def test_different_executed_runner_rejected(self):
        (self.proof_dir / "executed_runner.py").write_text("different checker")
        with self.assertRaises(AssertionError): self.gate()

    def test_different_sealed_top_rejected(self):
        (self.proof_dir / "sealed_soc_top_gmac_ddr.sv.txt").write_text("old board")
        with self.assertRaises(AssertionError): self.gate()

    def test_missing_real_word_reset_source_rejected(self):
        del self.receipt["input_sha256"][str(self.source / "native_tx_word_reset_boundary.sv")]
        with self.assertRaises(AssertionError): self.gate()

    def test_slower_mac_rejected(self):
        self.receipt["mac_hz"] = 62500000
        with self.assertRaises(AssertionError): self.gate()

    def test_phy_double_delay_rejected(self):
        self.receipt["phy_tx_delay_enabled"] = True
        with self.assertRaises(AssertionError): self.gate()

    def test_production_boundary_is_not_bit_qualification(self):
        self.receipt["bit_generated"] = True
        with self.assertRaises(AssertionError): self.gate()


if __name__ == "__main__": unittest.main()
