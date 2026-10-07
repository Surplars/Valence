# Read-only timing extraction from the saved routed full-board candidate.
# Does not substitute for the independent, full placement-equivalence audit.
if {$argc!=2} {error "Expected ROUTED_DCP REPORT_DIRECTORY"}
lassign $argv baseline out
if {![file exists $baseline]} {error "Missing routed checkpoint"}
foreach name {executed_reports.tcl tx_io.rpt timing_summary.rpt} {
    if {[file exists [file join $out $name]]} {error "Preserve prior reports: $name"}
}
file mkdir $out
cd $out
file copy [info script] executed_reports.tcl
set_param general.maxThreads 8
open_checkpoint $baseline
report_clocks -file clocks.rpt
set f [open clock_graph.rpt w]
foreach path {native_tx_ref_pll/CLKOUT0 u_eth_clk_wiz/inst/clkout2_buf/O u_eth_clk_wiz/inst/clkout1_buf/I u_eth_clk_wiz/inst/clkout1_buf/O native_tx90_forward_buffer/I native_tx90_forward_buffer/O u_rgmii/tx_clock_ddr/CLK} {
    puts $f "$path CLOCKS=[get_clocks -of_objects [get_pins $path]]"
}
foreach c [get_clocks] {
    puts $f "$c PERIOD=[get_property PERIOD $c] WAVEFORM=[get_property WAVEFORM $c] MASTER=[get_property MASTER_CLOCK $c] SOURCE=[get_property SOURCE_PINS $c]"
}
close $f
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_io.rpt
report_timing -to [get_pins {u_eth_clk_wiz/inst/clkout1_buf/CLR native_tx90_forward_buffer/CLR}] -delay_type min_max -max_paths 8 -input_pins -file divider_clear.rpt
report_timing -from [get_cells -hier -filter {NAME =~ native_tx_divider_* && REF_NAME == FDPE}] -delay_type min_max -max_paths 12 -input_pins -file phase_release.rpt
report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file rx_io.rpt
report_timing -delay_type max -max_paths 20 -input_pins -file setup_paths.rpt
report_timing -delay_type min -max_paths 20 -input_pins -file hold_paths.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_cdc -details -file cdc.rpt
report_route_status -file route_status.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
puts "READ_ONLY_NATIVE_DIVIDED_FULL_BOARD_REPORTS_COMPLETE NO_ROUTE_NO_BIT"
close_design
