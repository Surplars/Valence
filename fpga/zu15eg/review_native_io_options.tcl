# Read-only I/O timing alternatives in memory. Restore output drive after sweep.
# First rebuild ALL related raw/managed clock trees, preserving CPU placement.
# No bit generation; retain each report including unsuccessful alternatives.
if {$argc != 2} {error "Expected ROUTED_ECO_DCP FRESH_OUTPUT_DIR"}
lassign $argv dcp out
if {[file exists $out]} {error "Preserve existing evidence"}
file mkdir $out
cd $out
set_param general.maxThreads 8
open_checkpoint $dcp
set clocks {}
foreach pin {rx_clock_buffer/O u_eth_clk_wiz/inst/clkout1_buf/O u_soc/nativeBank/gmac/txManaged_gate/buffer/O u_soc/nativeBank/gmac/rxManaged_gate/buffer/O} {
    set net [get_nets -of_objects [get_pins $pin]]
    if {[llength $net]!=1} {error "Missing related clock: $pin"}
    lappend clocks $net
}
route_design -unroute -nets $clocks
set_property USER_CLOCK_ROOT X3Y2 $clocks
update_clock_routing
route_design -preserve
write_checkpoint aligned_roots.dcp
report_timing_summary -delay_type min_max -file aligned_timing_summary.rpt
foreach drive {8 12 16} {
    set_property DRIVE $drive [get_ports {eth_txc eth_txd[*] eth_tx_ctl}]
    report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_drive${drive}.rpt
}
set_property DRIVE 8 [get_ports {eth_txc eth_txd[*] eth_tx_ctl}]
# UG903: forwarded clock source is the output-DDR CLOCK INPUT, not a remote
# hierarchy pin. Evaluate the same 2ns PHY-delay/1.75ns I/O contract unchanged.
set source [get_pins u_rgmii/tx_clock_ddr/CLK]
set masters [get_clocks -of_objects $source]
if {[llength $source]!=1 || [llength $masters]!=1 || abs([get_property PERIOD $masters]-8.0)>0.001} {
    error "Missing actual forwarded-clock CLK/125MHz master; CLKDIV is unused on this UltraScale+ ODDR"
}
# Same output/name without -add replaces the previous clock definition.
create_generated_clock -name phy_tx_capture -source $source -edges {1 2 3} -edge_shift {2.0 2.0 2.0} [get_ports eth_txc]
foreach edge {rise fall} {
    set args {}
    if {$edge eq "fall"} {set args {-clock_fall -add_delay}}
    set_output_delay -clock phy_tx_capture {*}$args -max 1.750 [get_ports {eth_txd[*] eth_tx_ctl}]
    set_output_delay -clock phy_tx_capture {*}$args -min -1.750 [get_ports {eth_txd[*] eth_tx_ctl}]
}
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_forwarded_source.rpt
report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file rx_aligned.rpt
report_route_status -file route_status.rpt
puts "NATIVE_IO_OPTIONS_COMPLETE NO_BIT_GENERATED"
close_design
