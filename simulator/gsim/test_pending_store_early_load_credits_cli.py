#!/usr/bin/env python3
"""Host-only routing, strict defaults and bounded-capacity checks; no RTL build."""
import copy
from pathlib import Path
import tempfile
import unittest

import test_ddr_write_collection_cli as common
from test_pending_ready_store_bypass_cli import PREREQUISITES

FLAG = "--pending-store-early-load-credits"


class PendingStoreEarlyLoadCreditsCliTests(unittest.TestCase):
    call = common.WriteCollectionCliTests.call

    def test_independent_row_and_credit_capacities_route_exactly(self):
        with tempfile.TemporaryDirectory(prefix="early-credit-cli-") as tmp:
            for rows in (1, 2):
                base = [*PREREQUISITES]
                if rows == 2:
                    base += ["--pending-virtual-store-proof-slots", "2"]
                native = ["--output", tmp + "/absent", *base]
                board = ["--tag", "early-credit-cli", "--preflight-only", "--variant", "selected", *base]
                off = self.call("fpga/next/export.py", native)
                self.assertEqual(off["pending_store_early_load_credits"], 1)
                self.assertNotIn("pending_store_early_load_credits", off["configuration"])
                for credits in (1, 2):
                    on = self.call("fpga/next/export.py", native + [FLAG, str(credits)])
                    plan = self.call("simulator/gsim/fpga_next_board.py", board + [FLAG, str(credits)])
                    self.assertEqual(on["command"][5:], plan["plan"]["parameters"])
                    self.assertEqual(on["command"].count(f"{FLAG}={credits}"), 1)
                    self.assertEqual(plan["plan"]["pending_store_early_load_credits"], credits)
                    configuration = copy.deepcopy(on["configuration"])
                    if credits == 2:
                        self.assertEqual(configuration.pop("pending_store_early_load_credits"), 2)
                        configuration["name"] = configuration["name"].replace(
                            "-pending-store-early-load-credits2", "")
                    self.assertEqual(configuration, off["configuration"])
                    self.assertFalse(Path(plan["output"]).exists())
            self.assertFalse(Path(tmp, "absent").exists())

    def test_capacity_prerequisite_duplicates_and_values_fail_closed(self):
        bad = [[FLAG, "2"],
               *[[*PREREQUISITES, FLAG, value] for value in ("0", "3", "true", "false")],
               [*PREREQUISITES, FLAG, "2", FLAG, "2"],
               [*PREREQUISITES, FLAG + "=1", FLAG + "=2"],
               [*PREREQUISITES, FLAG + "-typo=2"]]
        with tempfile.TemporaryDirectory(prefix="early-credit-cli-bad-") as tmp:
            for options in bad:
                self.call("fpga/next/export.py", ["--output", tmp + "/absent", *options], False)
                self.call("simulator/gsim/fpga_next_board.py",
                          ["--tag", "early-credit-cli-bad", "--preflight-only", *options], False)
            self.assertFalse(Path(tmp, "absent").exists())


if __name__ == "__main__":
    unittest.main()
