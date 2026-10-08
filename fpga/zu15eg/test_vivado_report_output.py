"""Execute report Tcl with mocked CAD commands and real file I/O.

These are wrapper regression tests, not Vivado, timing, RAM or hardware proof.
Run with: python3 fpga/zu15eg/test_vivado_report_output.py
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
MOCKS = r"""
set events {}
set fail_command $::env(FAIL_COMMAND)
proc record {command args} {
    lappend ::events [list $command {*}$args]
    if {$command eq $::fail_command} {error "injected $command failure"}
}
proc report {command args} {
    record $command {*}$args
    set index [lsearch -exact $args -file]
    if {$index < 0} {error "missing native -file: $command"}
    if {[lsearch -exact $args -quiet] >= 0} {error "report must propagate errors"}
    if {$command eq "check_timing" && [lsearch -exact $args -verbose] < 0} {
        error "missing detailed timing checks"
    }
    set path [lindex $args [expr {$index + 1}]]
    if {$::env(BAD_REPORT_PATH) eq $command} {file mkdir $path}
    set f [open $path w]
    puts $f "MOCK_REPORT $command"
    close $f
}
foreach command {
    report_utilization report_timing_summary report_timing report_clocks
    report_clock_interaction report_cdc report_drc check_timing
} {interp alias {} $command {} report $command}
foreach command {
    open_checkpoint close_design create_project set_param read_verilog synth_design
    create_clock set_input_delay set_output_delay opt_design place_design route_design
} {interp alias {} $command {} record $command}
proc get_parts args {return xczu15eg-ffvb1156-2-i}
proc get_ports args {return {clock reset data}}
proc get_cells args {record get_cells {*}$args; return {ram0 flop0}}
proc get_property {property cell} {
    record get_property $property $cell
    switch -- $property {
        REF_NAME {return [expr {$cell eq "ram0" ? "RAMB18E2" : "FDRE"}]}
        INIT_00 {return 256'h0012}
        INITP_00 {return 256'h0034}
    }
    error "unexpected property $property"
}
proc list_property cell {return {REF_NAME INIT_00 INITP_00}}
proc version args {return MOCK_NOT_VIVADO}
proc write_checkpoint {path} {
    record write_checkpoint $path
    set f [open $path w]; puts $f MOCK_CHECKPOINT; close $f
}
proc valence_quarter_tx_audit {hier} {
    record valence_quarter_tx_audit $hier
    return {lane0 lane1 lane2 lane3 control}
}
# Deliberately no redirect command or permissive unknown-command fallback.
if {[llength [info commands redirect]]} {error "unexpected redirect command"}
set output $::env(OUTPUT)
set out $output
set input $::env(INPUT)
set script $::env(SCRIPT)
set kind $::env(KIND)
if {$kind eq "quarter"} {
    set f [open $script r]; set body [read $f]; close $f
    set start [string first {write_checkpoint [file join $out routed.dcp]} $body]
    set end [string first {report_timing_summary -delay_type min_max -report_unconstrained} $body $start]
    if {$start < 0 || $end < $start} {error "missing exact post-route audit section"}
    set body [string range $body $start [expr {$end - 1}]]
    if {![info complete $body]} {error "incomplete audit section"}
    set failed [catch {eval $body} detail]
} else {
    set argv [list $input $output]
    if {$kind eq "bridge"} {lappend argv $::env(STAGE)}
    set argc [llength $argv]
    if {$::env(BAD_ARGC) ne ""} {set argc $::env(BAD_ARGC)}
    set failed [catch {source $script} detail]
}
puts "EVENTS=$events"
if {$failed} {
    puts stderr $detail
    # Native Vivado batch can return zero even when its sourced Tcl fails.
    if {$::env(ZERO_EXIT_ON_ERROR)} {exit 0}
    exit 1
}
puts PASS_MOCK_REPORT_WRAPPER
"""


@unittest.skipUnless(shutil.which("tclsh"), "requires Tcl for execution-level wrapper tests")
class ReportOutput(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="valence report test ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "reports with spaces [literal] $name"
        self.input = self.root / "verified input [literal].dcp"
        self.input.write_text("MOCK_INPUT_NOT_A_CHECKPOINT\n")
        self.harness = self.root / "harness.tcl"
        self.harness.write_text(MOCKS)

    def run_script(self, kind="ram", fail="", stage="synth", bad_path="", bad_argc="", zero_exit=False):
        names = {
            "ram": "report_ram_concurrency.tcl",
            "bridge": "vivado_axi_payload_compare.tcl",
            "quarter": "replace_network_candidate.tcl",
        }
        env = dict(os.environ, INPUT=str(self.input), OUTPUT=str(self.output), KIND=kind,
                   SCRIPT=str(HERE / names[kind]), FAIL_COMMAND=fail, STAGE=stage,
                   BAD_REPORT_PATH=bad_path, BAD_ARGC=bad_argc, ZERO_EXIT_ON_ERROR=str(int(zero_exit)))
        return subprocess.run(["tclsh", str(self.harness)], env=env, text=True,
                              capture_output=True, timeout=15)

    def assert_pass(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS_MOCK_REPORT_WRAPPER", result.stdout)

    def assert_failure(self, result, message):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)
        self.assertNotIn("PASS_MOCK_REPORT_WRAPPER", result.stdout)

    def bridge_input(self):
        self.input = self.root / "frozen input [literal].sv"
        self.input.write_text("// MOCK_INPUT_NOT_RTL\n")

    def test_ram_full_report_and_init_inventory(self):
        result = self.run_script()
        self.assert_pass(result)
        for name in ("utilization.rpt", "timing_summary.rpt", "setup_paths.rpt", "hold_paths.rpt",
                     "clocks.rpt", "clock_interaction.rpt", "cdc.rpt", "drc.rpt", "check_timing.rpt",
                     "ram_primitives_and_init.txt", "REVIEW_REQUIRED.txt"):
            self.assertGreater((self.output / name).stat().st_size, 0)
        inventory = (self.output / "ram_primitives_and_init.txt").read_text()
        self.assertIn("RAMB18E2", inventory)
        self.assertIn("INIT_00 256'h0012", inventory)
        self.assertIn("INITP_00 256'h0034", inventory)
        self.assertNotIn("flop0", inventory)
        self.assertIn("No automatic timing or resource PASS", (self.output / "REVIEW_REQUIRED.txt").read_text())
        for forbidden in ("write_checkpoint", "synth_design", "place_design", "route_design"):
            self.assertNotIn(forbidden, result.stdout)

    def test_ram_report_failure_propagates(self):
        for command in ("open_checkpoint", "report_cdc", "check_timing", "get_property"):
            with self.subTest(command=command):
                self.output = self.root / command
                self.assert_failure(self.run_script(fail=command), "injected " + command + " failure")
                self.assertFalse((self.output / "REVIEW_REQUIRED.txt").exists())

    def test_ram_report_write_failure_propagates(self):
        self.assert_failure(self.run_script(bad_path="check_timing"), "couldn't open")
        self.assertFalse((self.output / "REVIEW_REQUIRED.txt").exists())

    def test_zero_batch_exit_does_not_establish_report_completion(self):
        result = self.run_script(fail="check_timing", zero_exit=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("injected check_timing failure", result.stderr)
        self.assertNotIn("PASS_MOCK_REPORT_WRAPPER", result.stdout)
        # Earlier reports survive, but the mandatory later artifacts are absent.
        self.assertTrue((self.output / "cdc.rpt").is_file())
        self.assertTrue((self.output / "drc.rpt").is_file())
        for name in ("check_timing.rpt", "ram_primitives_and_init.txt", "REVIEW_REQUIRED.txt"):
            self.assertFalse((self.output / name).exists())

    def test_ram_missing_checkpoint_rejected(self):
        self.input.unlink()
        self.assert_failure(self.run_script(), "missing verified checkpoint")
        self.assertFalse(self.output.exists())

    def test_ram_existing_output_preserved(self):
        self.output.mkdir()
        sentinel = self.output / "previous.txt"
        sentinel.write_text("original evidence")
        self.assert_failure(self.run_script(), "preserve old evidence")
        self.assertEqual(sentinel.read_text(), "original evidence")
        self.assertEqual(list(self.output.iterdir()), [sentinel])

    def test_ram_wrong_argc_rejected(self):
        self.assert_failure(self.run_script(bad_argc="1"), "usage:")
        self.assertFalse(self.output.exists())

    def test_bridge_both_stages_use_native_report_output(self):
        self.bridge_input()
        for stage in ("synth", "route"):
            with self.subTest(stage=stage):
                self.output = self.root / (stage + " reports with spaces [literal]")
                self.assert_pass(self.run_script(kind="bridge", stage=stage))
                labels = ("post_synth", "post_route") if stage == "route" else ("post_synth",)
                for label in labels:
                    self.assertIn("MOCK_REPORT check_timing", (self.output / (label + "_check_timing.rpt")).read_text())
                    self.assertIn("INITP_00", (self.output / (label + "_ram_primitives.txt")).read_text())
                    self.assertTrue((self.output / (label + ".dcp")).is_file())
                self.assertTrue((self.output / "SCOPE.txt").is_file())

    def test_bridge_report_failure_is_not_success(self):
        self.bridge_input()
        self.assert_failure(self.run_script(kind="bridge", fail="check_timing"), "injected check_timing failure")
        self.assertFalse((self.output / "post_synth.dcp").exists())
        self.assertFalse((self.output / "SCOPE.txt").exists())

    def test_bridge_write_failure_is_not_success(self):
        self.bridge_input()
        self.assert_failure(self.run_script(kind="bridge", bad_path="check_timing"), "couldn't open")
        self.assertFalse((self.output / "SCOPE.txt").exists())

    def test_bridge_invalid_stage_rejected(self):
        self.bridge_input()
        self.assert_failure(self.run_script(kind="bridge", stage="skip"), "stage must be")
        self.assertFalse(self.output.exists())

    def test_quarter_audit_records_validated_return_value(self):
        self.output.mkdir()
        self.assert_pass(self.run_script(kind="quarter"))
        text = (self.output / "quarter_tx_identity.txt").read_text()
        self.assertIn("PASS_NATIVE_QUARTER_TX_TOPOLOGY", text)
        self.assertIn("ACTUAL_VALIDATED_DATA_PADS=lane0 lane1 lane2 lane3 control", text)
        self.assertTrue((self.output / "routed.dcp").exists())

    def test_quarter_failed_audit_preserves_dcp_without_pass_file(self):
        self.output.mkdir()
        self.assert_failure(self.run_script(kind="quarter", fail="valence_quarter_tx_audit"),
                            "injected valence_quarter_tx_audit failure")
        self.assertTrue((self.output / "routed.dcp").exists())
        self.assertFalse((self.output / "quarter_tx_identity.txt").exists())

    def test_quarter_report_io_error_propagates(self):
        self.output.mkdir()
        (self.output / "quarter_tx_identity.txt").mkdir()
        self.assert_failure(self.run_script(kind="quarter"), "couldn't open")
        self.assertTrue((self.output / "routed.dcp").exists())


class SourceContract(unittest.TestCase):
    def test_no_unsupported_redirect_wrapper_in_fpga_tcl(self):
        for path in HERE.parent.rglob("*.tcl"):
            self.assertIsNone(re.search(r"\bredirect\s+-(?:file|variable|append|tee)\b", path.read_text()), str(path))

    def test_report_hash_matches_staging_contract(self):
        receipt = json.loads((HERE / "concurrency_validation/EXPORT-RECEIPT.json").read_text())
        entry = receipt["source_map"]["scripts/report_ram_concurrency.tcl"]
        self.assertEqual(entry["sha256"], hashlib.sha256((HERE / "report_ram_concurrency.tcl").read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main(verbosity=2)
