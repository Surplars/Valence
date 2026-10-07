# Source-matched, five-pin repair of FIXED-mode IDELAYE3 CLK only.
# Preserve the complete routed parent and all CPU RTL/synthesis results.
if {$argc != 2} {error "Expected ROUTED_PARENT_DCP FRESH_OUTPUT_DIR"}
lassign $argv dcp out
if {[file exists $out]} {error "Preserve existing evidence"}
file mkdir $out
cd $out
set_param general.maxThreads 8
open_checkpoint $dcp
set delays [get_cells -quiet -hier -filter {NAME =~ u_rgmii/receive_delay*.data_delay && REF_NAME == IDELAYE3}]
if {[llength $delays] != 5} {error "Expected all five native RX delays"}
set zero [get_nets -of_objects [get_pins [lindex $delays 0]/CE]]
if {[llength $zero] != 1} {error "Missing fixed control constant"}
set drivers [get_pins -leaf -of_objects $zero -filter {DIRECTION == OUT}]
set owners [get_cells -of_objects $drivers]
if {[llength $owners] != 1 || [get_property REF_NAME $owners] ne "GND"} {
    error "Control constant is not driven by GND"
}
foreach cell $delays {
    if {[get_property DELAY_TYPE $cell] ne "FIXED" || [get_property DELAY_FORMAT $cell] ne "TIME"} {
        error "Never remove a VARIABLE/VAR_LOAD control clock"
    }
    set pin [get_pins $cell/CLK]
    set old [get_nets -of_objects $pin]
    set clk [get_clocks -of_objects $pin]
    if {[llength $old]!=1 || [llength $clk]!=1 || abs([get_property PERIOD $clk]-2.0)>0.001} {
        error "Expected original 500MHz control connection"
    }
    puts "FIXED_CLK_REPAIR $pin $old -> $zero"
    disconnect_net -net $old -objects $pin
    connect_net -net $zero -objects $pin
}
set ref [get_clocks -of_objects [get_pins u_rgmii/delay_control/REFCLK]]
if {[llength $ref]!=1 || abs([get_property PERIOD $ref]-2.0)>0.001} {error "REFCLK was altered"}
write_checkpoint repaired_unrouted.dcp
route_design -directive Explore
write_checkpoint routed.dcp
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_timing -delay_type max -max_paths 40 -input_pins -file setup_paths.rpt
report_timing -delay_type min -max_paths 30 -input_pins -file hold_paths.rpt
set cpu [get_clocks -of_objects [get_pins u_soc/clock]]
set cpuRegs [all_registers -clock $cpu]
report_timing -from $cpuRegs -to $cpuRegs -delay_type min_max -max_paths 5 -input_pins -file cpu_internal.rpt
foreach family {fetchPacket multiplier mulDiv} {
    set targets [get_cells -quiet -hier -filter "NAME =~ u_soc/*/$family/* && IS_SEQUENTIAL"]
    if {[llength $targets]==0} {error "Missing CPU timing family $family"}
    report_timing -from $cpu -to $targets -delay_type max -max_paths 5 -input_pins -file ${family}_setup.rpt
}
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_io.rpt
report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file rx_io.rpt
report_utilization -hierarchical -file utilization.rpt
report_cdc -details -file cdc.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_route_status -file route_status.rpt
report_exceptions -coverage -file exception_coverage.rpt
report_clock_interaction -file clock_interaction.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
puts "FIXED_CLK_REPAIR_COMPLETE REQUIRES_SIGNOFF NO_BIT_GENERATED"
close_design
