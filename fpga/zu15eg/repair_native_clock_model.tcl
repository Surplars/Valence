# Correct STA coverage only: do not place, route, synthesize or generate a bit.
if {$argc != 2} {error "Expected ROUTED_DCP FRESH_OUTPUT_DIR"}
lassign $argv dcp out
if {[file exists $out]} {error "Preserve existing evidence"}
file mkdir $out
cd $out
set_param general.maxThreads 8
open_checkpoint $dcp
set source [get_pins -quiet u_rgmii/tx_clock_ddr/CLK]
set masters [get_clocks -quiet -of_objects $source]
if {[llength $source]!=1 || [llength $masters]!=1 || abs([get_property PERIOD $masters]-8.0)>0.001} {
    error "Actual forwarded-clock CLK must have exactly one 8ns master"
}
puts "VALID_FORWARDED_MASTER $source $masters [get_property PERIOD $masters]"
create_generated_clock -name phy_tx_capture -source $source -edges {1 2 3} -edge_shift {2.0 2.0 2.0} [get_ports eth_txc]
foreach edge {rise fall} {
    set args {}
    if {$edge eq "fall"} {set args {-clock_fall -add_delay}}
    set_output_delay -clock phy_tx_capture {*}$args -max 1.750 [get_ports {eth_txd[*] eth_tx_ctl}]
    set_output_delay -clock phy_tx_capture {*}$args -min -1.750 [get_ports {eth_txd[*] eth_tx_ctl}]
}
foreach port [get_ports {eth_txd[*] eth_tx_ctl}] {
    foreach delay {max min} {
        set paths [get_timing_paths -quiet -to $port -delay_type $delay -max_paths 1]
        if {[llength $paths]!=1} {error "Missing finite TX $delay path: $port"}
        set slack [get_property SLACK $paths]
        if {![string is double -strict $slack] || abs($slack)>1000} {error "Invalid TX clock coverage: $port $slack"}
        puts "TX_COVERAGE $port $delay $slack"
    }
}
write_checkpoint routed.dcp
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_io.rpt
report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file rx_io.rpt
set cpuClock [get_clocks -quiet clk_out1_clk_wiz_ddr]
if {[llength $cpuClock]!=1 || abs([get_property PERIOD $cpuClock]-10.0)>0.001} {error "CPU clock is not the 100MHz baseline"}
report_timing -from $cpuClock -to $cpuClock -delay_type min_max -max_paths 2 -input_pins -file cpu100.rpt
report_timing -delay_type min -slack_lesser_than 0 -max_paths 30 -input_pins -file failing_hold.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_cdc -details -file cdc.rpt
report_route_status -file route_status.rpt
report_clocks -file clocks.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
puts "NATIVE_ACTUAL_CLOCK_STA_COMPLETE NO_PLACE_ROUTE_SYNTH_OR_BIT"
close_design
