set ::common_board_definitions_only 1
source [file join [file dirname [info script]] board_audit.tcl]
proc assert {condition why} {if {![uplevel 1 [list expr $condition]]} {error $why}}
set ::visited {}
proc common_board::resets {} {lappend ::visited resets;error reset_failed}
proc common_board::io {} {lappend ::visited io;error io_failed}
proc common_board::cdc {} {lappend ::visited cdc;error gray_exception_missing}
assert {[catch {common_board::reset_io_cdc} why]} {independent failures not propagated}
assert {$::visited eq {resets io cdc}} {reset/io failure hid CDC timing audit}
foreach failure {reset_failed io_failed gray_exception_missing} {
    assert {[string first $failure $why]>=0} {an independent failure was lost}
}
set ::visited {}
proc common_board::resets {} {lappend ::visited resets}
proc common_board::io {} {lappend ::visited io}
proc common_board::cdc {} {lappend ::visited cdc}
common_board::reset_io_cdc
assert {$::visited eq {resets io cdc}} {passing audit census changed}
puts INDEPENDENT_RESET_IO_CDC_AUDIT_NEGATIVES_PASS
