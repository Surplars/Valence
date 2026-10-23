"""Independent baseline byte-preservation oracle; not physical qualification."""
import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
sha = lambda s: hashlib.sha256(s.encode()).hexdigest()


class RxCascadeIntegration(unittest.TestCase):
    def test_original_tx_calibration_and_capture_unchanged(self):
        s = (ROOT / 'fpga/zu15eg/native_rgmii_trispeed_quarter.sv').read_text()
        # Digests from pre-candidate reviewed source, not derived from this DUT.
        tx = s[s.index('    wire serializer_reset;'):s.index('    for(genvar n=0;n<5;n=n+1) begin: receive')]
        capture = s[s.index('        IDDRE1 #'):]
        self.assertEqual(sha(tx), 'edf2883b852d556192c9f54bd099a5e2e7039dfee2232c6b05761477457bc375')
        self.assertEqual(sha(capture), 'b93fb5e5570c6062d1a723228197f24e72f0363c661453c4195ef907f002b562')
        self.assertIn('parameter integer RX_CASCADE_STAGE_DELAY_PS = -1', s)
        self.assertIn('.CASCADE(RX_CASCADE_STAGE_DELAY_PS < 0 ? "NONE" : "MASTER")', s)
        self.assertIn('.DELAY_VALUE(RX_CASCADE_STAGE_DELAY_PS < 0 ? RX_DATA_DELAY_PS : RX_CASCADE_STAGE_DELAY_PS)', s)
        self.assertIn('.DELAY_VALUE(RX_CASCADE_STAGE_DELAY_PS)', s)
        self.assertIn("assign returned = 1'b0;", s)
        self.assertIn('.CASC_RETURN(returned), .CASC_OUT(cascade)', s)
        self.assertIn('RX_CASCADE_STAGE_DELAY_PS < -1 || RX_CASCADE_STAGE_DELAY_PS > 1100', s)

    def test_original_shell_unchanged_except_explicit_parameter_hook(self):
        s = (ROOT / 'fpga/common/soc_top_common_ddr.sv').read_text()
        s = s.replace('module soc_top_common_ddr #(\n    // Explicit diagnostic override only; production/default keeps single1100.\n    parameter integer RX_CASCADE_STAGE_DELAY_PS = -1\n) (', 'module soc_top_common_ddr (')
        s = s.replace('        .RX_CASCADE_STAGE_DELAY_PS(RX_CASCADE_STAGE_DELAY_PS),\n', '')
        self.assertEqual(sha(s), 'b51d4834e9e6d63c91f2b1462692bd59755cb770643188035a23f57461d4df3b')

    def test_review_gate_uses_actual_changed_pad_bytes(self):
        p = ROOT / 'fpga/zu15eg/native_rgmii_trispeed_quarter.sv'
        self.assertIn(hashlib.sha256(p.read_bytes()).hexdigest(), (ROOT / 'fpga/common/board_inputs.py').read_text())


if __name__ == '__main__':
    unittest.main()
