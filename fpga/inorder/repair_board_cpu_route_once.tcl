# One isolated physical-only attempt from a completed board DCP.
# No synthesis, RTL edit, clock/exception change, or bit generation.
if {$argc != 1} {error "usage: repair_board_cpu_route_once.tcl EXISTING_BOARD_ROOT"}
set sourceRoot [file normalize [lindex $argv 0]]
if {![file isfile [file join $sourceRoot reports stage-result.txt]]} {
    error "Completed original board reports required"
}
set input [file join $sourceRoot reports real_board_routed.dcp]
set trial [file join $sourceRoot post-route-r1]
if {[file exists $trial]} {error "Preserve previous physical attempt"}
set out [file join $trial reports]
file mkdir $out
set_param general.maxThreads 8
open_checkpoint $input
if {[get_property PART [current_design]] ne "xczu15eg-ffvb1156-2-i"} {
    error "Wrong actual physical part"
}
foreach {pin expected} {u_soc/io_clockIn 3.333
                       u_axi_cdc/m_axi_aclk 4.000
                       u_soc/io_alwaysOnClock 20.000} {
    set c [get_clocks -of_objects [get_pins $pin]]
    if {[llength $c] != 1 || abs([get_property PERIOD $c]-$expected)>0.002} {
        error "Original domain clock must be preserved: $pin"
    }
}
report_timing_summary -delay_type min_max -report_unconstrained \
    -file [file join $out before_timing_summary.rpt]
write_xdc [file join $out before_constraints.xdc]
set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
if {$wns >= 0.0 || $wns < -0.200} {
    error "One bounded physical attempt only for a close failing route"
}
phys_opt_design -directive AggressiveExplore
route_design -directive Explore
write_checkpoint [file join $out real_board_routed.dcp]
write_xdc [file join $out after_constraints.xdc]
report_timing_summary -delay_type min_max -report_unconstrained \
    -file [file join $out timing_summary.rpt]
foreach delay {max min} {
    report_timing -delay_type $delay -max_paths 60 -input_pins \
        -file [file join $out [format "paths_%s.rpt" $delay]]
}
report_utilization -file [file join $out utilization_flat.rpt]
report_utilization -hierarchical -file [file join $out utilization.rpt]
report_clocks -file [file join $out clocks.rpt]
report_clock_interaction -file [file join $out clock_interaction.rpt]
report_cdc -details -file [file join $out cdc.rpt]
report_bus_skew -warn_on_violation -file [file join $out bus_skew.rpt]
report_drc -file [file join $out drc.rpt]
report_route_status -file [file join $out route_status.rpt]
report_exceptions -coverage -file [file join $out exceptions.rpt]
check_timing -verbose -file [file join $out check_timing.rpt]
report_io -file [file join $out io.rpt]
set setup [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set f [open [file join $out stage-result.txt] w]
puts $f "ONE_PHYSICAL_ATTEMPT ORIGINAL_ROUTE_PRESERVED NO_SYNTHESIS NO_RTL_OR_CLOCK_CHANGE"
puts $f "WNS=$setup WHS=$hold STATUS=ROUTED_REQUIRES_REVIEW NO_BIT_GENERATED"
close $f
close_design
# Identical read-only boundary/family queries on this isolated result.
set argv [list $trial]
set argc 1
source [file join $sourceRoot scripts review_board_cpu.tcl]
set argv [list $trial]
set argc 1
source [file join $sourceRoot scripts review_cache_boundaries.tcl]
puts "I1_ONE_POST_ROUTE_ATTEMPT_COMPLETE NO_ADDITIONAL_RETRY"
