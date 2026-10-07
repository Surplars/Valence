# One combined managed UART/native GMAC/CMU OOC. Not CPU/RGMII/board/bit signoff.
if {$argc != 3 && $argc != 4} { error "expected RTL FRESH_REPORTS CONSTRAINT_DIR ?SYNTH_DCP?" }
set rtl [file normalize [lindex $argv 0]]
set output [file normalize [lindex $argv 1]]
set constraints [file normalize [lindex $argv 2]]
if {[file exists $output]} { error "refusing to overwrite reports" }
file mkdir $output
cd $output
set_param general.maxThreads 8
if {$argc == 4} {
    open_checkpoint [lindex $argv 3]
} else {
    create_project -in_memory -part xczu15eg-ffvb1156-2-i
    read_verilog -sv [glob -directory $rtl *.sv]
    synth_design -top ManagedPeripheralBank -mode out_of_context -flatten_hierarchy none
    if {[llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]} { error "functional black box" }
    create_clock -name cpu -period 10.000 [get_ports sourceClock]
    create_clock -name aon -period 20.000 [get_ports alwaysOnClock]
    create_clock -name uart_raw -period 20.000 [get_ports rawUartClock]
    create_clock -name tx_raw -period 8.000 [get_ports rawTxClock]
    create_clock -name rx_raw -period 8.000 [get_ports rawRxClock]
    write_checkpoint post_synth_unconstrained.dcp
    close_design
    open_checkpoint post_synth_unconstrained.dcp
}
source [file join $constraints managed-peripheral-constraints.tcl]
valence_managed_peripheral_constraints
report_utilization -file post_synth_utilization.rpt
report_cdc -details -file post_synth_cdc.rpt
write_checkpoint post_synth.dcp
opt_design
place_design
route_design
report_utilization -file post_route_utilization.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file post_route_timing.rpt
report_timing -delay_type max -max_paths 30 -file setup_paths.rpt
report_timing -delay_type min -max_paths 20 -file hold_paths.rpt
report_clock_interaction -file post_route_clock_interaction.rpt
report_cdc -details -file post_route_cdc.rpt
report_bus_skew -warn_on_violation -file post_route_bus_skew.rpt
report_drc -file post_route_drc.rpt
write_checkpoint post_route.dcp
set seq [get_cells -hier -filter {IS_SEQUENTIAL == 1}]
set starts [get_pins -of_objects $seq -filter {REF_PIN_NAME == C || REF_PIN_NAME == CLK || REF_PIN_NAME == WCLK}]
set ends [get_pins -of_objects $seq -filter {REF_PIN_NAME == D || REF_PIN_NAME == CE}]
report_timing -from $starts -to $ends -delay_type max -max_paths 30 -file internal_setup.rpt
report_timing -from $starts -to $ends -delay_type min -max_paths 20 -file internal_hold.rpt
puts "MANAGED_PERIPHERALS_OOC_DONE internal_only_not_board"
exit
