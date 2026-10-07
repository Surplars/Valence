# Correct STA phase representation and declare global same-column CMT routing
# on the ALREADY ROUTED physical candidate. No new hardware, synthesis or route.
if {$argc!=2} {error "Expected TX90_ROUTED_DCP FRESH_OUT"}
lassign $argv dcp out
if {[file exists $out]} {error "Preserve previous evidence"}
file mkdir $out
cd $out
file copy [info script] executed_tx90_model.tcl
set_param general.maxThreads 8
open_checkpoint $dcp
set mmcm [get_cells native_eth_mmcm]
if {[get_property CLKOUT1_PHASE $mmcm]!=90 || [get_property CLKOUT1_DIVIDE $mmcm]!=8} {error "Physical +2ns configuration absent"}
set uiPin [get_pins u_ddr/inst/u_ddr4_infrastructure/u_bufg_divClk/O]
set uiNet [get_nets -of_objects $uiPin]
set sourceRegion [get_clock_regions -of_objects [get_sites -of_objects [get_cells -of_objects $uiPin]]]
set destRegion [get_clock_regions -of_objects [get_sites [get_property LOC $mmcm]]]
regexp {^(X[0-9]+)Y} $sourceRegion -> sourceColumn
regexp {^(X[0-9]+)Y} $destRegion -> destColumn
if {$sourceColumn ne $destColumn} {error "Same-column dedicated routing contract invalid"}
set savedRoute [dict create]
foreach pin [list $uiPin u_eth_clk_wiz/inst/clkout1_buf/O u_eth_clk_wiz/inst/clkout2_buf/O native_tx90_forward_buffer/O rx_clock_buffer/O u_clk_wiz/inst/clkout1_buf/O] {
    set net [get_nets -of_objects [get_pins $pin]]
    dict set savedRoute $net [get_property ROUTE $net]
}
report_clocks -file before_clocks.rpt
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -file before_tx_io.rpt
set_property PHASESHIFT_MODE WAVEFORM $mmcm
set_property CLOCK_DEDICATED_ROUTE SAME_CMT_COLUMN $uiNet
create_generated_clock -name phy_tx_capture -source [get_pins u_rgmii/tx_clock_ddr/CLK] -divide_by 1 [get_ports eth_txc]
# No set_clock_latency, false path, multicycle path or relaxed I/O delay.
foreach net [dict keys $savedRoute] {
    if {[get_property ROUTE [get_nets $net]] ne [dict get $savedRoute $net]} {error "Clock routing unexpectedly changed"}
}
puts "SIX_CLOCK_ROUTES_UNCHANGED UI_SOURCE=$sourceRegion ETH_CMT=$destRegion SAME_CMT_COLUMN_NOT_FALSE"
report_property -file eth_mmcm.rpt $mmcm
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_io.rpt
report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file rx_io.rpt
report_timing -delay_type max -max_paths 20 -input_pins -file setup_paths.rpt
report_timing -delay_type min -max_paths 20 -input_pins -file hold_paths.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_cdc -details -file cdc.rpt
report_route_status -file route_status.rpt
report_clocks -file clocks.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
write_checkpoint routed.dcp
puts "NATIVE_TX90_MODEL_REVIEW_COMPLETE PHYSICAL_PHASE_UNCHANGED_NO_ROUTE_NO_BIT"
close_design
