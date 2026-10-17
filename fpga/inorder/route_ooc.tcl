# One default-profile standalone implementation, with an explicit external clock context.
# No board/peripheral integration and no bit. Boundary nets are intentionally not qualified.
if {$argc != 2} { error "usage: route_ooc.tcl SYNTH_DCP FRESH_REPORT_ROOT" }
set input [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
if {![file isfile $input]} { error "synthesized checkpoint missing" }
if {[file exists $out]} { error "refusing to overwrite physical evidence" }
file mkdir $out
set_param general.maxThreads 4
open_checkpoint $input
puts "ORBITAL_I1_CHECKPOINT_DESIGN_OBJECT [get_property NAME [current_design]]"
# An opened DCP's design object/project name is not its RTL top module. Validate the
# exact expected mapped RF hierarchy and clock instead of comparing project names.
foreach bank {rf/bank_ext/Memory_reg rf/bank_1_ext/Memory_reg} {
    set cell [get_cells -quiet $bank]
    if {[llength $cell] != 1 || [get_property REF_NAME $cell] != "RAMB36E2"} {
        error "expected default Orbital-I1 BRAM RF cell missing: $bank"
    }
}
set cpu_clock [get_clocks orbital_i1_cpu]
if {[llength $cpu_clock] != 1 || [get_property PERIOD $cpu_clock] != 5.000} {
    error "expected frozen 200MHz core-only clock"
}
# UG905: clock is driven by a BUFGCE outside this OOC core. This selected site is a
# standalone timing assumption, not the location/qualification of the VL100 board clock.
set candidates [lsort -dictionary [get_sites -quiet BUFGCE_X0Y*]]
if {[llength $candidates] == 0} { error "no external BUFGCE source sites on selected part" }
set source [lindex $candidates [expr {[llength $candidates] / 2}]]
set_property HD.CLK_SRC $source [get_ports clock]
set context [open [file join $out context.txt] w]
puts $context "scope=BARE_CORE_INTERNAL_PATHS_ONLY_NOT_SOC_NOT_BOARD"
puts $context "clock_period_ns=5.000 assumed_external_clock_source=$source"
puts $context "boundary_I_O_paths_and_peripheral_CDC_are_not_qualified"
close $context
opt_design
place_design -directive Default
phys_opt_design -directive Default
route_design -directive Default
write_checkpoint [file join $out routed.dcp]
report_utilization -file [file join $out utilization.rpt]
report_utilization -hierarchical -file [file join $out hierarchical_utilization.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose \
    -file [file join $out timing_routed.rpt]
report_timing -delay_type max -max_paths 20 -nworst 2 -file [file join $out setup_routed.rpt]
report_timing -delay_type min -max_paths 10 -nworst 2 -file [file join $out hold_routed.rpt]
report_route_status -file [file join $out route_status.rpt]
report_drc -file [file join $out drc.rpt]
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
puts "ORBITAL_I1_OOC_ROUTE_COMPLETE setup=[get_property SLACK $setup] hold=[get_property SLACK $hold] source=$source"
puts "ORBITAL_I1_NO_BOARD_QUALIFICATION_NO_BIT"
