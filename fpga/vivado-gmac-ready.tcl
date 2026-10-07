# One combined native batch: new CDC boundary, then actual full-F/D CPU.
# Does not open the user's board project, generate a bit, or run full-board sim.
if {$argc != 3} { error "usage: vivado-gmac-ready.tcl CORE_RTL CDC_RTL FRESH_REPORT_ROOT" }
set batch_core [file normalize [lindex $argv 0]]
set batch_cdc [file normalize [lindex $argv 1]]
set batch_reports [file normalize [lindex $argv 2]]
set batch_scripts [file dirname [info script]]
if {[file exists $batch_reports]} { error "Preserve previous timing evidence" }
file mkdir $batch_reports
set_param general.maxThreads 8
create_project -in_memory -part xczu15eg-ffvb1156-2-i
read_verilog -sv [glob [file join $batch_cdc *.sv]]
synth_design -top ClockDomainCdcTop -mode out_of_context -flatten_hierarchy none
create_clock -name cpu_clock -period 10.0 [get_ports sourceClock]
create_clock -name mac_clock -period 8.0 [get_ports destinationClock]
source [file join $batch_scripts zu15eg cdc_constraints.tcl]
valence_register_cdc_constraints bridge 8.0
valence_stream_cdc_constraints fifo 8.0
# An external persistent IRQ uses the same two-stage level synchronizer.
set_max_delay -datapath_only 8.0 -from [get_ports irqIn] \
    -to [get_pins -of_objects [get_cells {irq/stages_reg?0?}] -filter {REF_PIN_NAME == D}]
# Only the external reset's assertion is asynchronous; release is synchronized.
set_false_path -from [get_ports commonReset] \
    -to [get_pins -hierarchical -filter {REF_PIN_NAME == CLR || REF_PIN_NAME == PRE}]
set cpu_inputs [get_ports -filter {DIRECTION == IN && (NAME =~ source_* || NAME =~ streamIn_*)}]
set mac_inputs [get_ports -filter {DIRECTION == IN && (NAME =~ destination_* || NAME == streamOut_ready)}]
set_input_delay -clock cpu_clock 0 $cpu_inputs
set_input_delay -clock mac_clock 0 $mac_inputs
set_input_delay -clock mac_clock 0 [get_ports irqIn]
set_output_delay -clock cpu_clock 0 [get_ports -filter {DIRECTION == OUT && (NAME =~ source_* || NAME == streamIn_ready || NAME == irqOut)}]
set_output_delay -clock mac_clock 0 [get_ports -filter {DIRECTION == OUT && (NAME =~ destination_* || NAME =~ streamOut_*)}]
set cdc_out [file join $batch_reports CDC]
file mkdir $cdc_out
report_cdc -details -file [file join $cdc_out post_synth_cdc.rpt]
report_clock_interaction -file [file join $cdc_out post_synth_clock_interaction.rpt]
opt_design
place_design
route_design
report_cdc -details -file [file join $cdc_out post_route_cdc.rpt]
report_clock_interaction -file [file join $cdc_out post_route_clock_interaction.rpt]
report_timing_summary -report_unconstrained -file [file join $cdc_out post_route_timing.rpt]
report_utilization -file [file join $cdc_out post_route_utilization.rpt]
report_bus_skew -file [file join $cdc_out post_route_bus_skew.rpt]
write_checkpoint [file join $cdc_out post_route.dcp]
close_project
set argc 6
set argv [list $batch_core xczu15eg-ffvb1156-2-i 10.0 MachineCore route [file join $batch_reports MachineCore]]
source [file join $batch_scripts vivado-module-ooc.tcl]
close_project
puts "GMAC_READY_BATCH_COMPLETE"
