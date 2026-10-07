# Read-only diagnostic: no implementation or bit generation, no saved ECO.
# Arguments: PLACED_OR_ROUTED_DCP STRICT_CONSTRAINTS_TCL EMPTY_OUTPUT_DIR.
if {$argc != 3} {error "Expected DCP CONSTRAINTS_TCL EMPTY_OUTPUT_DIR"}
lassign $argv dcp constraints out
if {[file exists $out]} {error "Preserve prior diagnostic"}
file mkdir $out
cd $out
set_param general.maxThreads 8
open_checkpoint $dcp
puts "REMOVE_OUTPUT_DELAY_COMMAND=[info commands remove_output_delay]"
puts "RESET_TIMING_COMMAND=[info commands reset_timing]"
foreach cell [get_cells -quiet -hier -filter {REF_NAME =~ BUFG* || REF_NAME =~ MMCM*}] {
    puts "CLOCK_PLACEMENT $cell LOC=[get_property LOC $cell]"
}
foreach pin {AA7 AC8} {
    set pad [get_package_pins $pin]
    # Query supported package-pin properties rather than assuming SITE exists.
    puts "PHY_PAD $pin [report_property -return_string $pad]"
}
set cpu [get_clocks -of_objects [get_pins u_soc/clock]]
set registers [all_registers -clock $cpu]
report_timing -from $cpu -to $registers -group $cpu -delay_type max \
    -max_paths 20 -input_pins -file cpu_internal_setup.rpt
report_timing -to [get_ports {eth_mdc eth_mdio led}] -delay_type max \
    -max_paths 12 -input_pins -file management_outputs.rpt
report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type min \
    -max_paths 10 -input_pins -file rx_hold_original.rpt
set presets [get_pins -quiet -hier -filter {REF_PIN_NAME == PRE && NAME =~ *release_0_reg*}]
report_timing -to $presets -delay_type max -max_paths 10 -file reset_recovery_before.rpt
# MIG's PHY regeneration may replace/restore source constraints. Reapply the
# SAME narrowly audited contracts in memory and report coverage; do not save.
source $constraints
valence_native_board_constraints
report_timing -to $presets -delay_type max -max_paths 10 -file reset_recovery_after.rpt
report_timing_summary -delay_type min_max -file strict_reapplied_summary.rpt
report_exceptions -coverage -file strict_exception_coverage.rpt
report_cdc -details -file strict_cdc.rpt
puts "READ_ONLY_BOUNDARY_DIAGNOSTIC_COMPLETE NO_CHECKPOINT_OR_BIT_WRITTEN"
close_design
