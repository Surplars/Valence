"""Host-only entry-point, fail-closed selector and frozen preset checks."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class BackendCapacityCliTests(unittest.TestCase):
    def call(self, entry, options, ok=True):
        p = subprocess.run([sys.executable, "-B", str(ROOT / entry), *options], cwd=ROOT,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0 if ok else 2, p.stdout + p.stderr)
        return json.loads(p.stdout) if ok else None

    def test_native_and_gsim_use_same_explicit_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            for rob, regs in ((16, 48), (16, 64), (32, 64), (64, 64), (64, 48)):
                flags = ["--rob-entries", str(rob), "--physical-regs", str(regs), "--lsu-entries", "4"]
                native = self.call("fpga/next/export.py", ["--output", tmp + "/rtl", *flags])
                board = self.call("simulator/gsim/fpga_next_board.py",
                                  ["--tag", "rob-capacity-host-test", "--preflight-only", "--variant", "selected", *flags])
                self.assertEqual(native["configuration"]["rob_entries"], rob)
                self.assertEqual(native["configuration"]["physical_registers"], regs)
                self.assertEqual(board["plan"]["rob_entries_override"], rob)
                self.assertEqual(board["plan"]["physical_regs_override"], regs)
                self.assertEqual(native["command"][5:], board["plan"]["parameters"])
                self.assertFalse(Path(board["output"]).exists())
            self.assertFalse((Path(tmp) / "rtl").exists())

    def test_omitted_capacity_options_preserve_native_variants_and_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            for selector in ([], ["--reference"], ["--storage-candidate"]):
                result = self.call("fpga/next/export.py", ["--output", tmp + "/rtl", *selector])
                self.assertEqual(result["configuration"]["rob_entries"], 16)
                self.assertEqual(result["configuration"]["physical_registers"], 48)
                self.assertFalse(any(x.startswith(("--rob-entries", "--physical-regs")) for x in result["command"]))
            expected = json.loads((ROOT / "fpga/next/performance-profile.json").read_text())["on"]
            preset = self.call("fpga/next/performance.py", ["--output", tmp + "/rtl"])
            self.assertEqual(preset["configuration"], expected)
            self.assertEqual((expected["rob_entries"], expected["physical_registers"], expected["lsu_entries"]), (16, 48, 4))

    def test_invalid_conflicting_or_still_unsupported_dimensions_rejected(self):
        bad = [["--rob-entries", str(n)] for n in (0, 8, 24, 128)]
        bad += [["--physical-regs", str(n)] for n in (32, 47, 96, 256)]
        bad += [["--rob-entries=16", "--rob-entries=64"], ["--physical-regs=64", "--physical-regs=64"],
                ["--lsu-entries=8"], ["--posted-store-merge", "--prechecked-data-flow"],
                ["--canonical-virtual-store-overlap"], ["--posted-prefetch-head-offer"]]
        with tempfile.TemporaryDirectory() as tmp:
            for flags in bad:
                self.call("fpga/next/export.py", ["--output", tmp + "/rtl", *flags], ok=False)
                self.call("simulator/gsim/fpga_next_board.py",
                          ["--tag", "rob-capacity-rejected", "--preflight-only", *flags], ok=False)
            for flags in (["--rob-entries=64"], ["--physical-regs=64"]):
                self.call("fpga/next/performance.py", ["--output", tmp + "/rtl", *flags], ok=False)
            self.assertFalse((Path(tmp) / "rtl").exists())


if __name__ == "__main__":
    unittest.main()
