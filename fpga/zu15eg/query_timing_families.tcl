# Read-only targeted reports from an existing implementation, never an ECO.
if {$argc != 2} {error "Expected ROUTED_DCP FRESH_OUTPUT_DIR"}
lassign $argv dcp out
if {[file exists $out]} {error "Preserve existing evidence"}
file mkdir $out
cd $out
open_checkpoint $dcp
set cpu [get_clocks -of_objects [get_pins u_soc/clock]]
foreach family {fetchPacket multiplier mulDiv} {
    set targets [get_cells -quiet -hier -filter "NAME =~ u_soc/*/$family/* && IS_SEQUENTIAL"]
    if {[llength $targets] == 0} {error "Missing family $family"}
    report_timing -from $cpu -to $targets -delay_type max -max_paths 5 -input_pins -file ${family}_setup.rpt
}
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_io.rpt
report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file rx_io.rpt
foreach pin {AA7 AC8} {
    set sites [get_sites -of_objects [get_package_pins $pin]]
    puts "PAD_SITES $pin $sites"
    foreach site $sites {puts "PAD_REGION $pin [get_clock_regions -of_objects $site]"}
}
help reset_timing
puts "TARGETED_TIMING_QUERY_COMPLETE NO_DESIGN_WRITTEN"
close_design
