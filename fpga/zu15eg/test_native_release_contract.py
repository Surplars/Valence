"""Synthetic CDC inventory/review negatives; not current-DCP qualification."""
import copy
import unittest
from verify_native_release_contract import cdc_inventory, fingerprint, validate_cdc_review, vendor_debug_fifo


REPORT = """CDC-1   Critical   1  1-bit unknown CDC circuitry
CDC-3   Info       1  1-bit synchronized
Source Clock: cpu100
Destination Clock: mac125
CDC Type: Safely Timed
  1  CDC-1  Critical  1-bit unknown CDC circuitry  0  Max Delay Datapath Only  mailbox/held_reg[3]/C  mailbox/captured_reg[3]/D
  2  CDC-3  Info  1-bit synchronized  2  Max Delay Datapath Only  request/C  sync/stage0/D
"""
DIGEST = "0" * 64


def reviewed(text=REPORT):
    return {
        "status": "PASS_CURRENT_ROUTED_NATIVE_CDC_REVIEW_WITH_DOCUMENTED_FINDINGS_NOT_BOARD_RUNTIME",
        "dcp_sha256": DIGEST, "timing_exceptions_added": False, "unreviewed_findings": [],
        "findings": [
            {"fingerprint": fingerprint(row), "classification": "held_payload_mailbox",
             "reason": "Synthetic test of complete fingerprint-bound review, not actual hardware proof.",
             "evidence": ["mailbox_truth"]}
            for row in cdc_inventory(text) if row["severity"] != "Info"
        ],
    }


class NativeReleaseInventoryTests(unittest.TestCase):
    def run_review(self, report=REPORT, review=None, roles=None):
        return validate_cdc_review(report, review if review is not None else reviewed(),
                                   DIGEST, roles if roles is not None else {"mailbox_truth"})

    def test_complete_review(self):
        self.assertEqual(self.run_review(), 1)

    def test_no_inventory(self):
        with self.assertRaises(ValueError): cdc_inventory("No CDC Report")

    def test_missing_pair(self):
        with self.assertRaises(ValueError): cdc_inventory(REPORT.replace("Source Clock: cpu100\n", ""))

    def test_declared_count_mismatch(self):
        with self.assertRaises(ValueError): cdc_inventory(REPORT.replace("Critical   1", "Critical   2"))

    def test_duplicate_summary(self):
        with self.assertRaises(ValueError): cdc_inventory(REPORT + "CDC-1   Critical   1  unknown\n")

    def test_unparsed_row(self):
        with self.assertRaises(ValueError): cdc_inventory(REPORT.replace("mailbox/held_reg[3]/C  mailbox/captured_reg[3]/D", "one-column"))

    def test_wrong_dcp(self):
        review = reviewed(); review["dcp_sha256"] = "1" * 64
        with self.assertRaises(ValueError): self.run_review(review=review)

    def test_pending_review(self):
        review = reviewed(); review["status"] = "PENDING"
        with self.assertRaises(ValueError): self.run_review(review=review)

    def test_added_exception(self):
        review = reviewed(); review["timing_exceptions_added"] = True
        with self.assertRaises(ValueError): self.run_review(review=review)

    def test_explicit_unreviewed_finding(self):
        review = reviewed(); review["unreviewed_findings"] = ["new CDC"]
        with self.assertRaises(ValueError): self.run_review(review=review)

    def test_missing_finding(self):
        review = reviewed(); review["findings"] = []
        with self.assertRaises(ValueError): self.run_review(review=review)

    def test_duplicate_finding(self):
        review = reviewed(); review["findings"].append(copy.deepcopy(review["findings"][0]))
        with self.assertRaises(ValueError): self.run_review(review=review)

    def test_foreign_fingerprint(self):
        review = reviewed(); review["findings"][0]["fingerprint"] = "2" * 64
        with self.assertRaises(ValueError): self.run_review(review=review)

    def test_new_endpoint_requires_review(self):
        with self.assertRaises(ValueError): self.run_review(report=REPORT.replace("captured_reg[3]", "captured_reg[4]"))

    def test_new_clock_pair_requires_review(self):
        with self.assertRaises(ValueError): self.run_review(report=REPORT.replace("mac125", "other125"))

    def test_new_exception_requires_review(self):
        with self.assertRaises(ValueError): self.run_review(report=REPORT.replace("Max Delay Datapath Only", "False Path"))

    def test_unknown_class(self):
        review = reviewed(); review["findings"][0]["classification"] = "blanket_safe"
        with self.assertRaises(ValueError): self.run_review(review=review)

    def test_missing_reason(self):
        review = reviewed(); review["findings"][0]["reason"] = "safe"
        with self.assertRaises(ValueError): self.run_review(review=review)

    def test_unbound_evidence(self):
        review = reviewed(); review["findings"][0]["evidence"] = ["not_checked"]
        with self.assertRaises(ValueError): self.run_review(review=review)

    def test_no_evidence(self):
        review = reviewed(); review["findings"][0]["evidence"] = []
        with self.assertRaises(ValueError): self.run_review(review=review)

    def test_vendor_trust_cannot_cover_native_critical(self):
        review = reviewed(); review["findings"][0]["classification"] = "vendor_encrypted_boundary"
        with self.assertRaises(ValueError): self.run_review(review=review)

    def test_duplicate_detail_identity(self):
        report = REPORT.replace("Critical   1", "Critical   2") + REPORT.splitlines()[-2] + "\n"
        with self.assertRaises(ValueError): self.run_review(report=report)

    def debug_row(self, direction="RD", bit=14):
        tck = "dbg_hub/inst/BSCANID.u_xsdbm_id/SWITCH_N_EXT_BSCAN.bscan_inst/SERIES7_BSCAN.bscan_inst/INTERNAL_TCK"
        prefix = ("dbg_hub/inst/BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/"
                  f"U_CMD6_{direction}/U_{direction}_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_{direction.lower()}fifo_inst/"
                  "inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.mem/gdm.dm_gen.dm/")
        source_clock, destination_clock = ("mmcm_clkout5", tck) if direction == "RD" else (tck, "mmcm_clkout5")
        return dict(id="CDC-15", severity="Warning", depth="0", exception="False Path",
                    source=prefix + "RAM_reg_0_15_14_15" + ("__0" if bit == 15 else "") + "/DP/CLK",
                    destination=prefix + f"gpr1.dout_i_reg[{bit}]/D",
                    source_clock=source_clock, destination_clock=destination_clock)

    def test_four_exact_debug_fifo_pairs(self):
        for direction in ("RD", "WR"):
            for bit in (14, 15):
                self.assertTrue(vendor_debug_fifo(self.debug_row(direction, bit)))

    def test_debug_fifo_rejects_critical(self):
        row = self.debug_row(); row["severity"] = "Critical"
        self.assertFalse(vendor_debug_fifo(row))

    def test_debug_fifo_rejects_new_clock(self):
        row = self.debug_row(); row["source_clock"] = "clk_out1_clk_wiz_ddr"
        self.assertFalse(vendor_debug_fifo(row))

    def test_debug_fifo_rejects_other_endpoint(self):
        row = self.debug_row(); row["destination"] = row["destination"].replace("[14]", "[13]")
        self.assertFalse(vendor_debug_fifo(row))

    def test_debug_fifo_rejects_other_exception(self):
        row = self.debug_row(); row["exception"] = "Max Delay Datapath Only"
        self.assertFalse(vendor_debug_fifo(row))

    def test_debug_fifo_rejects_native_path(self):
        self.assertFalse(vendor_debug_fifo(dict(cdc_inventory(REPORT)[0])))


if __name__ == "__main__":
    unittest.main(verbosity=2)
