#!/usr/bin/env python3
"""Fail-closed board/top source-binding tests, no Vivado or HDL behavior claim."""
import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('export',ROOT/'fpga/next/export.py')
export=importlib.util.module_from_spec(spec);spec.loader.exec_module(export)
class Binding(unittest.TestCase):
    def test_no_extra_pins(self):
        text=export.bscan_board_wrapper((ROOT/'fpga/next/soc_top_fpga_next_ddr.sv').read_text())
        self.assertNotIn('input wire jtag_',text);self.assertNotIn('output wire jtag_',text)
        self.assertIn('wire jtag_debug_por_n = ~board_reset;',text)
    def test_legacy_preserves_media(self):
        original=(ROOT/'fpga/zu15eg/soc_top_gmac_ddr.sv').read_text()
        text=export.bscan_legacy_board_wrapper(original)
        self.assertNotIn('input wire jtag_',text)
        self.assertIn('.jtag_debugPorN(~board_reset)',text)
        # Everything outside the replaced SoC instance prefix is byte-preserved.
        original_prefix,original_tail=original.split('    BoardSocTop u_soc (')
        self.assertTrue(text.startswith(original_prefix))
        self.assertTrue(text.endswith(original_tail))
    def test_unknown_source_fails(self):
        with self.assertRaises(RuntimeError): export.bscan_board_wrapper('module changed(); endmodule')
        with self.assertRaises(RuntimeError): export.bscan_legacy_board_wrapper('module changed(); endmodule')
    def test_named_port_mismatch_fails(self):
        with self.assertRaises(RuntimeError): export.check_wrapper_ports('FpgaNextSocTop u_soc (.a(a),.extra(b));','module FpgaNextSocTop(input a);')
    def test_named_port_missing_fails(self):
        with self.assertRaises(RuntimeError): export.check_wrapper_ports('FpgaNextSocTop u_soc (.a(a));','module FpgaNextSocTop(input a, output b);')
    def test_exact_port_match(self):
        self.assertEqual(export.check_wrapper_ports('FpgaNextSocTop u_soc (.a(a),.b());','module FpgaNextSocTop(input a, output b);'),2)
if __name__=='__main__':unittest.main()
