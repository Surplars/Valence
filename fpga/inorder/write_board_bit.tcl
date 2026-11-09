# Invoked only after the routed signoff receipt passes the offline checks.
set_param general.maxThreads 8
set root [file normalize [lindex $argv 0]]
open_project [file join $root hardware i1_board.xpr]
open_checkpoint [file join $root implementation routed.dcp]
set badSetup [get_timing_paths -delay_type max -slack_lesser_than 0 -max_paths 1]
set badHold [get_timing_paths -delay_type min -slack_lesser_than 0 -max_paths 1]
report_drc -file [file join $root implementation drc_pre_bit.rpt]
if {[llength $badSetup] || [llength $badHold] || [llength [get_drc_violations -quiet -filter {SEVERITY == Error}]]} {
    error "routed board timing/DRC has not passed"
}
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
write_bitstream [file join $root i1_board.bit]
write_hw_platform -fixed -include_bit -force -file [file join $root i1_board.xsa]
puts PASS_FULL_BOARD_BITSTREAM_AND_XSA_WRITTEN_NOT_BOARD_TESTED
close_project
exit
