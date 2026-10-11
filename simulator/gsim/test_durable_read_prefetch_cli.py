#!/usr/bin/env python3
"""Constructor routing only; never emits RTL or runs the simulator."""
import copy
from pathlib import Path
import tempfile
import unittest
import test_ddr_write_collection_cli as common

RETENTION = "--durable-read-prefetch-candidate"
CAPTURE = "--read-prefetch-behind-store"
PREREQUISITES = ["--prefetch-candidate-cycles", "16", "--store-next-line-prefetch",
                 "--split-prefetch-tracking", "--read-prefetch-dirty-retry",
                 "--read-prefetch-demand-adoption", "--read-prefetch-store-hold",
                 "--independent-demand-admission", "--virtual-ram-load-precheck",
                 "--canonical-virtual-store-overlap"]

class DurableReadPrefetchCliTests(unittest.TestCase):
    call = common.WriteCollectionCliTests.call

    def test_exact_independent_forwarding_and_unchanged_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "absent"
            for selector, variant in (([], "selected"), (["--reference"], "reference"),
                                      (["--storage-candidate"], "candidate")):
                native = ["--output", str(output), *selector, *PREREQUISITES]
                board = ["--tag", "durable-read-cli", "--preflight-only", "--variant", variant, *PREREQUISITES]
                off = self.call("fpga/next/export.py", native)
                off_board = self.call("simulator/gsim/fpga_next_board.py", board)
                for flags in ([RETENTION], [RETENTION, CAPTURE]):
                    on = self.call("fpga/next/export.py", native + flags)
                    on_board = self.call("simulator/gsim/fpga_next_board.py", board + flags)
                    self.assertEqual(on["command"][5:], on_board["plan"]["parameters"])
                    config = copy.deepcopy(on["configuration"])
                    plan = copy.deepcopy(on_board["plan"])
                    for flag in reversed(flags):
                        key = flag[2:].replace("-", "_")
                        self.assertIs(config.pop(key), True)
                        self.assertTrue(config["name"].endswith(flag[1:]))
                        config["name"] = config["name"].removesuffix(flag[1:])
                        self.assertIs(plan[key], True)
                        plan[key] = False
                        plan["parameters"].remove(flag)
                    self.assertEqual(config, off["configuration"])
                    self.assertEqual(plan, off_board["plan"])
                self.assertNotIn("durable_read_prefetch_candidate", off["configuration"])
                self.assertNotIn("read_prefetch_behind_store", off["configuration"])
            self.assertFalse(output.exists())

    def test_missing_prerequisites_duplicate_and_valued_forms_fail(self):
        cases = [[CAPTURE], [*PREREQUISITES, CAPTURE], [*PREREQUISITES, RETENTION, RETENTION],
                 [*PREREQUISITES, RETENTION, CAPTURE, CAPTURE]]
        for missing in PREREQUISITES[2:]:
            cases.append([x for x in PREREQUISITES if x != missing] + [RETENTION])
        for cycles in (1, 3):
            cases.append(["--prefetch-candidate-cycles", str(cycles), *PREREQUISITES[2:], RETENTION])
        for flag in (RETENTION, CAPTURE):
            for value in ("true", "false", "0", "1"):
                cases.append([*PREREQUISITES, RETENTION, flag + "=" + value])
        with tempfile.TemporaryDirectory() as tmp:
            for bad in cases:
                self.call("fpga/next/export.py", ["--output", tmp + "/absent", *bad], False)
                self.call("simulator/gsim/fpga_next_board.py", ["--tag", "durable-read-bad", "--preflight-only", *bad], False)
            self.assertFalse((Path(tmp) / "absent").exists())

if __name__ == "__main__":
    unittest.main()
