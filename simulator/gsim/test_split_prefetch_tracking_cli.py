#!/usr/bin/env python3
"""Host-only exact native/GSIM routing checks; no elaboration or simulator work."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import test_ddr_write_collection_cli as common

ROOT = Path(__file__).resolve().parents[2]
FLAG = "--split-prefetch-tracking"


class SplitPrefetchTrackingCliTests(unittest.TestCase):
    call = common.WriteCollectionCliTests.call

    def test_exact_forwarding_without_coupled_policy_or_lifetime_changes(self):
        with tempfile.TemporaryDirectory(prefix="split-prefetch-cli-") as tmp:
            output = Path(tmp) / "absent"
            for selector, variant in (([], "selected"), (["--reference"], "reference"),
                                      (["--storage-candidate"], "candidate")):
                for cycles in (1, 3, 16):
                    extra = ["--store-next-line-prefetch", "--prefetch-candidate-cycles", str(cycles)]
                    args = ["--output", str(output), *selector, *extra]
                    board_args = ["--tag", "split-prefetch-cli", "--preflight-only",
                                  "--variant", variant, *extra]
                    off = self.call("fpga/next/export.py", args)
                    on = self.call("fpga/next/export.py", args + [FLAG])
                    board_off = self.call("simulator/gsim/fpga_next_board.py", board_args)
                    board_on = self.call("simulator/gsim/fpga_next_board.py", board_args + [FLAG])
                    self.assertEqual(off["status"], "PREFLIGHT_ONLY")
                    self.assertEqual(board_on["status"], "PREFLIGHT_ONLY")
                    self.assertNotIn("split_prefetch_tracking", off["configuration"])
                    self.assertEqual(on["command"].count(FLAG), 1)
                    self.assertEqual(on["command"][5:], board_on["plan"]["parameters"])
                    self.assertEqual([v for v in on["command"] if v != FLAG], off["command"])
                    config = copy.deepcopy(on["configuration"])
                    self.assertIs(config.pop("split_prefetch_tracking"), True)
                    self.assertTrue(config["name"].endswith("-split-prefetch-tracking"))
                    config["name"] = config["name"].removesuffix("-split-prefetch-tracking")
                    self.assertEqual(config, off["configuration"])
                    self.assertEqual(config["prefetch_candidate_cycles"], cycles)
                    plan = copy.deepcopy(board_on["plan"])
                    self.assertIs(plan["split_prefetch_tracking"], True)
                    plan["split_prefetch_tracking"] = False
                    plan["parameters"].remove(FLAG)
                    self.assertEqual(plan, board_off["plan"])
                    self.assertFalse(Path(board_on["output"]).exists())
            self.assertFalse(output.exists())

    def test_missing_store_prefetch_duplicates_and_valued_forms_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="split-prefetch-bad-") as tmp:
            output = Path(tmp) / "absent"
            for bad in ([FLAG], ["--store-next-line-prefetch", FLAG, FLAG],
                        ["--store-next-line-prefetch", FLAG + "=true"],
                        ["--store-next-line-prefetch", FLAG + "=false"],
                        ["--store-next-line-prefetch", FLAG, "true"]):
                native = self.call("fpga/next/export.py", ["--output", str(output), *bad], False)
                board = self.call("simulator/gsim/fpga_next_board.py",
                                  ["--tag", "split-prefetch-bad", "--preflight-only", *bad], False)
                if bad == [FLAG]:
                    self.assertIn(FLAG + " requires --store-next-line-prefetch", native)
                    self.assertIn(FLAG + " requires --store-next-line-prefetch", board)
                self.assertFalse(output.exists())

    def test_all_official_performance_presets_remain_frozen(self):
        expected = json.loads((ROOT / "fpga/next/performance-profile.json").read_text())
        with tempfile.TemporaryDirectory(prefix="split-prefetch-preset-") as tmp:
            for args, key in (([], "on"), (["--disable-posted"], "off"),
                              (["--disable-posted-prefetch"], "legacy-posted")):
                for canonical in (True, False):
                    options = args + ([] if canonical else ["--disable-canonical-store-overlap"])
                    result = self.call("fpga/next/performance.py", ["--output", tmp + "/absent", *options])
                    profile = copy.deepcopy(expected[key])
                    if not canonical:
                        profile["canonical_virtual_store_overlap"] = False
                        profile["name"] = profile["name"].replace("-canonical-virtual-store-overlap", "")
                    self.assertEqual(result["configuration"], profile)
                    self.assertNotIn(FLAG, result["command"])
                    self.assertNotIn("split_prefetch_tracking", result["configuration"])
            self.assertFalse((Path(tmp) / "absent").exists())


if __name__ == "__main__":
    unittest.main()
