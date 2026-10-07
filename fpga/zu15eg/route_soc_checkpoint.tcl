# Continue a saved, clock-constrained board placement without redoing synthesis.
# Args: PLACED_DCP OUTPUT_DIR CPU_HZ [ROUTE_DIRECTIVE]
if {$argc < 3 || $argc > 5} {error "Expected CHECKPOINT OUTPUT_DIR CPU_HZ ?ROUTE_DIRECTIVE ?FLOW??"}
lassign $argv placed out cpu_hz route_directive flow
if {$flow eq ""} {set flow complete}
if {$flow ni {complete route-only post-route}} {error "Unsupported routing flow"}
if {$route_directive eq ""} {set route_directive Explore}
if {$route_directive ni {Explore AlternateCLBRouting}} {error "Unsupported route directive"}
if {![string is integer -strict $cpu_hz] || $cpu_hz < 6000000 ||
    $cpu_hz > 200000000 || $cpu_hz % 1000000} {error "Expected whole MHz, 6..200 MHz"}
set placed [file normalize $placed]
set out [file normalize $out]
if {[file exists [file join $out routed_initial.dcp]]} {error "Use a fresh route output directory"}
file mkdir $out
set_param general.maxThreads 8
open_checkpoint $placed
set cpu [get_clocks -quiet clk_out1_clk_wiz_ddr]
if {[llength $cpu] != 1 || abs([get_property PERIOD $cpu] - 1.0e9 / $cpu_hz) > 0.001} {
    error "Checkpoint does not have the requested real CPU clock"
}
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Unresolved board black boxes"}
source [file join [file dirname [info script]] audit_reset_cdc.tcl]
audit_board_reset_cdc [file join $out reset_cdc_audit.txt]
audit_cpu_reset_gate [file join $out reset_gate_audit.txt]
if {$flow ne "post-route"} {route_design -directive $route_directive -tns_cleanup}
# Save before optional expensive optimization, so every stage is recoverable.
write_checkpoint [file join $out routed_initial.dcp]
report_timing_summary -delay_type min_max -file [file join $out initial_timing.rpt]
report_bus_skew -file [file join $out initial_bus_skew.rpt]
report_timing -group clk_out1_clk_wiz_ddr -max_paths 40 -nworst 1 -file [file join $out initial_cpu_paths.rpt]
if {$flow eq "route-only"} {close_design; exit}
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {![llength $setup] || ![llength $hold]} {error "Missing routed timing paths"}
set skew_file [open [file join $out initial_bus_skew.rpt] r]
set skew_text [read $skew_file]
close $skew_file
if {[get_property SLACK $setup] < 0 || [get_property SLACK $hold] < 0 ||
    [regexp {\(VIOLATED\)} $skew_text]} {
    puts "ROUTE_CONTINUATION: post-route physical optimization required"
    # Target the critical cells; avoid repeated all-net placement searches.
    phys_opt_design -critical_cell_opt -rewire
} else {
    puts "ROUTE_CONTINUATION: routed setup/hold/skew met; skip redundant post-route optimization"
}
write_checkpoint [file join $out routed.dcp]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing_summary.rpt]
report_timing -delay_type max -max_paths 30 -input_pins -file [file join $out timing_paths.rpt]
report_timing -group clk_out1_clk_wiz_ddr -delay_type max -max_paths 30 -input_pins -file [file join $out cpu_timing_paths.rpt]
report_timing -delay_type min -max_paths 10 -file [file join $out hold_paths.rpt]
report_utilization -hierarchical -file [file join $out utilization.rpt]
report_route_status -file [file join $out route_status.rpt]
report_bus_skew -file [file join $out bus_skew.rpt]
report_clock_interaction -file [file join $out clock_interaction.rpt]
report_cdc -file [file join $out cdc.rpt]
check_timing -verbose -file [file join $out check_timing.rpt]
report_drc -file [file join $out drc.rpt]
set setup [get_timing_paths -group clk_out1_clk_wiz_ddr -delay_type max -max_paths 1]
puts "DDR CPU $cpu_hz Hz: WNS=[get_property SLACK $setup] DATA_DELAY=[get_property DATAPATH_DELAY $setup]"
# No bit here: the separate release script remains the mandatory signoff gate.
close_design
