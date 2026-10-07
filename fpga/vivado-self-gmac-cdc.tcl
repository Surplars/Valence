# One small three-clock CDC/retention-policy OOC candidate, not CPU/board/bit.
# Arguments: frozen RTL directory, fresh report directory, frozen constraint dir.
if {$argc != 3} { error "expected: RTL FRESH_REPORTS CONSTRAINT_DIR" }
set rtl [file normalize [lindex $argv 0]]
set output [file normalize [lindex $argv 1]]
set constraintDir [file normalize [lindex $argv 2]]
if {[file exists $output]} { error "refusing to overwrite report directory" }
file mkdir $output
cd $output
set_param general.maxThreads 8
create_project -in_memory -part xczu15eg-ffvb1156-2-i
set files [glob -nocomplain -directory $rtl *.sv]
if {[llength $files] < 4} { error "incomplete CDC RTL export" }
read_verilog -sv $files
synth_design -top SelfGmacCdcTop -mode out_of_context -flatten_hierarchy none
if {[llength [get_cells -hier -filter {IS_BLACKBOX == 1}]] != 0} { error "functional black box" }
create_clock -name control -period 10.000 [get_ports controlClock]
create_clock -name tx -period 8.000 [get_ports txClock]
create_clock -name rx -period 8.000 [get_ports rxClock]
source [file join $constraintDir native-gmac-cdc-constraints.tcl]
valence_native_gmac_cdc_constraints "" 8.0
report_utilization -file post_synth_utilization.rpt
report_cdc -details -file post_synth_cdc.rpt
write_checkpoint post_synth.dcp
opt_design
place_design
route_design
report_utilization -file post_route_utilization.rpt
report_timing_summary -delay_type min_max -file post_route_timing.rpt
report_clock_interaction -file post_route_clock_interaction.rpt
report_cdc -details -file post_route_cdc.rpt
report_bus_skew -warn_on_violation -file post_route_bus_skew.rpt
report_drc -file post_route_drc.rpt
write_checkpoint post_route.dcp
set sequential [get_cells -hier -filter {IS_SEQUENTIAL == 1}]
set starts [get_pins -of_objects $sequential -filter {DIRECTION == OUT && REF_PIN_NAME == Q}]
set ends [get_pins -of_objects $sequential -filter {REF_PIN_NAME == D || REF_PIN_NAME == CE}]
report_timing -from $starts -to $ends -delay_type max -max_paths 20 -file internal_setup.rpt
report_timing -from $starts -to $ends -delay_type min -max_paths 20 -file internal_hold.rpt
puts "NATIVE_GMAC_CDC_OOC_REPORTS_DONE not_board_or_gate_signoff"
exit
