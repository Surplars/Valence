# Routed INTERNAL OOC diagnostic only, NOT a board frequency claim or a bit.
# Reuses the completed, source-qualified DCP; does not rerun synthesis.
if {$argc != 3} { error "usage: route_diagnostic.tcl RTL_PACKAGE CONSTRAINED_DCP FRESH_OUTPUT" }
lassign $argv package checkpoint output
foreach name {package checkpoint output} { set $name [file normalize [set $name]] }
if {[file exists $output]} { error "fresh physical evidence required" }
file mkdir $output
set_param general.maxThreads 8
open_checkpoint $checkpoint
if {[get_property TOP [current_design]] ne "FiveStageFpgaShell" ||
    [string tolower [get_property PART [current_design]]] ne "xczu15eg-ffvb1156-2-i"} {
    error "independent I1 shell/part required"
}
set clock [get_clocks orbital_i1_cpu]
if {[llength $clock] != 1 || abs([get_property PERIOD $clock] - 3.333) > 0.0005} {
    error "preserve the qualified 300MHz target"
}
# An explicit hypothetical fabric clock site provides OOC routing's source
# location. No actual board Clock Wizard or MIG is instantiated here.
set sites [lsort [get_sites -filter {SITE_TYPE == BUFGCE}]]
if {[llength $sites] == 0} { error "missing actual UltraScale+ clock sites" }
set site [lindex $sites 0]
set_property HD.CLK_SRC $site [get_ports io_clockIn]
puts "I1_OOC_HYPOTHETICAL_CLOCK_SITE=$site NOT_BOARD_SIGNOFF"
set primitive [get_property NAME [get_cells -hierarchical -filter {REF_NAME == BSCANE2}]]
if {![regsub {([/.])user_scan$} $primitive {\1transport} engine]} { error "USER2 sibling shape" }
source [file join $package bscan_timing.tcl]
opt_design -directive Explore
valence_reapply_bscan_cdc $primitive $engine orbital_i1_cpu
write_checkpoint [file join $output optimized.dcp]
place_design -directive Explore
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $output timing_placed.rpt]
write_checkpoint [file join $output placed.dcp]
phys_opt_design -directive AggressiveExplore
route_design -directive Explore
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $output timing_routed.rpt]
report_timing -delay_type max -max_paths 40 -nworst 1 -file [file join $output setup_routed.rpt]
report_timing -delay_type min -max_paths 30 -nworst 1 -file [file join $output hold_routed.rpt]
report_bus_skew -file [file join $output bus_skew_routed.rpt]
report_route_status -file [file join $output route_status.rpt]
report_utilization -file [file join $output utilization.rpt]
check_timing -verbose -file [file join $output check_timing.rpt]
write_checkpoint [file join $output routed.dcp]
puts "I1_INTERNAL_OOC_ROUTING_DONE NOT_BOARD_NOT_MIG_NO_BIT"
close_design
