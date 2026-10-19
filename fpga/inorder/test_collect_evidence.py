#!/usr/bin/env python3
"""Report parsers must reject shape drift and retain failed synthesis timing."""
import unittest
from collect_evidence import timing, utilization, worst_path, route_status


class ReportParserTests(unittest.TestCase):
    def test_synthesized_resource_row(self):
        sample = "| FiveStageCore | (top) | 4641 | 4641 | 0 | 0 | 2735 | 2 | 0 | 0 | 34 |"
        self.assertEqual(utilization(sample), {
            "lut": 4641, "logic_lut": 4641, "lutram": 0, "srl": 0, "ff": 2735,
            "bram36": 2, "bram18": 0, "uram": 0, "dsp": 34})
        for invalid in ("", sample + "\n" + sample, sample.replace("| 34 |", "|")):
            with self.assertRaises(ValueError):
                utilization(invalid)

    def test_timing_failure_is_not_discarded(self):
        sample = " WNS(ns) TNS(ns) others\n --------\n -1.050 -297.840 703 6883 0.053 0.000 0 6883 1.958 0.000 0 2748"
        value = timing(sample)
        self.assertEqual(value["wns_ns"], -1.050)
        self.assertEqual(value["setup_failing_endpoints"], 703)
        self.assertEqual(value["whs_ns"], 0.053)
        with self.assertRaises(ValueError):
            timing(sample.replace(" 2748", ""))

    def test_worst_path_fields(self):
        sample = "  Source: rf/bank/CLKARDCLK\n  Destination: desiredPc_reg[10]/CE\n  Data Path Delay: 5.898ns details\n  Logic Levels: 18 details"
        value = worst_path(sample)
        self.assertEqual(value["logic_levels"], 18)
        self.assertEqual(value["data_path_ns"], 5.898)
        self.assertEqual(value["destination"], "desiredPc_reg[10]/CE")
        with self.assertRaises(ValueError):
            worst_path(sample.replace("Data Path Delay", "unknown"))

    def test_complete_and_failed_route_counts(self):
        sample = "# of routable nets...... : 8435 :\n# of fully routed nets.... : 8435 :\n# of nets with routing errors.... : 0 :"
        self.assertEqual(route_status(sample), {
            "routable_nets": 8435, "fully_routed_nets": 8435, "nets_with_routing_errors": 0})
        self.assertEqual(route_status(sample.replace(": 0 :", ": 9 :"))["nets_with_routing_errors"], 9)
        with self.assertRaises(ValueError):
            route_status(sample.replace("fully routed nets", "unknown"))


if __name__ == "__main__":
    unittest.main()
