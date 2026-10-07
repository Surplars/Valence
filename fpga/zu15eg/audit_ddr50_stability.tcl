# Read-only signoff audit; does not write or alter the input checkpoint.
# vivado -mode batch -source audit_ddr50_stability.tcl -tclargs ROUTED_DCP REPORT_DIR [CANDIDATE_XDC]
if {$argc != 2 && $argc != 3} {error "Expected ROUTED_DCP REPORT_DIR [CANDIDATE_XDC]"}
lassign $argv dcp report_dir
file mkdir $report_dir
set_param general.maxThreads 8
open_checkpoint $dcp
# Optional validation applies the new board attributes only in this in-memory design.
# No checkpoint/bitstream is written; placement is NOT redone by this audit.
if {$argc == 3} {read_xdc [lindex $argv 2]}
set uart_meta [get_cells -quiet -hier -filter {NAME =~ */uart/rxMeta_reg}]
set uart_sync [get_cells -quiet -hier -filter {NAME =~ */uart/rxSync_reg}]
if {[llength $uart_meta] != 1 || [llength $uart_sync] != 1} {
    error "Expected exactly one UART RX metastability stage and one synchronized stage"
}
set audit [open [file join $report_dir uart_sync_audit.txt] w]
foreach cell [concat $uart_meta $uart_sync] {
    puts $audit "$cell REF_NAME=[get_property REF_NAME $cell] ASYNC_REG=[get_property ASYNC_REG $cell]"
    set qp [get_pins -of_objects $cell -filter {REF_PIN_NAME == Q}]
    puts $audit "  Q endpoints: [all_fanout -flat -endpoints_only -from $qp]"
}
set meta_d [get_pins -of_objects $uart_meta -filter {REF_PIN_NAME == D}]
set sync_d [get_pins -of_objects $uart_sync -filter {REF_PIN_NAME == D}]
puts $audit "meta D sources: [all_fanin -flat -startpoints_only -to $meta_d]"
puts $audit "sync D sources: [all_fanin -flat -startpoints_only -to $sync_d]"
foreach cell [get_cells -quiet -hier -filter {NAME =~ *reset_pipe_reg*}] {
    puts $audit "$cell ASYNC_REG=[get_property ASYNC_REG $cell]"
}
close $audit
report_timing -from $uart_meta -to $uart_sync -delay_type min_max -max_paths 4 \
    -file [file join $report_dir uart_sync_timing.rpt]
report_clock_interaction -file [file join $report_dir clock_interaction.rpt]
report_cdc -file [file join $report_dir cdc.rpt]
check_timing -verbose -file [file join $report_dir check_timing.rpt]
close_design
