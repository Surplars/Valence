# Report-only review of the ONE routed CDC candidate. Never synth/place/route.
if {$argc != 3} { error "expected: ROUTED_DCP FRESH_OUTPUT CONSTRAINT_DIR" }
set checkpoint [file normalize [lindex $argv 0]]
set output [file normalize [lindex $argv 1]]
set constraintDir [file normalize [lindex $argv 2]]
if {[file exists $output]} { error "refusing to overwrite review output" }
file mkdir $output
cd $output
set_param general.maxThreads 8
open_checkpoint $checkpoint
source [file join $constraintDir native-gmac-cdc-constraints.tcl]
valence_native_gmac_cdc_constraints "" 8.0
report_timing_summary -delay_type min_max -file timing.rpt
report_cdc -details -file cdc.rpt
report_clock_interaction -file clock_interaction.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_exceptions -file exceptions.rpt
foreach name {txFifo rxFifo} {
    set starts [get_pins -quiet -hier -filter "NAME =~ $name/fifo/storage_ext/* && (REF_PIN_NAME == CLK || REF_PIN_NAME == WCLK)"]
    set ends [get_pins -of_objects [get_cells -quiet "$name/fifo/output_0_reg*"] -filter {REF_PIN_NAME == D}]
    report_timing -from $starts -to $ends -delay_type max -max_paths 38 -file "${name}_payload.rpt"
}
set setup [get_timing_paths -delay_type max -max_paths 1]
set setupSlack [get_property SLACK $setup]
set sequential [get_cells -hier -filter {IS_SEQUENTIAL == 1}]
set starts [get_pins -of_objects $sequential -filter {DIRECTION == OUT && REF_PIN_NAME == Q}]
set ends [get_pins -of_objects $sequential -filter {REF_PIN_NAME == D || REF_PIN_NAME == CE}]
report_timing -from $starts -to $ends -delay_type max -max_paths 20 -file internal_setup.rpt
report_timing -from $starts -to $ends -delay_type min -max_paths 20 -file internal_hold.rpt
write_checkpoint reviewed_route.dcp
if {$setupSlack < 0} { error "CDC routed max-delay/setup requirement not met: $setupSlack" }
puts "NATIVE_GMAC_CDC_REVIEW_DONE same_route_no_synthesis setup_slack=$setupSlack"
exit
