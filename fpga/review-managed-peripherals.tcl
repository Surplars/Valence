# Reports only from saved route. No synthesis/place/route/bit.
if {$argc != 3} { error "expected ROUTE_DCP FRESH_REPORTS CONSTRAINT_DIR" }
set output [file normalize [lindex $argv 1]]
if {[file exists $output]} { error "fresh reports required" }
file mkdir $output
cd $output
set_param general.maxThreads 8
open_checkpoint [lindex $argv 0]
source [file join [lindex $argv 2] managed-peripheral-constraints.tcl]
valence_managed_peripheral_constraints
report_timing_summary -delay_type min_max -report_unconstrained -file post_route_timing.rpt
report_cdc -details -file post_route_cdc.rpt
report_bus_skew -warn_on_violation -file post_route_bus_skew.rpt
report_exceptions -coverage -file exception_coverage.rpt
set seq [get_cells -hier -filter {IS_SEQUENTIAL == 1}]
set starts [get_pins -of_objects $seq -filter {REF_PIN_NAME == C || REF_PIN_NAME == CLK || REF_PIN_NAME == WCLK}]
set ends [get_pins -of_objects $seq -filter {REF_PIN_NAME == D || REF_PIN_NAME == CE}]
report_timing -from $starts -to $ends -delay_type max -max_paths 30 -file internal_setup.rpt
report_timing -from $starts -to $ends -delay_type min -max_paths 20 -file internal_hold.rpt
foreach name {cpu aon uart_raw tx_raw rx_raw} {
    report_timing -from [get_clocks $name] -to [get_clocks $name] -delay_type max -max_paths 5 -file $name-setup.rpt
}
write_checkpoint post_route_reviewed.dcp
puts "MANAGED_PERIPHERALS_REVIEW_DONE no_new_implementation"
exit
