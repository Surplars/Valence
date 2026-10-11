#!/usr/bin/env python3
"""Independent host-only line channel forwarding and frozen-default checks."""
import copy
import tempfile
import unittest
import test_ddr_write_collection_cli as collection_cli

FLAG = "--line-read-channel"


class LineReadChannelCliTests(unittest.TestCase):
    call = collection_cli.WriteCollectionCliTests.call

    def test_independent_selection_and_forwarding(self):
        with tempfile.TemporaryDirectory(prefix="line-read-cli-") as tmp:
            for selector, variant in (([], "selected"), (["--reference"], "reference"),
                                      (["--storage-candidate"], "candidate")):
                for extra in ([], ["--ddr-write-collection-flow", "--line-transfer-dispatch-flow"]):
                    options = ["--output", tmp + "/absent", *selector, *extra]
                    off = self.call("fpga/next/export.py", options)
                    on = self.call("fpga/next/export.py", options + [FLAG])
                    board_options = ["--tag", "line-read-cli", "--preflight-only", "--variant", variant, *extra]
                    board_off = self.call("simulator/gsim/fpga_next_board.py", board_options)
                    board_on = self.call("simulator/gsim/fpga_next_board.py", board_options + [FLAG])
                    self.assertEqual(on["command"].count(FLAG), 1)
                    self.assertEqual(on["command"][5:], board_on["plan"]["parameters"])
                    self.assertEqual([x for x in on["command"] if x != FLAG], off["command"])
                    config = copy.deepcopy(on["configuration"])
                    self.assertIs(config.pop("line_read_channel"), True)
                    config["name"] = config["name"].removesuffix("-line-read-channel")
                    self.assertEqual(config, off["configuration"])
                    plan = copy.deepcopy(board_on["plan"])
                    self.assertIs(plan["line_read_channel"], True)
                    plan["line_read_channel"] = False
                    plan["parameters"].remove(FLAG)
                    self.assertEqual(plan, board_off["plan"])

    def test_invalid_forms_and_recommended_preset_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="line-read-bad-") as tmp:
            for bad in ([FLAG, FLAG], [FLAG + "=true"], [FLAG + "=false"], [FLAG, "true"]):
                self.call("fpga/next/export.py", ["--output", tmp + "/absent", *bad], False)
                self.call("simulator/gsim/fpga_next_board.py",
                          ["--tag", "line-read-bad", "--preflight-only", *bad], False)
            preset = self.call("fpga/next/performance.py", ["--output", tmp + "/absent"])
            self.assertNotIn(FLAG, preset["command"])
            self.assertNotIn("line_read_channel", preset["configuration"])


if __name__ == "__main__":
    unittest.main()
