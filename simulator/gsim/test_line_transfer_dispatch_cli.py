#!/usr/bin/env python3
"""Host-only independent selector/default checks; no RTL execution."""
import copy
from pathlib import Path
import tempfile
import unittest
import test_ddr_write_collection_cli as collection_cli

FLAG = "--line-transfer-dispatch-flow"


class LineDispatchCliTests(unittest.TestCase):
    call = collection_cli.WriteCollectionCliTests.call

    def test_independent_and_combined_selection(self):
        with tempfile.TemporaryDirectory(prefix="line-dispatch-cli-") as tmp:
            for selector, variant in (([], "selected"), (["--reference"], "reference"),
                                      (["--storage-candidate"], "candidate")):
                for other in ([], [collection_cli.FLAG]):
                    args = ["--output", tmp + "/absent", *selector, *other]
                    board = ["--tag", "line-dispatch-cli", "--preflight-only", "--variant", variant, *other]
                    off = self.call("fpga/next/export.py", args)
                    on = self.call("fpga/next/export.py", args + [FLAG])
                    board_off = self.call("simulator/gsim/fpga_next_board.py", board)
                    board_on = self.call("simulator/gsim/fpga_next_board.py", board + [FLAG])
                    self.assertNotIn("line_transfer_dispatch_flow", off["configuration"])
                    self.assertEqual(on["command"].count(FLAG), 1)
                    self.assertEqual(on["command"][5:], board_on["plan"]["parameters"])
                    self.assertEqual([v for v in on["command"] if v != FLAG], off["command"])
                    config = copy.deepcopy(on["configuration"])
                    self.assertIs(config.pop("line_transfer_dispatch_flow"), True)
                    config["name"] = config["name"].removesuffix("-line-transfer-dispatch-flow")
                    self.assertEqual(config, off["configuration"])
                    plan = copy.deepcopy(board_on["plan"])
                    self.assertIs(plan["line_transfer_dispatch_flow"], True)
                    plan["line_transfer_dispatch_flow"] = False
                    plan["parameters"].remove(FLAG)
                    self.assertEqual(plan, board_off["plan"])
            self.assertFalse((Path(tmp) / "absent").exists())

    def test_bad_forms_and_preset(self):
        with tempfile.TemporaryDirectory(prefix="line-dispatch-bad-") as tmp:
            for bad in ([FLAG, FLAG], [FLAG + "=true"], [FLAG + "=false"], [FLAG, "true"]):
                self.call("fpga/next/export.py", ["--output", tmp + "/absent", *bad], False)
                self.call("simulator/gsim/fpga_next_board.py",
                          ["--tag", "line-dispatch-bad", "--preflight-only", *bad], False)
            preset = self.call("fpga/next/performance.py", ["--output", tmp + "/absent"])
            self.assertNotIn(FLAG, preset["command"])
            self.assertNotIn("line_transfer_dispatch_flow", preset["configuration"])
            self.assertFalse((Path(tmp) / "absent").exists())


if __name__ == "__main__":
    unittest.main()
