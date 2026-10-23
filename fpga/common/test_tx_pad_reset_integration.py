"""Exact source-delta proof for the explicit TX-only common-shell parameter."""
import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
# Exact pre-change common shell in c1457f6627b52bcf1aeb51ec891cd8ae0150c6ca.
BEFORE_SHA = '04019a87079eb017ea639e9a2fe0273d0c08db12b3cb7b565c65843e685a949a'
NEW_PARAMETERS = '''parameter integer RX_CASCADE_STAGE_DELAY_PS = -1,
    // Explicit TX diagnostic candidate; one falling-PAD release driver.
    parameter integer TX_LOCAL_PAD_RESET_RELEASE = 0'''
NEW_CONNECTION = '.LOCAL_PAD_RESET_RELEASE(TX_LOCAL_PAD_RESET_RELEASE),'


def exact_delta(text):
    if text.count(NEW_PARAMETERS) != 1 or text.count(NEW_CONNECTION) != 1:
        return False
    restored = text.replace(NEW_PARAMETERS, 'parameter integer RX_CASCADE_STAGE_DELAY_PS = -1')
    restored = restored.replace(NEW_CONNECTION, '.LOCAL_PAD_RESET_RELEASE(0),')
    return hashlib.sha256(restored.encode()).hexdigest() == BEFORE_SHA


class TxPadResetIntegration(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT/'fpga/common/soc_top_common_ddr.sv').read_text()

    def test_only_explicit_default_off_hook_changed(self):
        self.assertTrue(exact_delta(self.text))

    def test_default_on_is_not_silently_admitted(self):
        self.assertFalse(exact_delta(self.text.replace('TX_LOCAL_PAD_RESET_RELEASE = 0', 'TX_LOCAL_PAD_RESET_RELEASE = 1')))

    def test_bypassed_hook_is_rejected(self):
        self.assertFalse(exact_delta(self.text.replace(NEW_CONNECTION, '.LOCAL_PAD_RESET_RELEASE(0),')))

    def test_unrelated_rx_or_clock_change_is_rejected(self):
        for old, new in [('RX_CASCADE_STAGE_DELAY_PS = -1','RX_CASCADE_STAGE_DELAY_PS = 450'),
                         ('.REGISTER_SELECTED_HALF(0)', '.REGISTER_SELECTED_HALF(1)'),
                         ('.clock_tx(clk_tx)', '.clock_tx(clk_tx_pad)')]:
            self.assertFalse(exact_delta(self.text.replace(old,new)))

    def test_existing_tx_rtl_is_unchanged(self):
        # Already reviewed and native-tested RTL; only selection is new.
        p = ROOT/'fpga/zu15eg/native_rgmii_trispeed_quarter.sv'
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),
                         '9db8e97150a2eab5670ac1ebd0512c608ee5d390f680235d95661d7e9bb99f78')

if __name__ == '__main__':
    unittest.main()
