# Continue saved clock ECO, move only the serial TX CMU buffer off DIV's input.
if {$argc!=2} {error "Expected MODIFIED_DCP FRESH_OUT"}
lassign $argv baseline out
if {[file exists $out]} {error "Preserve evidence"}
file mkdir $out
cd $out
file copy [info script] executed_resume.tcl
set_param general.maxThreads 8
open_checkpoint $baseline
set gate [get_cells u_soc/nativeBank/gmac/txManaged_gate/buffer]
set frozen [dict create]
set all [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}]
foreach c [get_property NAME $all] loc [get_property LOC $all] bel [get_property BEL $all] {
    if {$c ne $gate} {dict set frozen $c [list $loc $bel]}
}
set regions [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AC8]]]
set occupied {}
foreach c [get_cells -hier -filter {REF_NAME == BUFGCE && LOC != ""}] {
    if {$c ne $gate && [regexp {BUFGCE_X0Y([0-9]+)} [get_property LOC $c] -> y]} {lappend occupied [expr {$y%24}]}
}
# DIV input muxes share the +5 BUFGCE of each six-site group; output at +0.
foreach c [get_cells -hier -filter {REF_NAME == BUFGCE_DIV && LOC != ""}] {
    regexp {BUFGCE_DIV_X0Y([0-9]+)} [get_property LOC $c] -> y
    lappend occupied [expr {($y%4)*6}] [expr {($y%4)*6+5}]
}
set target ""
foreach s [lsort -dictionary [get_sites -of_objects $regions -filter {SITE_TYPE == BUFGCE}]] {
    if {[llength [get_cells -quiet -of_objects $s]]==0 && [regexp {BUFGCE_X0Y([0-9]+)} $s -> y] && [expr {$y%24}] ni $occupied} {set target $s; break}
}
if {$target eq ""} {error "No independent TX managed track"}
set in [get_nets -of_objects [get_pins $gate/I]]
set output [get_nets -of_objects [get_pins $gate/O]]
route_design -unroute -nets [list $in $output]
set_property IS_LOC_FIXED FALSE $gate
set_property CLOCK_REGION $regions $gate
place_cell [list $gate $target]
set_property USER_CLOCK_ROOT $regions $output
puts "TX_CMU_BUFFER_MOVED_OFF_DIV_SHARED_INPUT TARGET=$target CE_TYPE=[get_property CE_TYPE $gate]"
update_clock_routing
route_design -preserve
write_checkpoint routed.dcp
set all [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}]
foreach c [get_property NAME $all] loc [get_property LOC $all] bel [get_property BEL $all] {
    if {[dict exists $frozen $c] && [list $loc $bel] ne [dict get $frozen $c]} {error "Unexpected placement change $c"}
}
puts "SAVED_PLACEMENTS_PRESERVED [dict size $frozen] ONLY_TX_CMU_BUFFER_MOVED"
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_io.rpt
report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file rx_io.rpt
set controls [get_cells -hier -filter {NAME =~ native_tx_divider_* && REF_NAME == FDPE}]
report_timing -from $controls -delay_type min_max -max_paths 12 -input_pins -file phase_release.rpt
report_timing -to [get_pins {u_eth_clk_wiz/inst/clkout1_buf/CLR native_tx90_forward_buffer/CLR}] -delay_type min_max -max_paths 8 -input_pins -file divider_clear.rpt
report_timing -delay_type max -max_paths 20 -input_pins -file setup_paths.rpt
report_timing -delay_type min -max_paths 20 -input_pins -file hold_paths.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_cdc -details -file cdc.rpt
report_route_status -file route_status.rpt
report_clocks -file clocks.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
puts "NATIVE_COMMON_SOURCE_DIV4_RESUME_COMPLETE NO_CPU_SYNTHESIS_NO_BIT"
close_design
