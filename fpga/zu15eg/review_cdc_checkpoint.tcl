# Report-only correction of constraints after synthesis register merging.
if {$argc != 2} { error "usage: review_cdc_checkpoint.tcl CDC_DCP FRESH_OUTPUT" }
set checkpoint [file normalize [lindex $argv 0]]
set output [file normalize [lindex $argv 1]]
if {[file exists $output]} { error "Use fresh output" }
file mkdir $output
open_checkpoint $checkpoint
# Rebuild the full constraint view, removing previous invalid Q startpoints.
reset_timing -invalid
create_clock -name cpu_clock -period 10.0 [get_ports sourceClock]
create_clock -name mac_clock -period 8.0 [get_ports destinationClock]
source [file join [file dirname [info script]] cdc_constraints.tcl]
valence_register_cdc_constraints bridge 8.0
valence_stream_cdc_constraints fifo 8.0
set_input_delay -clock mac_clock 0 [get_ports irqIn]
set_input_delay -clock cpu_clock 0 [get_ports -filter {DIRECTION == IN && (NAME =~ source_* || NAME =~ streamIn_*)}]
set_input_delay -clock mac_clock 0 [get_ports -filter {DIRECTION == IN && (NAME =~ destination_* || NAME == streamOut_ready)}]
set_output_delay -clock cpu_clock 0 [get_ports -filter {DIRECTION == OUT && (NAME =~ source_* || NAME == streamIn_ready || NAME == irqOut)}]
set_output_delay -clock mac_clock 0 [get_ports -filter {DIRECTION == OUT && (NAME =~ destination_* || NAME =~ streamOut_*)}]
set_max_delay -datapath_only 8.0 -from [get_ports irqIn] \
    -to [get_pins -of_objects [get_cells {irq/stages_reg?0?}] -filter {REF_PIN_NAME == D}]
set_false_path -from [get_ports commonReset] \
    -to [get_pins -hierarchical -filter {REF_PIN_NAME == CLR || REF_PIN_NAME == PRE}]
report_cdc -details -file [file join $output cdc.rpt]
report_clock_interaction -file [file join $output clock_interaction.rpt]
report_timing_summary -report_unconstrained -file [file join $output timing.rpt]
report_bus_skew -file [file join $output bus_skew.rpt]
report_exceptions -file [file join $output exceptions.rpt]
set regs [all_registers]
report_timing -from $regs -to $regs -delay_type max -max_paths 20 -file [file join $output internal_setup.rpt]
report_timing -from $regs -to $regs -delay_type min -max_paths 10 -file [file join $output internal_hold.rpt]
write_checkpoint [file join $output constrained.dcp]
puts "CDC_CONSTRAINT_REVIEW_COMPLETE"
