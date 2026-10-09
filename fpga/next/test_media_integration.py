"""Host-only integration recipe tests; no hardware simulation or Vivado claim."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export as exporter
import media_integration as media

ROOT = Path(__file__).resolve().parents[2]


class NativeMediaIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "export"
        self.output.mkdir()
        (self.output / "board").mkdir()
        self.wrapper = (ROOT / "fpga/next/soc_top_fpga_next_ddr.sv").read_text()
        (self.output / "board/soc_top_fpga_next_ddr.sv").write_text(self.wrapper)

    def test_exact_native_source_closure(self):
        before = exporter.sources()
        self.assertTrue(set(media.INPUTS).issubset(before))
        self.assertIn("fpga/next/media_integration.py", before)
        self.assertIn("src/main/resources/debug/ValenceBscanDebugPort.sv", before)

    def test_package_pins_are_preserved_without_legacy_timing(self):
        original = (ROOT / "fpga/zu15eg/native_gmac_pins.xdc").read_text()
        pins = media.pin_only_constraints(original)
        self.assertEqual(re.findall(r"^set_property .*$", original, re.M),
                         re.findall(r"^set_property .*$", pins, re.M))
        self.assertNotRegex(pins, r"(?m)^\s*(create_clock|set_(input|output)_delay|set_clock_groups)")
        self.assertEqual(len(re.findall(r"^set_property PACKAGE_PIN", pins, re.M)), 15)
        # Frozen independently from the reviewed native-enabled export.
        self.assertEqual(hashlib.sha256(pins.encode()).hexdigest(),
                         "ac8760aa578496c7f6603d5e8038bee8a441f4b1f94f264fd5125a13301e2971")

    def test_changed_pin_is_rejected(self):
        original = (ROOT / "fpga/zu15eg/native_gmac_pins.xdc").read_text()
        with self.assertRaisesRegex(RuntimeError, "pin map"):
            media.pin_only_constraints(original.replace("PACKAGE_PIN Y1 ", "PACKAGE_PIN Y9 "))

    def test_changed_pin_timing_boundary_is_rejected(self):
        original = (ROOT / "fpga/zu15eg/native_gmac_pins.xdc").read_text()
        with self.assertRaisesRegex(RuntimeError, "boundary changed"):
            media.pin_only_constraints(original.replace("period 8.000", "period 40.000"))

    def test_hidden_pin_section_exception_is_rejected(self):
        original = (ROOT / "fpga/zu15eg/native_gmac_pins.xdc").read_text()
        with self.assertRaisesRegex(RuntimeError, "unexpected timing"):
            media.pin_only_constraints("set_false_path -from [all_clocks]\n" + original)

    def test_extra_unbraced_pin_override_is_rejected(self):
        original = (ROOT / "fpga/zu15eg/native_gmac_pins.xdc").read_text()
        changed = original.replace("set_property IOSTANDARD",
            "set_property PACKAGE_PIN Y9 [get_ports eth_mdc]\nset_property IOSTANDARD")
        with self.assertRaises(RuntimeError):
            media.pin_only_constraints(changed)

    def test_semicolon_appended_timing_exception_is_rejected(self):
        original = (ROOT / "fpga/zu15eg/native_gmac_pins.xdc").read_text()
        statement = "set_property DRIVE 8 [get_ports {eth_txc eth_tx_ctl eth_txd[*] eth_mdc eth_reset_gate}]"
        with self.assertRaises(RuntimeError):
            media.pin_only_constraints(original.replace(statement,
                statement + "; set_false_path -from [all_clocks]"))

    def test_duplicate_or_extra_braced_pin_is_rejected(self):
        original = (ROOT / "fpga/zu15eg/native_gmac_pins.xdc").read_text()
        for statement in ("set_property PACKAGE_PIN Y1 [get_ports {eth_mdc}]",
                          "set_property PACKAGE_PIN Y9 [get_ports {eth_mdc}]",
                          "set_property PACKAGE_PIN Y9 [get_ports {unreviewed_port}]"):
            with self.subTest(statement=statement), self.assertRaises(RuntimeError):
                media.pin_only_constraints(statement + "\n" + original)

    def test_changed_pin_statement_syntax_is_rejected(self):
        original = (ROOT / "fpga/zu15eg/native_gmac_pins.xdc").read_text()
        statement = "set_property PACKAGE_PIN Y1 [get_ports {eth_mdc}]"
        for replacement in ("set_property PACKAGE_PIN Y1 [get_ports eth_mdc]",
                            'set_property PACKAGE_PIN Y1 [get_ports "eth_mdc"]',
                            "set_property -dict {PACKAGE_PIN Y1} [get_ports {eth_mdc}]",
                            "set_property\tPACKAGE_PIN Y1 [get_ports {eth_mdc}]",
                            statement + ";", statement + " # inline comment"):
            with self.subTest(replacement=replacement), self.assertRaises(RuntimeError):
                media.pin_only_constraints(original.replace(statement, replacement))

    def test_missing_pin_is_rejected(self):
        original = (ROOT / "fpga/zu15eg/native_gmac_pins.xdc").read_text()
        with self.assertRaises(RuntimeError):
            media.pin_only_constraints(original.replace("set_property PACKAGE_PIN Y1 [get_ports {eth_mdc}]\n", ""))

    def test_changed_electrical_or_control_value_is_rejected(self):
        original = (ROOT / "fpga/zu15eg/native_gmac_pins.xdc").read_text()
        for before, after in (("IOSTANDARD LVCMOS18", "IOSTANDARD LVCMOS33"),
                              ("DRIVE 8", "DRIVE 12"), ("SLEW FAST", "SLEW SLOW"),
                              ("UNAVAILABLE_DURING_CALIBRATION TRUE", "UNAVAILABLE_DURING_CALIBRATION FALSE")):
            with self.subTest(property=before), self.assertRaises(RuntimeError):
                media.pin_only_constraints(original.replace(before, after))

    def test_changed_electrical_or_control_targets_are_rejected(self):
        original = (ROOT / "fpga/zu15eg/native_gmac_pins.xdc").read_text()
        for statement in ("set_property DRIVE 8 [get_ports {eth_txc eth_tx_ctl eth_txd[*] eth_mdc eth_reset_gate}]",
                          "set_property UNAVAILABLE_DURING_CALIBRATION TRUE [get_ports {eth_txd[1]}]"):
            with self.subTest(statement=statement), self.assertRaises(RuntimeError):
                replacement = re.sub(r"\[get_ports .*", "[get_ports {*}]", statement)
                media.pin_only_constraints(original.replace(statement, replacement))

    def test_missing_duplicate_or_malformed_property_is_rejected(self):
        original = (ROOT / "fpga/zu15eg/native_gmac_pins.xdc").read_text()
        statement = "set_property SLEW FAST [get_ports {eth_txc eth_tx_ctl eth_txd[*]}]"
        for replacement in ("", statement + "\n" + statement,
                            statement[:-1], statement.replace("FAST", "[expr 1]"),
                            statement + "; set_property PACKAGE_PIN Y9 [get_ports eth_mdc]"):
            with self.subTest(replacement=replacement), self.assertRaises(RuntimeError):
                media.pin_only_constraints(original.replace(statement, replacement))

    def test_unreviewed_property_is_rejected(self):
        original = (ROOT / "fpga/zu15eg/native_gmac_pins.xdc").read_text()
        with self.assertRaises(RuntimeError):
            media.pin_only_constraints("set_property PULLUP TRUE [get_ports {eth_mdio}]\n" + original)

    def test_line_continuations_cannot_hide_statements(self):
        original = (ROOT / "fpga/zu15eg/native_gmac_pins.xdc").read_text()
        statement = "set_property PACKAGE_PIN Y1 [get_ports {eth_mdc}]"
        for prefix in ("# continued comment \\\n", "set_property \\\n", "# carriage return\r"):
            with self.subTest(prefix=prefix), self.assertRaises(RuntimeError):
                media.pin_only_constraints(original.replace(statement, prefix + statement))

    def test_clock_boundary_must_be_a_complete_statement(self):
        original = (ROOT / "fpga/zu15eg/native_gmac_pins.xdc").read_text()
        marker = "create_clock -name phy_rx -period 8.000 -waveform {0 4} [get_ports eth_rxc]"
        for replacement in ("# " + marker, marker + "; set_false_path -from [all_clocks]",
                            marker + "\n" + marker, marker + " extra", marker + "\\"):
            with self.subTest(replacement=replacement), self.assertRaisesRegex(RuntimeError, "boundary changed"):
                media.pin_only_constraints(original.replace(marker, replacement))

    def test_standalone_comments_blank_lines_and_crlf_are_preserved(self):
        original = (ROOT / "fpga/zu15eg/native_gmac_pins.xdc").read_text()
        changed = ("\t# reviewed comment\n\n" + original).replace("\n", "\r\n")
        pins = media.pin_only_constraints(changed)
        expected = changed[:changed.index("create_clock")]
        self.assertEqual(pins, expected +
                         "# Timing belongs to trispeed_board_constraints.tcl, one explicit rate per design.\n")

    def test_stage_is_hash_bound_and_unqualified(self):
        result = media.stage(ROOT, self.output)
        record = json.loads((self.output / result["manifest"]).read_text())
        self.assertFalse(result["physical_qualification"])
        self.assertEqual(record["rates_mbps"], [10, 100, 1000])
        for name, digest in record["artifacts_sha256"].items():
            self.assertEqual(media.sha(self.output / name), digest)
        for name in (*media.NATIVE_SOURCES, *media.NATIVE_CONSTRAINTS):
            self.assertEqual(media.sha(self.output / "board" / name), media.sha(ROOT / "fpga/zu15eg" / name))
        self.assertNotIn("board/native_rgmii_trispeed.sv", record["native_sources"])
        self.assertFalse(any(record[name] for name in ("synthesis_run", "route_run", "bit_generated", "on_board_verified")))
        self.assertTrue((self.output / "board/require_trispeed.tcl").is_file())

    def test_stage_rejects_native_source_drift(self):
        hashes = media.source_hashes(ROOT)
        with mock.patch.object(media, "source_hashes", side_effect=[hashes, {**hashes, "drift": "bad"}]):
            with self.assertRaisesRegex(RuntimeError, "changed while staging"):
                media.stage(ROOT, self.output)

    def test_missing_matched_wrapper_is_rejected(self):
        (self.output / "board/soc_top_fpga_next_ddr.sv").unlink()
        with self.assertRaisesRegex(RuntimeError, "matched tri-speed wrapper"):
            media.stage(ROOT, self.output)

    def test_bscan_removes_only_reserved_package_ports(self):
        text = exporter.bscan_board_wrapper(self.wrapper)
        self.assertNotIn("input wire jtag_tck", text)
        self.assertIn("wire jtag_debug_por_n = ~board_reset", text)
        self.assertIn(".io_nativeGmac_triSpeedRgmii_requestedSpeed(requested_speed)", text)
        self.assertIn(".io_nativeGmac_triSpeedRgmii_appliedSpeed(applied_speed)", text)
        self.assertIn(".io_nativeGmac_triSpeedRgmii_rxDrained(media_rx_drained)", text)
        self.assertIn(".jtag_debugPorN(jtag_debug_por_n)", text)

    def test_wrapper_port_mismatch_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "named-port mismatch"):
            exporter.check_wrapper_ports(self.wrapper, "module FpgaNextSocTop(input clock); endmodule")

    def test_export_staging_flag_matrix_with_mock_emitter(self):
        # This exercises Python branching with a deliberately synthetic emitter.
        # It is NOT Chisel elaboration or RTL qualification. A real paired export
        # must separately establish the generated top's actual named ports.
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True)
        for trispeed, bscan in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(trispeed=trispeed, bscan=bscan):
                output = Path(self.temp.name) / f"mock-export-{trispeed}-{bscan}"
                def emit(command, **kwargs):
                    rtl = Path(command[4]); rtl.mkdir()
                    wrapper = self.wrapper if trispeed else exporter.bscan_legacy_board_wrapper(
                        (ROOT / "fpga/zu15eg/soc_top_gmac_ddr.sv").read_text())
                    instance = re.search(r"FpgaNextSocTop\s+u_soc\s*\((.*?)\);", wrapper, re.S).group(1)
                    ports = re.findall(r"\.([A-Za-z_][A-Za-z0-9_$]*)\s*\(", instance)
                    (rtl / "FpgaNextSocTop.sv").write_text("module FpgaNextSocTop(" +
                        ",".join("input " + name for name in ports) + "); endmodule\n")
                    if bscan:
                        for name in ("ValenceJtagDebugPort.sv", "ValenceBscanDebugPort.sv"):
                            (rtl / name).write_text("// synthetic emitter fixture, not hardware\n")
                    return subprocess.CompletedProcess(command, 0)
                args = ["export.py", "--output", str(output), "--emit"]
                if trispeed: args.append("--experimental-trispeed-ethernet")
                if bscan: args.extend(["--experimental-jtag-bscan", "2"])
                with mock.patch.object(sys, "argv", args), mock.patch.object(exporter.subprocess, "run", emit), \
                        mock.patch.object(exporter.subprocess, "check_output", return_value=head), \
                        contextlib.redirect_stdout(io.StringIO()):
                    exporter.main()
                receipt = json.loads((output / "receipt.json").read_text())
                self.assertEqual("tri_speed_native_integration" in receipt, trispeed)
                self.assertEqual("required_post_synthesis_gate" in receipt, bscan)
                self.assertEqual((output / "board").exists(), trispeed or bscan)
                self.assertEqual(receipt["profile"]["tri_speed_tx_frame_slots"], 2 if trispeed else 1)
                self.assertEqual(receipt["profile"]["bscan_chain"], 2 if bscan else None)
                self.assertFalse(receipt["physical_qualification"])
                filelist = (output / "synthesis-files.f").read_text()
                self.assertEqual("ValenceBscanDebugPort.sv" in filelist, bscan)


TCL_MOCKS = r"""
array set periods {}
array set waveforms {}
set delays {}
proc get_clocks {args} {
    global periods
    set names [lindex $args end]; set out {}
    foreach name $names {if {[info exists periods($name)]} {lappend out $name}}
    return $out
}
proc get_ports {args} {
    set names [lindex $args end]
    if {$names eq {eth_rxd[*] eth_rx_ctl}} {return {rx0 rx1 rx2 rx3 rxctl}}
    return $names
}
proc create_clock {args} {
    global periods waveforms
    set name [lindex $args [expr {[lsearch -exact $args -name]+1}]]
    set periods($name) [lindex $args [expr {[lsearch -exact $args -period]+1}]]
    set waveforms($name) [lindex $args [expr {[lsearch -exact $args -waveform]+1}]]
}
proc set_clock_uncertainty {args} {}
proc set_input_delay {args} {global delays; lappend delays $args}
proc require {condition message} {if {![uplevel 1 [list expr $condition]]} {error $message}}
"""


class TclRecipeTests(unittest.TestCase):
    def run_tcl(self, body):
        script = "source {" + str(ROOT / "fpga/zu15eg/trispeed_board_constraints.tcl") + "}\n"
        script += TCL_MOCKS + "\n" + body
        # tclsh's interactive stdin can return 0 on a script error. Wrap the
        # entire test in catch and require an explicit success marker as well.
        command = "if {[catch {\n" + script + "\n} why]} {puts stderr $why; exit 1}\nputs HOST_TCL_CONTRACT_PASS\n"
        result = subprocess.run(["tclsh"], input=command, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("HOST_TCL_CONTRACT_PASS", result.stdout)

    def test_three_rate_rx_edges_and_inherited_budgets(self):
        for speed, period in ((10, 400), (100, 40), (1000, 8)):
            with self.subTest(speed=speed):
                self.run_tcl("""
valence_trispeed_rx_constraints @speed@
require {$periods(phy_rx)==@period@ && $periods(phy_rx_launch)==@period@} {wrong period}
require {[lindex $waveforms(phy_rx_launch) 0]==2 && [lindex $waveforms(phy_rx_launch) 1]==@fall@} {wrong fixed skew}
require {[llength $delays]==4} {missing both-edge min/max}
foreach d $delays {require {[lsearch -exact $d 1.050]>=0 || [lsearch -exact $d -1.050]>=0} {budget changed}}
""".replace("@speed@", str(speed)).replace("@period@", str(period)).replace("@fall@", str(period/2+2)))

    def test_existing_clock_and_invalid_rate_rejected(self):
        self.run_tcl("""
require {[catch {valence_trispeed_rx_constraints 250} why]} {invalid rate accepted}
require {[string match {*explicit*} $why]} {wrong failure}
set periods(phy_rx) 8.0
require {[catch {valence_trispeed_rx_constraints 100} why]} {legacy clock accepted}
require {[string match {*refusing existing/legacy*} $why]} {wrong failure}
require {[llength $delays]==0} {partial timing mutations on rejected legacy flow}
""")

    def test_pad_topology_missing_cells_rejected(self):
        self.run_tcl("""
proc get_cells {args} {return {}}
require {[catch {valence_trispeed_quarter_tx_constraints u_rgmii 1000} why]} {missing pads accepted}
require {[string match {*six real tri-speed ODDR*} $why]} {wrong pad failure}
""")

    def test_packet_cdc_includes_rate_diagnostics_and_physical_epoch(self):
        self.run_tcl("""
set mailbox {}; set gray {}; set payload {}
proc valence_mailbox_cdc_constraints {path budget} {global mailbox; lappend mailbox [list $path $budget]}
proc valence_stream_cdc_constraints {path budget} {global gray; lappend gray [list $path $budget]}
proc valence_fifo_payload_constraints {path budget} {global payload; lappend payload [list $path $budget]}
valence_trispeed_packet_cdc_constraints test
require {[llength $mailbox]==9 && [llength $gray]==3 && $gray eq $payload} {incomplete scoped crossing list}
foreach path {txRate rxRate rawDiagnostics/mailbox rxDiagnostics/mailbox rxStop/command} {
    require {[lsearch -exact $mailbox [list test/$path 8.0]]>=0} {missing rate/diagnostic mailbox}
}
require {[lsearch -exact $gray {test/physicalIngress/crossing/fifo 8.0}]>=0} {missing raw physical FIFO}
foreach row [concat $mailbox $gray $payload] {require {[lindex $row 1]==8.0} {slow-mode relaxation}}
""")


if __name__ == "__main__":
    unittest.main()
