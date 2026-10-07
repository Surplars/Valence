# Invoke in Vivado: vivado -mode batch -source fpga/vivado-ooc.tcl -tclargs RTL_DIRECTORY FULL_PART PERIOD_NS ?TOP?
# Example family names are insufficient: use the exact installed part including package/speed grade.
if {$argc != 3 && $argc != 4} { error "usage: vivado-ooc.tcl RTL_DIRECTORY FULL_PART PERIOD_NS ?TOP?" }
set rtl_dir [file normalize [lindex $argv 0]]
set target_part [lindex $argv 1]
set period_ns [lindex $argv 2]
set top_module FpgaRomTop
if {$argc == 4} { set top_module [lindex $argv 3] }
if {$top_module ni {FpgaRomTop FpgaPlatformTop CurrentSocTimingTop CompactSocTimingTop}} { error "Unsupported top module" }
if {![string is double -strict $period_ns] || $period_ns <= 0} { error "PERIOD_NS must be positive" }
set matched_parts [get_parts -quiet $target_part]
if {[llength $matched_parts] != 1 || [get_property NAME $matched_parts] ne $target_part} {
    error "Specify an exact installed FPGA part, without wildcards"
}
cd $rtl_dir
if {$top_module ni {CurrentSocTimingTop CompactSocTimingTop}} {
    foreach image {rom_even.hex rom_odd.hex} {
        if {![file exists $image]} { error "Missing ROM image: $image" }
    }
}
if {$top_module eq "FpgaPlatformTop" && ![file exists ram_zero.hex]} { error "Missing RAM initialization" }
create_project -in_memory -part $target_part
# Windows defaults to 2 Vivado worker threads; allow up to 8 on larger hosts.
set_param general.maxThreads 8
set source_files [glob -nocomplain *.sv]
if {[llength $source_files] == 0} { error "No exported SystemVerilog files" }
# Vivado applies preprocessor definitions during synthesis, not this read step.
read_verilog -sv $source_files
# CIRCT guards the generated $readmemh blocks with this macro.
synth_design -top $top_module -part $target_part -mode out_of_context -verilog_define ENABLE_INITIAL_MEM_
create_clock -name core_clock -period $period_ns [get_ports clock]
file mkdir reports
report_utilization -file reports/post_synth_utilization.rpt
# Rebuilt synthesis hierarchy can misattribute optimized logic; use a separate
# -flatten_hierarchy none synthesis when precise per-module attribution is needed.
report_utilization -hierarchical -file reports/post_synth_hierarchical_utilization.rpt
report_timing_summary -report_unconstrained -file reports/post_synth_timing.rpt
opt_design
place_design
# Preserve a usable implementation snapshot even if congestion prevents routing.
report_utilization -file reports/post_place_utilization.rpt
report_timing_summary -report_unconstrained -file reports/post_place_timing.rpt
write_checkpoint -force reports/placed.dcp
if {[info exists ::env(VALENCE_PLACE_ONLY)] && $::env(VALENCE_PLACE_ONLY) eq "1"} {
    puts "VALENCE_PLACE_ONLY=1: stopping after placement"
    return
}
if {[catch {route_design} route_error]} {
    catch {report_route_status -file reports/route_status.rpt}
    error "route_design failed: $route_error"
}
report_utilization -file reports/post_route_utilization.rpt
report_timing_summary -report_unconstrained -file reports/post_route_timing.rpt
check_timing -verbose -file reports/check_timing.rpt
write_checkpoint -force reports/routed.dcp
# External data/commit ports deliberately have no board I/O delays: only internal clocked paths
# can be assessed here. This is not board timing signoff; do not generate a bitstream from this script.
