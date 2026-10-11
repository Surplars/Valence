#!/usr/bin/env python3
"""Host-only forwarding / frozen-default checks. No RTL build or board claim."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
FLAG = "--ddr-write-collection-flow"


class WriteCollectionCliTests(unittest.TestCase):
    def call(self, script, args, accepted=True):
        r = subprocess.run([sys.executable, "-B", str(ROOT / script), *args], cwd=ROOT,
                           text=True, capture_output=True, timeout=30)
        self.assertEqual(r.returncode, 0 if accepted else 2, r.stdout + r.stderr)
        return json.loads(r.stdout) if accepted else r.stderr

    def test_forwarding_and_unchanged_defaults(self):
        with tempfile.TemporaryDirectory(prefix="ddr-collection-cli-") as tmp:
            output = Path(tmp) / "absent"
            for selector, variant in (([], "selected"), (["--reference"], "reference"),
                                      (["--storage-candidate"], "candidate")):
                args = ["--output", str(output), *selector]
                board_args = ["--tag", "ddr-collection-cli", "--preflight-only", "--variant", variant]
                off = self.call("fpga/next/export.py", args)
                on = self.call("fpga/next/export.py", args + [FLAG])
                board_off = self.call("simulator/gsim/fpga_next_board.py", board_args)
                board_on = self.call("simulator/gsim/fpga_next_board.py", board_args + [FLAG])
                self.assertNotIn("ddr_write_collection_flow", off["configuration"])
                self.assertEqual(on["command"].count(FLAG), 1)
                self.assertEqual(on["command"][5:], board_on["plan"]["parameters"])
                self.assertEqual([v for v in on["command"] if v != FLAG], off["command"])
                config = copy.deepcopy(on["configuration"])
                self.assertIs(config.pop("ddr_write_collection_flow"), True)
                config["name"] = config["name"].removesuffix("-ddr-write-collection-flow")
                self.assertEqual(config, off["configuration"])
                plan = copy.deepcopy(board_on["plan"])
                self.assertIs(plan["ddr_write_collection_flow"], True)
                plan["ddr_write_collection_flow"] = False
                plan["parameters"].remove(FLAG)
                self.assertEqual(plan, board_off["plan"])
                self.assertFalse(Path(board_on["output"]).exists())
            self.assertFalse(output.exists())

    def test_bad_forms_do_not_create_output(self):
        with tempfile.TemporaryDirectory(prefix="ddr-collection-bad-") as tmp:
            for bad in ([FLAG, FLAG], [FLAG + "=true"], [FLAG + "=false"], [FLAG, "true"]):
                self.call("fpga/next/export.py", ["--output", tmp + "/absent", *bad], False)
                self.call("simulator/gsim/fpga_next_board.py",
                          ["--tag", "ddr-collection-bad", "--preflight-only", *bad], False)
            self.assertFalse((Path(tmp) / "absent").exists())

    def test_recommended_profile_is_not_promoted(self):
        expected = json.loads((ROOT / "fpga/next/performance-profile.json").read_text())
        with tempfile.TemporaryDirectory(prefix="ddr-collection-preset-") as tmp:
            result = self.call("fpga/next/performance.py", ["--output", tmp + "/absent"])
            self.assertEqual(result["configuration"], expected["on"])
            self.assertNotIn(FLAG, result["command"])
            self.assertFalse((Path(tmp) / "absent").exists())


if __name__ == "__main__":
    unittest.main()
