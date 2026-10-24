# Invoke in Vivado: vivado -mode batch -source fpga/vivado-ooc.tcl -tclargs RTL_DIRECTORY FULL_PART PERIOD_NS ?TOP?
# Example family names are insufficient: use the exact installed part including package/speed grade.
# Fresh measurement only: saved DCPs may be reopened for reports, never substituted for fresh RTL here.
proc valence_ooc_check_clock {target_part top_module period_ns} {
    if {[get_property PART [current_design]] ne $target_part ||
        [get_property NAME [current_design]] ne $top_module} {
        error "OOC synthesized part/top mismatch"
    }
    set ports [get_ports -quiet clock]
    if {[llength $ports] != 1} { error "OOC requires exactly one clock input port" }
    set clocks [get_clocks -quiet -of_objects $ports]
    if {[llength $clocks] != 1 || [get_property NAME $clocks] ne "core_clock"} {
        error "OOC missing or ambiguous core_clock on clock input"
    }
    set actual [get_property PERIOD $clocks]
    # Some tool readbacks have picosecond precision. Permit only <=1 ps of
    # tighter rounding, never a longer period (e.g. 3.334 ns for CPU300).
    if {![string is double -strict $actual] ||
        [catch {expr {$actual > 0 && $actual <= $period_ns + 1.0e-9 &&
                     $period_ns - $actual <= 0.001}} valid] || !$valid} {
        error "OOC clock period mismatch: actual=$actual requested=$period_ns"
    }
    if {$top_module eq "CommonA1CpuTile" && [llength [get_clocks -quiet *]] != 1} {
        error "OOC A1 tile has unexpected additional clocks"
    }
    return $clocks
}
proc valence_ooc_record_stage {stage} {
    set f [open reports/inputs.txt a]
    puts $f "stage=$stage"
    close $f
    puts "OOC_STAGE=$stage"
}

if {$argc != 3 && $argc != 4} { error "usage: vivado-ooc.tcl RTL_DIRECTORY FULL_PART PERIOD_NS ?TOP?" }
set rtl_dir [file normalize [lindex $argv 0]]
set target_part [lindex $argv 1]
set period_ns [lindex $argv 2]
set top_module FpgaRomTop
if {$argc == 4} { set top_module [lindex $argv 3] }
if {$top_module ni {FpgaRomTop FpgaPlatformTop CurrentSocTimingTop CompactSocTimingTop CommonA1CpuTile}} { error "Unsupported top module" }
if {[catch {expr {[string is double -strict $period_ns] && $period_ns > 0 && $period_ns < Inf}} valid_period] ||
    !$valid_period} { error "PERIOD_NS must be positive and finite" }
# Explicit diagnostic opt-in only; default keeps the original synth arguments.
set synth_directive default
if {[info exists ::env(VALENCE_SYNTH_DIRECTIVE)]} {set synth_directive $::env(VALENCE_SYNTH_DIRECTIVE)}
if {$synth_directive ni {default RuntimeOptimized}} {
    error "VALENCE_SYNTH_DIRECTIVE must be default or RuntimeOptimized"
}
set synth_only 0
if {[info exists ::env(VALENCE_SYNTH_ONLY)]} {set synth_only $::env(VALENCE_SYNTH_ONLY)}
if {$synth_only ni {0 1}} {error "VALENCE_SYNTH_ONLY must be 0 or 1"}
set synth_command [list synth_design -top $top_module -part $target_part -mode out_of_context \
    -flatten_hierarchy rebuilt -verilog_define ENABLE_INITIAL_MEM_]
if {$synth_directive eq "RuntimeOptimized"} {
    # UG835 option table / UG901 spelling. Confirm installed synth_design -help
    # before a native diagnostic run; do not silently retry another spelling.
    lappend synth_command -directive RuntimeOptimized
}
set matched_parts [get_parts -quiet $target_part]
if {[llength $matched_parts] != 1 || [get_property NAME $matched_parts] ne $target_part} {
    error "Specify an exact installed FPGA part, without wildcards"
}
cd $rtl_dir
if {$top_module in {FpgaRomTop FpgaPlatformTop}} {
    foreach image {rom_even.hex rom_odd.hex} {
        if {![file exists $image]} { error "Missing ROM image: $image" }
    }
}
if {$top_module eq "FpgaPlatformTop" && ![file exists ram_zero.hex]} { error "Missing RAM initialization" }
set source_files [lsort [glob -nocomplain *.sv]]
if {[llength $source_files] == 0} { error "No exported SystemVerilog files" }
if {[file exists reports]} { error "Fresh reports directory required; preserve previous DCPs/reports" }
file mkdir reports

# Register timing before synthesis using the documented non-project OOC XDC flow.
# Braces keep get_ports unevaluated here: Vivado evaluates it when it processes
# the XDC with the elaborated design, NOT against an empty pre-synthesis design.
# UG903 2025.2: Synthesis-and-Implementation-Constraint-Files; Out-of-Context-Constraints.
set clock_xdc [file normalize reports/ooc-clock.xdc]
set f [open $clock_xdc {WRONLY CREAT EXCL}]
puts $f [format {create_clock -name core_clock -period %.15g [get_ports clock]} $period_ns]
close $f
set f [open reports/inputs.txt {WRONLY CREAT EXCL}]
puts $f "scope=OOC_INTERNAL_PATHS_ONLY_NOT_BOARD_SIGNOFF"
puts $f "part=$target_part top=$top_module requested_period_ns=$period_ns"
puts $f "vivado=[version]"
puts $f "defines=ENABLE_INITIAL_MEM_ hierarchy=rebuilt"
puts $f "synth_directive=$synth_directive synth_only=$synth_only"
puts $f "synth_command=$synth_command"
puts $f "ppa_guarantee=NONE timing_signoff=NOT_ESTABLISHED"
if {$synth_directive eq "RuntimeOptimized"} {
    puts $f "comparison_scope=DIAGNOSTIC_RUNTIMEOPTIMIZED_NOT_PPA_COMPARABLE_WITH_DEFAULT"
} else {
    puts $f "comparison_scope=DEFAULT_FLOW_COMPARE_ONLY_MATCHED_SYNTHESIS_SETTINGS"
}
puts $f "thread_limit_requested=8 active_workers=UNMEASURED"
puts $f "source_order=$source_files"
puts $f "No source/config hash receipt is implied; bind this run to the frozen export separately."
close $f
create_project -in_memory -part $target_part
# Windows defaults to 2 Vivado worker threads; allow up to 8 on larger hosts.
set_param general.maxThreads 8
set thread_limit [get_param general.maxThreads]
set f [open reports/inputs.txt a]
puts $f "thread_limit_readback=$thread_limit active_workers=UNMEASURED"
close $f
if {![string is integer -strict $thread_limit] || $thread_limit < 8} {
    error "OOC requested thread limit unavailable: requested=8 readback=$thread_limit"
}
# Vivado applies preprocessor definitions during synthesis, not this read step.
read_verilog -sv $source_files
read_xdc -mode out_of_context $clock_xdc
# CIRCT guards the generated $readmemh blocks with this macro.
valence_ooc_record_stage synthesis_started
puts "OOC_SYNTH_COMMAND=$synth_command"
if {$synth_directive eq "RuntimeOptimized"} {
    puts "DIAGNOSTIC_RUNTIMEOPTIMIZED_NOT_PPA_COMPARABLE_WITH_DEFAULT: no runtime or PPA guarantee"
}
{*}$synth_command
set core_clock [valence_ooc_check_clock $target_part $top_module $period_ns]
write_checkpoint reports/post_synth.dcp
# Successful write plus nonempty artifact, not a separate native reopen proof.
if {![file isfile reports/post_synth.dcp] || [file size reports/post_synth.dcp] == 0} {
    error "Missing or empty post_synth checkpoint"
}
valence_ooc_record_stage post_synth_identity_clock_checked_checkpoint_written
set f [open reports/boundary-scope.txt {WRONLY CREAT EXCL}]
puts $f "Internal core-clock sequential paths only. Data I/O and reset entry have NO external timing budget."
puts $f "requested_period_ns=$period_ns actual_period_ns=[get_property PERIOD $core_clock]"
puts $f "No input/output delay, false path, or board clock/reset assumption is supplied by this flow."
foreach port [get_ports -quiet *] {
    set name [get_property NAME $port]
    if {$name ne "clock"} {
        puts $f "UNBUDGETED port=$name direction=[get_property DIRECTION $port]"
    }
}
close $f
report_utilization -file reports/post_synth_utilization.rpt
# Rebuilt hierarchy can misattribute optimized logic; this is not precise
# per-module attribution. Decide any different hierarchy policy before the run,
# rather than repeating synthesis merely to answer a report query.
report_utilization -hierarchical -file reports/post_synth_hierarchical_utilization.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file reports/post_synth_timing.rpt
report_clocks -file reports/clocks.rpt
valence_ooc_record_stage post_synth_reports_completed
if {$synth_only eq "1"} {
    valence_ooc_record_stage SYNTH_ONLY_COMPLETED_NOT_FULL_OOC_NOT_TIMING_SIGNOFF
    puts "VALENCE_SYNTH_ONLY=1: stopping after synthesis checkpoint and reports; no placement or routing"
    return
}
valence_ooc_record_stage optimization_started
opt_design
set core_clock [valence_ooc_check_clock $target_part $top_module $period_ns]
write_checkpoint reports/post_opt.dcp
valence_ooc_record_stage placement_started
place_design
set core_clock [valence_ooc_check_clock $target_part $top_module $period_ns]
# Preserve a usable implementation snapshot even if congestion prevents routing.
write_checkpoint reports/placed.dcp
report_utilization -file reports/post_place_utilization.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file reports/post_place_timing.rpt
if {[info exists ::env(VALENCE_PLACE_ONLY)] && $::env(VALENCE_PLACE_ONLY) eq "1"} {
    valence_ooc_record_stage PLACE_ONLY_COMPLETED_NOT_FULL_OOC_NOT_TIMING_SIGNOFF
    puts "VALENCE_PLACE_ONLY=1: stopping after placement"
    return
}
valence_ooc_record_stage routing_started
if {[catch {route_design} route_error]} {
    valence_ooc_record_stage route_failed
    catch {report_route_status -file reports/route_status.rpt}
    error "route_design failed: $route_error"
}
set core_clock [valence_ooc_check_clock $target_part $top_module $period_ns]
write_checkpoint reports/routed.dcp
report_utilization -file reports/post_route_utilization.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file reports/post_route_timing.rpt
report_timing -from $core_clock -to $core_clock -delay_type min_max -max_paths 20 \
    -path_type full_clock_expanded -file reports/post_route_internal_paths.rpt
check_timing -verbose -file reports/check_timing.rpt
report_clocks -file reports/post_route_clocks.rpt
report_route_status -file reports/route_status.rpt
report_drc -file reports/drc.rpt
valence_ooc_record_stage OOC_COMMANDS_COMPLETED_NOT_TIMING_SIGNOFF
# External data/commit ports deliberately have no board I/O delays: only internal clocked paths
# can be assessed here. This is not board timing signoff; do not generate a bitstream from this script.
puts "OOC_COMMANDS_COMPLETED_NOT_TIMING_SIGNOFF: review internal min/max paths, coverage, route and DRC; boundary remains unqualified"
