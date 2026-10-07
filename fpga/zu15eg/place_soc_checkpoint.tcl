# Recover from an assembled board checkpoint without repeating SoC synthesis.
# Args: ASSEMBLED_DCP OUTPUT_DIR CPU_HZ [PLACE_DIRECTIVE [ROUTE_DIRECTIVE]]
if {$argc < 3 || $argc > 6} {error "Expected ASSEMBLED_DCP OUTPUT_DIR CPU_HZ ?PLACE_DIRECTIVE ?ROUTE_DIRECTIVE ?FLOW???"}
lassign $argv assembled out cpu_hz place_directive route_directive flow
if {$flow eq ""} {set flow complete}
if {$flow ni {complete place-only}} {error "Unsupported placement flow"}
if {$place_directive eq ""} {set place_directive Explore}
if {$route_directive eq ""} {set route_directive Explore}
if {$place_directive ni {Explore AltSpreadLogic_high AltSpreadLogic_medium}} {error "Unsupported place directive"}
if {$route_directive ni {Explore AlternateCLBRouting}} {error "Unsupported route directive"}
set assembled [file normalize $assembled]
set out [file normalize $out]
if {[file exists [file join $out placed.dcp]]} {error "Use a fresh output directory"}
file mkdir $out
set_param general.maxThreads 8
open_checkpoint $assembled
set cpu [get_clocks -quiet clk_out1_clk_wiz_ddr]
if {[llength $cpu] != 1 || abs([get_property PERIOD $cpu] - 1.0e9 / $cpu_hz) > 0.001} {
    error "Checkpoint does not have the requested real CPU clock"
}
opt_design
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Unresolved board black boxes"}
source [file join [file dirname [info script]] audit_reset_cdc.tcl]
audit_board_reset_cdc [file join $out reset_cdc_audit.txt]
audit_cpu_reset_gate [file join $out reset_gate_audit.txt]
write_checkpoint [file join $out optimized.dcp]
puts "BOARD_IMPLEMENTATION: place=$place_directive route=$route_directive"
place_design -directive $place_directive
write_checkpoint [file join $out placed.dcp]
report_timing_summary -delay_type min_max -file [file join $out placed_timing.rpt]
report_timing -group clk_out1_clk_wiz_ddr -max_paths 40 -nworst 1 -file [file join $out placed_cpu_paths.rpt]
if {$flow eq "place-only"} {close_design; exit}
# The route stage saves its initial DCP before doing any targeted optimization.
set argv [list [file join $out placed.dcp] [file join $out routing] $cpu_hz $route_directive]
set argc 4
source [file join [file dirname [info script]] route_soc_checkpoint.tcl]
