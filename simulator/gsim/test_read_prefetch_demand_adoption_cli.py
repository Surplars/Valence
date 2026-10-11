#!/usr/bin/env python3
"""Host-only exact native/GSIM routing checks; no elaboration or simulator work."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import test_ddr_write_collection_cli as common

ROOT = Path(__file__).resolve().parents[2]
FLAG = "--read-prefetch-demand-adoption"
PREREQUISITES = ["--store-next-line-prefetch", "--split-prefetch-tracking",
                 "--independent-demand-admission", "--virtual-ram-load-precheck",
                 "--canonical-virtual-store-overlap"]


class ReadPrefetchDemandAdoptionCliTests(unittest.TestCase):
    call = common.WriteCollectionCliTests.call

    def test_exact_forwarding_preserves_lifetime_capacities_and_other_policies(self):
        with tempfile.TemporaryDirectory(prefix="read-pf-demand-adoption-cli-") as tmp:
            output = Path(tmp) / "absent"
            for selector, variant in (([], "selected"), (["--reference"], "reference"),
                                      (["--storage-candidate"], "candidate")):
                for cycles in (1, 3, 16):
                    extra = [*PREREQUISITES, "--prefetch-candidate-cycles", str(cycles)]
                    if cycles == 16:
                        extra += ["--store-prefetch-mru-insertion", "--store-prefetch-lru-victim",
                                  "--distinct-way-release"]
                    args = ["--output", str(output), *selector, *extra]
                    board_args = ["--tag", "read-pf-demand-adoption-cli", "--preflight-only",
                                  "--variant", variant, *extra]
                    off = self.call("fpga/next/export.py", args)
                    on = self.call("fpga/next/export.py", args + [FLAG])
                    board_off = self.call("simulator/gsim/fpga_next_board.py", board_args)
                    board_on = self.call("simulator/gsim/fpga_next_board.py", board_args + [FLAG])
                    self.assertEqual(off["status"], "PREFLIGHT_ONLY")
                    self.assertEqual(board_on["status"], "PREFLIGHT_ONLY")
                    self.assertNotIn("read_prefetch_demand_adoption", off["configuration"])
                    self.assertEqual(on["command"].count(FLAG), 1)
                    self.assertEqual(on["command"][5:], board_on["plan"]["parameters"])
                    self.assertEqual([v for v in on["command"] if v != FLAG], off["command"])
                    config = copy.deepcopy(on["configuration"])
                    self.assertIs(config.pop("read_prefetch_demand_adoption"), True)
                    self.assertTrue(config["name"].endswith("-read-prefetch-demand-adoption"))
                    config["name"] = config["name"].removesuffix("-read-prefetch-demand-adoption")
                    self.assertEqual(config, off["configuration"])
                    self.assertEqual(config["prefetch_candidate_cycles"], cycles)
                    plan = copy.deepcopy(board_on["plan"])
                    self.assertIs(plan["read_prefetch_demand_adoption"], True)
                    plan["read_prefetch_demand_adoption"] = False
                    plan["parameters"].remove(FLAG)
                    self.assertEqual(plan, board_off["plan"])
                    self.assertFalse(Path(board_on["output"]).exists())
            self.assertFalse(output.exists())

    def test_missing_prerequisites_duplicates_and_valued_forms_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="read-pf-demand-adoption-bad-") as tmp:
            output = Path(tmp) / "absent"
            bad_forms = [[FLAG], [*PREREQUISITES, FLAG, FLAG],
                         *[[x for x in PREREQUISITES if x != missing] + [FLAG]
                           for missing in PREREQUISITES],
                         *[[*PREREQUISITES, FLAG + "=" + value]
                           for value in ("true", "false", "0", "1")],
                         [*PREREQUISITES, FLAG, "true"], [*PREREQUISITES, FLAG + "-typo"]]
            for bad in bad_forms:
                native = self.call("fpga/next/export.py", ["--output", str(output), *bad], False)
                board = self.call("simulator/gsim/fpga_next_board.py",
                                  ["--tag", "read-pf-demand-adoption-bad", "--preflight-only", *bad], False)
                self.assertFalse(output.exists())

    def test_published_performance_and_board_presets_stay_frozen(self):
        performance = json.loads((ROOT / "fpga/next/performance-profile.json").read_text())
        board = json.loads((ROOT / "fpga/next/board-performance-profile.json").read_text())
        release = json.loads((ROOT / "fpga/next/board-release-profile.json").read_text())
        with tempfile.TemporaryDirectory(prefix="read-pf-demand-adoption-preset-") as tmp:
            cases = [("fpga/next/performance.py", options, performance[key])
                     for options, key in (([], "on"), (["--disable-posted"], "off"),
                                          (["--disable-posted-prefetch"], "legacy-posted"))]
            cases += [("fpga/next/board_profile.py", ["--mode", mode],
                       board["modes"][mode]["export_profile"]) for mode in ("A", "B")]
            cases += [("fpga/next/board_release.py", [], release["export_profile"])]
            for script, options, expected in cases:
                result = self.call(script, ["--output", tmp + "/absent", *options])
                self.assertEqual(result["configuration"], expected)
                self.assertNotIn(FLAG, result["command"])
                self.assertNotIn("read_prefetch_demand_adoption", result["configuration"])
            self.assertFalse((Path(tmp) / "absent").exists())


if __name__ == "__main__":
    unittest.main()
