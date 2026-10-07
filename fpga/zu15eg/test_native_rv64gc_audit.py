"""Unit tests of report parsing only, not a hardware or timing receipt."""
import unittest

from audit_native_rv64gc import checked_source_map, io_slack, resources, routed_state, summary


class ReportParsing(unittest.TestCase):
    def test_physical_clock_and_script_provenance_included(self):
        inputs = {"checked_source_sha256": {"src/main/scala/Core.scala": "chisel"},
                  "candidate_sha256": {"board\\native_gmac_clocks.sv": "clock",
                                       "scripts/native_board_constraints.tcl": "constraints",
                                       "ip-build/vendor.xci": "ip"}}
        self.assertEqual(checked_source_map(inputs), {
            "src/main/scala/Core.scala": "chisel",
            "fpga/zu15eg/native_gmac_clocks.sv": "clock",
            "fpga/zu15eg/native_board_constraints.tcl": "constraints"})

    def test_only_completed_route_states(self):
        for state in ("Routed", "Physopt postRoute"):
            self.assertTrue(routed_state("| Design State      : " + state + "\n"))
        for state in ("Placed", "Physopt", "Synthesized", "Partially Routed", ""):
            self.assertFalse(routed_state("| Design State      : " + state + "\n"))

    def test_summary_preserves_failures(self):
        text = "| Design Timing Summary\n -0.036 -0.045 2 100 -0.003 -0.003 1 100 0.081 0.000 0 100\n"
        result = summary(text)
        self.assertEqual(result["setup_ns"], -0.036)
        self.assertEqual(result["hold_failures"], 1)
        self.assertEqual(result["pulse_ns"], 0.081)

    def test_missing_summary_rejected(self):
        with self.assertRaises(AssertionError):
            summary("| Design Timing Summary\n Report failed\n")

    def test_fpu_must_be_instantiated(self):
        board = "| soc_top_gmac_ddr | (top) | 200000 | 197000 | 2000 | 1000 | 95000 | 64 | 3 | 0 | 44 |\n"
        fp = "| floatingPoint | FloatingPointSystem | 23114 | 23000 | 100 | 14 | 6127 | 0 | 0 | 0 | 22 |\n"
        self.assertEqual(resources(board + fp)["FloatingPointSystem"]["dsps"], 22)
        own = "| (floatingPoint) | FloatingPointSystem | 209 | 209 | 0 | 0 | 130 | 0 | 0 | 0 | 0 |\n"
        self.assertEqual(resources(board + fp + own)["FloatingPointSystem"]["luts"], 23114)
        with self.assertRaises(AssertionError):
            resources(board)
        with self.assertRaises(AssertionError):
            resources(board + fp + fp)

    def test_all_endpoints_require_both_checks(self):
        ports = {"eth_txd[0]", "eth_tx_ctl"}
        block = lambda port, kind, slack: f"Slack (MET) : {slack}ns\n  Destination: {port}\n  Path Type: {kind}\n"
        text = "".join(block(port, kind, slack) for port in ports
                       for kind, slack in (("Setup (Max at Slow Process Corner)", ".123"),
                                            ("Hold (Min at Fast Process Corner)", ".045")))
        self.assertEqual(io_slack(text, ports, "Destination"), {"setup_ns": .123, "hold_ns": .045})
        with self.assertRaises(AssertionError):
            io_slack(block("eth_txd[0]", "Setup", ".123") + block("eth_txd[0]", "Hold", ".045"), ports, "Destination")

    def test_infinite_paths_not_valid(self):
        text = "Slack (MET) : infns\n Destination: eth_txd[0]\n Path Type: Setup\n"
        with self.assertRaises(ValueError):
            io_slack(text, {"eth_txd[0]"}, "Destination")


if __name__ == "__main__":
    unittest.main()
