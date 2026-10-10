#!/usr/bin/env python3
"""Host-only option routing; this neither compiles hardware nor claims CPU behavior."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
COMMON = ["--virtual-ram-load-precheck", "--data-translation-entries=16",
          "--prepared-store-lookahead", "--store-next-line-prefetch", "--store-prefetch-mru-insertion",
          "--lsu-entries=4", "--physical-load-ingress-flow", "--load-order-older-retire", "--fetch-previous-packet"]


class Selection(unittest.TestCase):
    def call(self, path, options, ok=True):
        r = subprocess.run([sys.executable, str(ROOT / path), *options], cwd=ROOT,
                           text=True, capture_output=True)
        self.assertEqual(r.returncode == 0, ok, r.stderr)
        return json.loads(r.stdout) if ok else r.stderr

    def test_board_off_on(self):
        options = ["--preflight-only", "--tag=posted-cpu-source-only", "--variant=selected", *COMMON]
        off = self.call("simulator/gsim/fpga_next_board.py", options)
        on = self.call("simulator/gsim/fpga_next_board.py", options + ["--posted-store-merge"])
        self.assertEqual(on["status"], "PREFLIGHT_ONLY")
        self.assertFalse(off["plan"]["posted_store_merge"])
        self.assertTrue(on["plan"]["posted_store_merge"])
        self.assertEqual(on["plan"]["parameters"], off["plan"]["parameters"] + ["--posted-store-merge"])
        for k in ("data_translation_entries", "instruction_translation_entries", "pte_cache_entries", "guest_suite"):
            self.assertEqual(off["plan"][k], on["plan"][k])

    def test_export_off_on(self):
        with tempfile.TemporaryDirectory(prefix="posted-cpu-export-") as d:
            options = ["--output", str(Path(d) / "no-output"), *COMMON]
            off = self.call("fpga/next/export.py", options)
            on = self.call("fpga/next/export.py", options + ["--posted-store-merge"])
            self.assertEqual(on["status"], "PREFLIGHT_ONLY")
            self.assertEqual(on["profile"], off["profile"] + "-posted-store-merge")
            self.assertFalse(off["posted_store_merge"])
            self.assertTrue(on["posted_store_merge"])
            self.assertFalse((Path(d) / "no-output").exists())

    def test_scalar_wrapper_routes_selector(self):
        # The Python preflight alone cannot detect a selector silently dropped by
        # the GSIM-specific Scala wrapper between profile and production board.
        entry = (ROOT / "src/test/scala/ooo/FpgaNextBoardGsimMain.scala").read_text()
        wrapper = (ROOT / "src/test/scala/ooo/BoardSocGsimMain.scala").read_text()
        self.assertIn("postedStoreMerge = c.postedStoreMerge", entry)
        self.assertIn("postedStoreMerge: Boolean = false", wrapper)
        self.assertIn("postedStoreMerge = postedStoreMerge", wrapper)

    def test_response_flow_cli_routes_remain_independent(self):
        # Co-routing is checked only as CLI syntax; both-enabled hardware is unqualified.
        for path, base in [
            ("simulator/gsim/fpga_next_board.py", ["--preflight-only", "--tag=posted-delivery-cli-only"]),
            ("fpga/next/export.py", ["--output=/tmp/posted-delivery-cli-only-uncreated"]),
        ]:
            for posted in (False, True):
                for response_flow in (False, True):
                    flags = (["--posted-store-merge"] if posted else []) + (
                        ["--translated-response-empty-flow"] if response_flow else [])
                    result = self.call(path, base + COMMON + flags)
                    plan = result.get("plan", result)
                    self.assertEqual(plan["posted_store_merge"], posted)
                    self.assertEqual(plan["translated_response_empty_flow"], response_flow)
                    if "parameters" in plan:
                        for flag in flags:
                            self.assertEqual(plan["parameters"].count(flag), 1)

    def test_shared_board_builder_preserves_response_flow(self):
        entry = (ROOT / "src/test/scala/ooo/FpgaNextBoardGsimMain.scala").read_text()
        self.assertIn("def build(c: FpgaNextConfig, lineageProbes: Boolean = false): BoardSocGsim", entry)
        self.assertIn("lineageProfile = if (lineageProbes) Some(c) else None", entry)
        self.assertIn("translatedResponseEmptyFlow = c.translatedResponseEmptyFlow", entry)
        self.assertIn("ChiselStage.emitCHIRRTLFile(FpgaNextBoardGsim.build(c)", entry)

    def test_unqualified_combination_rejected(self):
        for path, base in [("simulator/gsim/fpga_next_board.py", ["--tag=posted-cpu-invalid", "--preflight-only"]),
                           ("fpga/next/export.py", ["--output=/tmp/posted-cpu-invalid-uncreated"])]:
            error = self.call(path, base + ["--posted-store-merge", "--prechecked-data-flow"], False)
            self.assertIn("--posted-store-merge excludes --prechecked-data-flow", error)


if __name__ == "__main__":
    unittest.main()
