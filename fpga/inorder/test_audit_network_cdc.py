import unittest
from audit_network_cdc import audit


class AuditCdcTests(unittest.TestCase):
    def report(self, row, count=1):
        return (f"CDC-1 Critical {count} 1-bit unknown CDC circuitry\n"
                "Source Clock: a\nDestination Clock: b\n" + row + "\n")

    def test_mailbox_stays_unresolved(self):
        result = audit(self.report(
            " 1 CDC-1 Critical 1-bit unknown CDC circuitry 0 Max Delay Datapath Only "
            "bank/gmac/rxStop/command/held_reg/C bank/gmac/rxStop/command/captured_reg/D"))
        self.assertEqual(result["status"], "KNOWN_CRITICAL_REVIEW_REQUIRED")
        self.assertFalse(result["cdc_signed_off"])
        self.assertFalse(result["critical_rows"][0]["waived"])

    def test_mismatched_bit_is_unknown(self):
        result = audit(self.report(
            " 1 CDC-1 Critical unknown 0 Max Delay Datapath Only "
            "bank/gmac/txConfig/mailbox/held_reg[3]/C bank/gmac/txConfig/mailbox/captured_reg[2]/D"))
        self.assertEqual(result["unknown_critical_count"], 1)

    def test_missing_detail_rejected(self):
        with self.assertRaises(ValueError):
            audit(self.report("", count=1))

    def test_unknown_circuit_not_hidden(self):
        result = audit(self.report(" 1 CDC-1 Critical unknown 0 None a_reg/C b_reg/D"))
        self.assertEqual(result["status"], "UNKNOWN_CRITICAL_REQUIRES_REVIEW")

    def test_registered_warm_reset_stays_unresolved(self):
        result = audit(
            "CDC-10 Critical 1 Combinational logic detected before a synchronizer\n"
            "Source Clock: cpu\nDestination Clock: rx\n"
            " 1 CDC-10 Critical Combinational logic 3 None "
            "bank/gmac/media/ingressResetSource_reg/C "
            "bank/gmac/physicalIngress/crossing/fifo/sourceRelease/release_0_reg[0]/PRE\n")
        self.assertEqual(result["status"], "KNOWN_CRITICAL_REVIEW_REQUIRED")
        self.assertFalse(result["cdc_signed_off"])

    def test_cpu_board_exact_reset_rows_are_not_waived(self):
        text = ("CDC-10 Critical 1 Combinational logic before synchronizer\n"
                "CDC-11 Critical 1 Fan-out from launch flop\n"
                "Source Clock: cpu300\nDestination Clock: aon50\n"
                " 1 CDC-11 Critical reset fanout 3 False Path reset_pipe_reg[2]/C "
                "u_soc/bank/uart/bridge/destinationResetSync/release_0_reg[0]/PRE\n"
                "Destination Clock: bscan\n"
                " 2 CDC-10 Critical reset logic 3 False Path u_soc/release_0/release_0_reg[2]/C "
                "u_soc/transport/enabled.transport/raw_release_reg[0]/CLR\n")
        result = audit(text)
        self.assertEqual(result["unknown_critical_count"], 0)
        self.assertEqual(result["status"], "KNOWN_CRITICAL_REVIEW_REQUIRED")
        self.assertFalse(result["cdc_signed_off"])
        self.assertTrue(all(not row["waived"] for row in result["critical_rows"]))
        # A superficially similar OTHER stage is not silently accepted.
        changed = audit(text.replace("destinationResetSync/release_0_reg[0]/PRE",
                                     "destinationResetSync/release_0_reg[1]/PRE"))
        self.assertEqual(changed["unknown_critical_count"], 1)


if __name__ == "__main__":
    unittest.main()
