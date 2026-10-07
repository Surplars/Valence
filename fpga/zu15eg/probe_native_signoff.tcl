# Read-only investigation of the completed board; no placement/route mutation.
if {$argc != 2} {error "Expected ROUTED_DCP FRESH_OUTPUT_DIR"}
lassign $argv dcp out
if {[file exists $out]} {error "Preserve existing evidence: $out"}
file mkdir $out
cd $out
open_checkpoint $dcp
help update_clock_routing
help route_design
help place_cell
foreach path {rx_clock_buffer u_eth_clk_wiz/inst/clkout1_buf u_eth_clk_wiz/inst/clkout2_buf} {
    set pin [get_pins $path/O]
    set net [get_nets -of_objects $pin]
    puts "CLOCK $path net=$net root=[get_property CLOCK_ROOT $net] user=[get_property USER_CLOCK_ROOT $net]"
    report_property [get_cells $path]
}
foreach pattern {phy_reset_pipe_reg* tx_reset_pipe_reg* rx_reset_pipe_reg*} {
    foreach cell [get_cells $pattern] {
        report_property $cell
        foreach ref {PRE D Q} {
            set pin [get_pins $cell/$ref]
            set net [get_nets -of_objects $pin]
            puts "RESET $pin net=$net drivers=[get_pins -leaf -of_objects [get_nets -segments $net] -filter {DIRECTION == OUT}]"
        }
    }
}
foreach pin [get_pins -hier -filter {REF_PIN_NAME == RDY && NAME =~ u_rgmii/*}] {
    puts "READY $pin [get_nets -of_objects $pin]"
}
set old [get_nets -of_objects [get_pins {rx_reset_pipe_reg[0]/PRE}]]
puts "RX_RESET_INPUTS [all_fanin -flat -startpoints_only -to [get_pins {rx_reset_pipe_reg[0]/PRE}]]"
report_property [get_cells -of_objects [get_pins -leaf -of_objects $old -filter {DIRECTION == OUT}]]
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_timing -to [get_ports {c0_ddr4_reset_n}] -delay_type min_max -max_paths 2 -input_pins -file ddr_reset.rpt
report_clock_networks -file clock_networks.rpt
puts "PROBE_COMPLETE READ_ONLY"
close_design
