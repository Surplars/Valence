# Bounded, read-only ancestry comparison. The actual output DDR CLK remains
# canonical unless equivalent edge/path propagation is independently proved.
# Keep all original PHY/PCB budgets. No route/DCP/bit edits.
if {$argc!=2} {error "Expected ROUTED_DCP FRESH_OUT"}
lassign $argv dcp out
if {[file exists $out]} {error "Preserve evidence"}
file mkdir $out
cd $out
file copy [info script] executed_review.tcl
set_param general.maxThreads 8
open_checkpoint $dcp
foreach {label source} {
    actual_ddr u_rgmii/tx_clock_ddr/CLK
    global_output u_eth_clk_wiz/inst/clkout1_buf/O
    global_input u_eth_clk_wiz/inst/clkout1_buf/I
    cmt_output native_rx_pll/CLKOUT0
} {
    set pin [get_pins $source]
    set clocks [get_clocks -of_objects $pin]
    if {[llength $pin]!=1 || [llength $clocks]!=1 || abs([get_property PERIOD $clocks]-8.0)>0.001} {error "Missing actual TX ancestry $source"}
    create_generated_clock -name phy_tx_capture -source $pin -edges {1 2 3} -edge_shift {2.0 2.0 2.0} [get_ports eth_txc]
    report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file ${label}_tx.rpt
    report_clocks -file ${label}_clocks.rpt
}
# Explore only electrical settings on the original actual-CLK model. All
# ports in the bus stay matched. No assumption that a drive sweep is a fix.
create_generated_clock -name phy_tx_capture -source [get_pins u_rgmii/tx_clock_ddr/CLK] -edges {1 2 3} -edge_shift {2.0 2.0 2.0} [get_ports eth_txc]
set ports [get_ports {eth_txc eth_txd[*] eth_tx_ctl}]
foreach drive {2 4 6} {
    set_property DRIVE $drive $ports
    report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file drive${drive}_tx.rpt
}
set_property DRIVE 8 $ports
puts "TX_ANCESTRY_REVIEW_COMPLETE NOT_SIGNOFF NO_BIT"
close_design
