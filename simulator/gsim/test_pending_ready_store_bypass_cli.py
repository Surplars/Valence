#!/usr/bin/env python3
"""Host-only exact routing/default contracts; no hardware qualification."""
import copy
from pathlib import Path
import tempfile
import unittest

import test_ddr_write_collection_cli as common

FLAG = "--pending-ready-store-bypass"
PREREQUISITES = ["--virtual-ram-load-precheck", "--canonical-virtual-store-overlap",
                 "--frozen-store-proof-transport", "--pending-virtual-store-proof",
                 "--bound-head-store-overlap", "--lsu-entries", "4",
                 "--data-translation-entries", "16", "--load-order-older-retire"]


class PendingReadyStoreBypassCliTests(unittest.TestCase):
    call = common.WriteCollectionCliTests.call

    def test_only_one_explicit_policy_changes_and_both_proof_capacities_route(self):
        with tempfile.TemporaryDirectory(prefix="ready-store-cli-") as tmp:
            for slots in (1, 2):
                extra = [*PREREQUISITES]
                if slots != 1:
                    extra += ["--pending-virtual-store-proof-slots", str(slots)]
                native = ["--output", tmp + "/absent", *extra]
                board = ["--tag", "ready-store-cli", "--preflight-only", "--variant", "selected", *extra]
                off = self.call("fpga/next/export.py", native)
                on = self.call("fpga/next/export.py", native + [FLAG])
                board_off = self.call("simulator/gsim/fpga_next_board.py", board)
                board_on = self.call("simulator/gsim/fpga_next_board.py", board + [FLAG])
                self.assertEqual(on["command"].count(FLAG), 1)
                self.assertEqual(on["command"][5:], board_on["plan"]["parameters"])
                self.assertEqual([x for x in on["command"] if x != FLAG], off["command"])
                config = copy.deepcopy(on["configuration"])
                self.assertIs(config.pop("pending_ready_store_bypass"), True)
                config["name"] = config["name"].replace("-pending-ready-store-bypass", "")
                self.assertEqual(config, off["configuration"])
                plan = copy.deepcopy(board_on["plan"])
                self.assertIs(plan["pending_ready_store_bypass"], True)
                plan["pending_ready_store_bypass"] = False
                plan["parameters"].remove(FLAG)
                self.assertEqual(plan, board_off["plan"])
                self.assertFalse(Path(board_on["output"]).exists())
            self.assertFalse(Path(tmp, "absent").exists())

    def test_requires_b2_and_rejects_duplicates_valued_and_unknown_forms(self):
        bad = [[FLAG], [*PREREQUISITES, FLAG, FLAG],
               *[[*PREREQUISITES, FLAG + "=" + value] for value in ("true", "false", "0", "1")],
               [*[x for x in PREREQUISITES if x != "--bound-head-store-overlap"], FLAG],
               [*PREREQUISITES, FLAG + "-typo"]]
        with tempfile.TemporaryDirectory(prefix="ready-store-cli-bad-") as tmp:
            for options in bad:
                self.call("fpga/next/export.py", ["--output", tmp + "/absent", *options], False)
                self.call("simulator/gsim/fpga_next_board.py",
                          ["--tag", "ready-store-cli-bad", "--preflight-only", *options], False)
            self.assertFalse(Path(tmp, "absent").exists())


if __name__ == "__main__":
    unittest.main()
