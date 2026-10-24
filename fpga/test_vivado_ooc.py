"""Fast Tcl control-flow mocks. NOT Vivado synthesis, XDC API, timing or FPGA evidence."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("vivado-ooc.tcl")
PART = "xczu15eg-ffvb1156-2-i"
PERIOD = "3.333333333333"
HARNESS = r'''
lassign $argv script rtl part period top mutation
set events {}; set design_exists 0; set synth_loading 0; set clock_created 0
set clock_period {}; set xdc {}; set stage initial; set synth_args {}
proc event {name} {lappend ::events $name}
proc require_design {} {if {!$::design_exists} {error "MOCK: design query before elaboration"}}
proc get_parts {args} {
    if {$::mutation eq "part-absent"} {return {}}
    if {$::mutation eq "part-ambiguous"} {return [list $::part $::part]}
    if {$::mutation eq "part-name"} {return wrong_part}
    return $::part
}
proc version {} {return MOCK_NOT_VIVADO_2025.2}
proc create_project {args} {event project}
proc set_param {args} {event parameter}
proc get_param {name} {
    if {$name ne "general.maxThreads"} {error "MOCK: unexpected parameter readback"}
    if {$::mutation eq "thread-readback-error"} {error "MOCK: parameter readback failed"}
    if {$::mutation eq "thread-too-low"} {return 4}
    event parameter_readback
    return 8
}
proc read_verilog {args} {event rtl}
proc read_xdc {args} {
    if {[lrange $args 0 1] ne {-mode out_of_context}} {error "MOCK: wrong XDC mode"}
    if {$::design_exists} {error "MOCK: timing XDC must precede synthesis"}
    event register_xdc
    if {$::mutation eq "xdc-error"} {error "MOCK: XDC registration failed"}
    set ::xdc [lindex $args end]
    # Register only. In this mock the design does not exist until synth_design.
    # This models documented sequencing, not native Vivado execution semantics.
}
proc synth_design {args} {
    event synth
    set ::synth_args $args
    if {$::xdc eq ""} {error "MOCK: synthesis has no registered timing XDC"}
    if {[lindex $args [expr {[lsearch -exact $args -mode]+1}]] ne "out_of_context"} {
        error "MOCK: not OOC synthesis"
    }
    if {$::mutation eq "synth-error"} {error "MOCK: synthesis failed"}
    if {$::mutation eq "directive-error" && [lsearch -exact $args -directive] >= 0} {
        error "MOCK: directive spelling rejected"
    }
    set ::design_exists 1; set ::synth_loading 1
    if {$::mutation ne "missing-clock"} {source $::xdc}
    set ::synth_loading 0; set ::stage synthesized
    if {$::mutation eq "slower-clock"} {set ::clock_period 3.334}
    if {$::mutation eq "wrong-clock"} {set ::clock_period 3.0}
    if {$::mutation eq "ps-rounding"} {set ::clock_period 3.333}
    if {$::mutation eq "nan-clock"} {set ::clock_period NaN}
}
proc create_clock {args} {
    require_design
    if {!$::synth_loading} {error "MOCK: clock created outside synthesis XDC processing"}
    event apply_clock_in_synth
    set ::clock_created 1
    set ::clock_period [lindex $args [expr {[lsearch -exact $args -period]+1}]]
}
proc current_design {} {require_design; return design}
proc get_ports {args} {
    require_design
    if {[lindex $args end] eq "clock"} {
        if {$::mutation eq "missing-port"} {return {}}
        if {$::mutation eq "multiple-ports"} {return {clock other_clock}}
        return clock
    }
    return {clock reset data_in data_out}
}
proc get_clocks {args} {
    require_design
    if {!$::clock_created} {return {}}
    if {$::mutation eq "multiple-clocks" ||
        ($::mutation eq "extra-clock" && [lindex $args end] eq "*")} {return {core_clock extra}}
    if {$::mutation eq "wrong-clock-name"} {return different_clock}
    return core_clock
}
proc get_property {key object} {
    if {$key eq "NAME"} {
        if {$object eq "design"} {
            if {$::mutation eq "wrong-top"} {return different_top}
            return $::top
        }
        return $object
    }
    if {$key eq "PART"} {
        if {$::mutation eq "wrong-part"} {return different_part}
        return $::part
    }
    if {$key eq "PERIOD"} {return $::clock_period}
    if {$key eq "DIRECTION"} {return [expr {$object eq "data_out" ? "OUT" : "IN"}]}
    error "MOCK: unexpected property $key"
}
proc write_checkpoint {path} {
    require_design; event checkpoint:[file tail $path]
    if {[file tail $path] eq "post_synth.dcp"} {
        if {$::mutation eq "checkpoint-missing"} {return}
        if {$::mutation eq "checkpoint-empty"} {close [open $path w]; return}
    }
    set f [open $path {WRONLY CREAT EXCL}]; puts $f MOCK_NOT_A_DCP; close $f
}
proc opt_design {} {
    event opt; set ::stage optimized
    if {$::mutation eq "clock-lost-after-opt"} {set ::clock_created 0}
}
proc place_design {} {event place; set ::stage placed}
proc route_design {} {
    event route
    if {$::mutation eq "route-error"} {error "MOCK: route failed"}
    set ::stage routed
}
proc mock_report {command args} {
    require_design; event $command
    if {$::mutation eq "synth-report-error" && $::stage eq "synthesized" && $command eq "report_timing_summary"} {
        error "MOCK: post-synth report failed"
    }
    if {$::mutation eq "report-error" && $::stage eq "routed" && $command eq "report_utilization"} {
        error "MOCK: post-route report failed"
    }
    if {$command eq "report_timing_summary" &&
        ([lsearch -exact $args min_max]<0 || [lsearch -exact $args -report_unconstrained]<0)} {
        error "MOCK: missing min/max or unconstrained coverage"
    }
    if {$command eq "report_timing" &&
        [lrange $args 0 5] ne {-from core_clock -to core_clock -delay_type min_max}} {
        error "MOCK: internal timing not scoped to core clock"
    }
    set path [lindex $args [expr {[lsearch -exact $args -file]+1}]]
    set f [open $path w]; puts $f [list MOCK_NOT_A_NATIVE_REPORT $command {*}$args]; close $f
}
foreach command {report_utilization report_timing_summary report_timing report_clocks
                 report_route_status report_drc check_timing} {
    proc ::$command {args} [format {mock_report %s {*}$args} $command]
}
foreach command {set_false_path set_input_delay set_output_delay set_clock_groups set_multicycle_path
                 read_checkpoint open_checkpoint write_bitstream write_device_image} {
    proc ::$command {args} [format {error "MOCK: forbidden operation %s"} $command]
}
set argv [list $rtl $part $period]
if {$top ne ""} {lappend argv $top} else {set top FpgaRomTop}
set argc [llength $argv]
set code [catch {source $script} reason]
puts "TRACE=$events"
puts "SYNTH_ARGS=$synth_args"
if {$code} {puts stderr $reason; exit 1}
'''


@unittest.skipUnless(shutil.which("tclsh"), "tclsh required; no native Vivado is used")
class VivadoOocContract(unittest.TestCase):
    def run_flow(self, top="CommonA1CpuTile", period=PERIOD, mutation="", images=True,
                 no_rtl=False, existing_reports=False, place_only=False, script_change=None,
                 synth_directive=None, synth_only=None):
        with tempfile.TemporaryDirectory(prefix="valence-ooc-mock-") as temp:
            root = Path(temp)
            rtl = root / "rtl with spaces"
            rtl.mkdir()
            if not no_rtl:
                for name in ("z.sv", "a.sv"):
                    (rtl / name).write_text("// MOCK input only\n")
            if images:
                for name in ("rom_even.hex", "rom_odd.hex", "ram_zero.hex"):
                    (rtl / name).write_text("00\n")
            if mutation == "missing-ram":
                (rtl / "ram_zero.hex").unlink()
            if existing_reports:
                (rtl / "reports").mkdir()
                (rtl / "reports" / "preserve.txt").write_text("prior evidence\n")
            harness = root / "harness.tcl"
            harness.write_text(HARNESS)
            script = SCRIPT
            if script_change:
                script = root / "mutated-script.tcl"
                script.write_text(script_change(SCRIPT.read_text()))
            env = dict(os.environ)
            for name in ("VALENCE_PLACE_ONLY", "VALENCE_SYNTH_DIRECTIVE", "VALENCE_SYNTH_ONLY"):
                env.pop(name, None)
            if place_only:
                env["VALENCE_PLACE_ONLY"] = "1"
            if synth_directive is not None:
                env["VALENCE_SYNTH_DIRECTIVE"] = synth_directive
            if synth_only is not None:
                env["VALENCE_SYNTH_ONLY"] = str(synth_only)
            result = subprocess.run(["tclsh", str(harness), str(script), str(rtl), PART, period,
                                     top, mutation], capture_output=True, text=True, env=env)
            reports = {p.name: p.read_text() for p in (rtl / "reports").glob("*") if p.is_file()}
            return result, reports

    def assert_failure(self, expected, **kwargs):
        result, reports = self.run_flow(**kwargs)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(expected, result.stderr)
        return result, reports

    @staticmethod
    def synth_args(result):
        return next(line.removeprefix("SYNTH_ARGS=") for line in result.stdout.splitlines()
                    if line.startswith("SYNTH_ARGS="))

    def test_default_synthesis_arguments_and_full_stages_do_not_drift(self):
        expected = ("-top CommonA1CpuTile -part " + PART + " -mode out_of_context "
                    "-flatten_hierarchy rebuilt -verilog_define ENABLE_INITIAL_MEM_")
        for directive in (None, "default"):
            with self.subTest(directive=directive):
                result, reports = self.run_flow(synth_directive=directive, synth_only=0)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.synth_args(result), expected)
                self.assertIn("synth_command=synth_design " + expected, reports["inputs.txt"])
                self.assertIn("synth_directive=default synth_only=0", reports["inputs.txt"])
                self.assertIn("stage=OOC_COMMANDS_COMPLETED_NOT_TIMING_SIGNOFF", reports["inputs.txt"])
                self.assertIn("routed.dcp", reports)

    def test_runtime_directive_changes_only_synthesis_directive(self):
        baseline, baseline_reports = self.run_flow()
        result, reports = self.run_flow(synth_directive="RuntimeOptimized")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.synth_args(result), self.synth_args(baseline) + " -directive RuntimeOptimized")
        self.assertEqual(reports["ooc-clock.xdc"], baseline_reports["ooc-clock.xdc"])
        self.assertEqual(reports["boundary-scope.txt"], baseline_reports["boundary-scope.txt"])
        self.assertIn("register_xdc synth apply_clock_in_synth", result.stdout)
        self.assertIn("synth_directive=RuntimeOptimized synth_only=0", reports["inputs.txt"])
        self.assertIn("synth_command=synth_design " + self.synth_args(result), reports["inputs.txt"])
        self.assertIn("DIAGNOSTIC_RUNTIMEOPTIMIZED_NOT_PPA_COMPARABLE_WITH_DEFAULT", result.stdout)
        self.assertIn("ppa_guarantee=NONE", reports["inputs.txt"])
        self.assertIn("routed.dcp", reports)

    def test_invalid_diagnostic_environment_values_fail_before_output(self):
        for directive in ("", "Default", "runtimeoptimized", "RunTimeOptimized", "PerformanceOptimized",
                          "RuntimeOptimized -no_timing_driven", "RuntimeOptimized;error injected"):
            with self.subTest(directive=directive):
                result, reports = self.assert_failure("VALENCE_SYNTH_DIRECTIVE must be", synth_directive=directive)
                self.assertEqual(reports, {})
                self.assertEqual(self.synth_args(result), "")
        for stop in ("", "true", "01", "2", "1;error injected"):
            with self.subTest(synth_only=stop):
                _, reports = self.assert_failure("VALENCE_SYNTH_ONLY must be", synth_only=stop)
                self.assertEqual(reports, {})

    def test_synth_only_retains_checked_checkpoint_and_reports_not_implementation(self):
        for directive in (None, "RuntimeOptimized"):
            with self.subTest(directive=directive):
                result, reports = self.run_flow(synth_directive=directive, synth_only=1, place_only=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                for name in ("post_synth.dcp", "post_synth_utilization.rpt",
                             "post_synth_hierarchical_utilization.rpt", "post_synth_timing.rpt", "clocks.rpt"):
                    self.assertTrue(reports[name])
                for name in ("post_opt.dcp", "placed.dcp", "routed.dcp"):
                    self.assertNotIn(name, reports)
                self.assertIn("SYNTH_ONLY_COMPLETED_NOT_FULL_OOC_NOT_TIMING_SIGNOFF", reports["inputs.txt"])
                self.assertIn("post_synth_identity_clock_checked_checkpoint_written", reports["inputs.txt"])
                self.assertIn("synth_only=1", reports["inputs.txt"])
                self.assertNotIn("OOC_COMMANDS_COMPLETED", result.stdout)
                self.assertNotIn("optimization_started", result.stdout)

    def test_synth_only_cannot_skip_clock_or_checkpoint_checks(self):
        for mutation, error in (("wrong-part", "part/top mismatch"), ("slower-clock", "clock period mismatch"),
                                ("checkpoint-missing", "Missing or empty post_synth checkpoint"),
                                ("checkpoint-empty", "Missing or empty post_synth checkpoint")):
            with self.subTest(mutation=mutation):
                result, _ = self.assert_failure(error, mutation=mutation, synth_only=1)
                self.assertNotIn("SYNTH_ONLY_COMPLETED", result.stdout)

    def test_synth_only_report_failure_preserves_dcp_without_completion(self):
        result, reports = self.assert_failure("post-synth report failed", mutation="synth-report-error", synth_only=1)
        self.assertTrue(reports["post_synth.dcp"])
        self.assertNotIn("SYNTH_ONLY_COMPLETED", result.stdout)
        self.assertNotIn("post_synth_reports_completed", reports["inputs.txt"])

    def test_native_directive_rejection_is_not_retried_or_hidden(self):
        result, reports = self.assert_failure("directive spelling rejected", mutation="directive-error",
                                              synth_directive="RuntimeOptimized")
        trace = next(line for line in result.stdout.splitlines() if line.startswith("TRACE="))
        self.assertEqual(trace.split().count("synth"), 1)
        self.assertNotIn("post_synth.dcp", reports)

    def test_a1_without_rom_uses_deferred_xdc_and_preserves_stages(self):
        result, reports = self.run_flow(images=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("register_xdc synth apply_clock_in_synth", result.stdout)
        self.assertEqual(reports["ooc-clock.xdc"],
                         "create_clock -name core_clock -period " + PERIOD + " [get_ports clock]\n")
        self.assertIn("source_order=a.sv z.sv", reports["inputs.txt"])
        self.assertIn("thread_limit_requested=8", reports["inputs.txt"])
        self.assertIn("thread_limit_readback=8 active_workers=UNMEASURED", reports["inputs.txt"])
        for name in ("post_synth.dcp", "post_opt.dcp", "placed.dcp", "routed.dcp",
                     "post_route_internal_paths.rpt", "check_timing.rpt", "route_status.rpt", "drc.rpt"):
            self.assertIn(name, reports)
        self.assertIn("UNBUDGETED port=reset", reports["boundary-scope.txt"])
        self.assertIn("UNBUDGETED port=data_in", reports["boundary-scope.txt"])
        self.assertIn("OOC_COMMANDS_COMPLETED_NOT_TIMING_SIGNOFF", result.stdout)

    def test_legacy_four_tops_and_default_remain_admitted(self):
        for top in ("FpgaRomTop", "FpgaPlatformTop", "CurrentSocTimingTop", "CompactSocTimingTop", ""):
            with self.subTest(top=top):
                result, _ = self.run_flow(top=top)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_old_rom_and_ram_guards_remain(self):
        for top in ("FpgaRomTop", "FpgaPlatformTop"):
            with self.subTest(top=top):
                self.assert_failure("Missing ROM image", top=top, images=False)
        self.assert_failure("Missing RAM initialization", top="FpgaPlatformTop", mutation="missing-ram")

    def test_old_timing_tops_do_not_need_rom(self):
        for top in ("CurrentSocTimingTop", "CompactSocTimingTop"):
            result, _ = self.run_flow(top=top, images=False)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_unknown_top_and_invalid_periods_rejected(self):
        self.assert_failure("Unsupported top", top="InventedA1")
        for period in ("0", "-1", "NaN", "Inf", "-Inf", "abc", "1;error injected"):
            with self.subTest(period=period):
                self.assert_failure("positive and finite", period=period)

    def test_exact_part_required(self):
        for mutation in ("part-absent", "part-ambiguous", "part-name"):
            with self.subTest(mutation=mutation):
                self.assert_failure("exact installed FPGA part", mutation=mutation)

    def test_thread_setting_readback_is_required_and_recorded(self):
        result, reports = self.assert_failure("requested thread limit unavailable", mutation="thread-too-low")
        self.assertIn("thread_limit_readback=4 active_workers=UNMEASURED", reports["inputs.txt"])
        self.assertNotIn("post_synth.dcp", reports)
        self.assertNotIn("register_xdc", result.stdout)
        self.assert_failure("parameter readback failed", mutation="thread-readback-error")

    def test_synthesized_identity_clock_and_period_checked(self):
        for mutation, expected in (("wrong-part", "part/top mismatch"), ("wrong-top", "part/top mismatch"),
                ("missing-port", "exactly one clock"), ("multiple-ports", "exactly one clock"),
                ("missing-clock", "ambiguous core_clock"), ("multiple-clocks", "ambiguous core_clock"),
                ("wrong-clock-name", "ambiguous core_clock"), ("slower-clock", "clock period mismatch"),
                ("wrong-clock", "clock period mismatch"), ("nan-clock", "clock period mismatch"),
                ("extra-clock", "additional clocks"), ("clock-lost-after-opt", "ambiguous core_clock")):
            with self.subTest(mutation=mutation):
                self.assert_failure(expected, mutation=mutation)

    def test_picosecond_readback_may_be_tighter_not_slower(self):
        result, reports = self.run_flow(mutation="ps-rounding")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("actual_period_ns=3.333", reports["boundary-scope.txt"])

    def test_eager_clock_evaluation_mutation_fails_without_design(self):
        self.assert_failure("design query before elaboration", script_change=lambda text: text.replace(
            "read_xdc -mode out_of_context $clock_xdc", "source $clock_xdc"))

    def test_input_and_prior_evidence_guards(self):
        self.assert_failure("No exported SystemVerilog", no_rtl=True)
        _, reports = self.assert_failure("Fresh reports directory", existing_reports=True)
        self.assertEqual(reports["preserve.txt"], "prior evidence\n")

    def test_failed_xdc_or_synth_cannot_advance(self):
        for mutation, expected in (("xdc-error", "XDC registration failed"), ("synth-error", "synthesis failed")):
            result, reports = self.assert_failure(expected, mutation=mutation)
            self.assertNotIn("post_synth.dcp", reports)
            self.assertNotIn("place", result.stdout)

    def test_route_failure_retains_placement_not_routed_checkpoint(self):
        _, reports = self.assert_failure("route_design failed: MOCK: route failed", mutation="route-error")
        self.assertIn("placed.dcp", reports)
        self.assertIn("route_status.rpt", reports)
        self.assertNotIn("routed.dcp", reports)

    def test_route_checkpoint_precedes_expensive_report_failure(self):
        _, reports = self.assert_failure("post-route report failed", mutation="report-error")
        self.assertIn("routed.dcp", reports)

    def test_place_only_remains_explicitly_partial(self):
        result, reports = self.run_flow(place_only=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stopping after placement", result.stdout)
        self.assertIn("placed.dcp", reports)
        self.assertNotIn("routed.dcp", reports)
        self.assertNotIn("OOC_COMMANDS_COMPLETED", result.stdout)


if __name__ == "__main__":
    unittest.main()
