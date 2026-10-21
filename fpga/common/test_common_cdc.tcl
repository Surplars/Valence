# Pure Tcl helpers/mutation tripwire; not a synthesized-netlist qualification.
source [file join [file dirname [info script]] common_cdc.tcl]
set ::common_board_definitions_only 1
source [file join [file dirname [info script]] board_audit.tcl]
proc assert {condition why} {if {![uplevel 1 [list expr $condition]]} {error $why}}
assert {[common_cdc::quote {u_soc/x_reg[4]}] eq {u_soc/x_reg\[4\]}} {regex escaping failed}
assert {[common_board::json "a\"b\nc"] eq {"a\"b\nc"}} {JSON escaping failed}
assert {[common_board::object [dict create a PASS]] eq {{"a":"PASS"}}} {JSON object failed}
# Definitions-only sourcing may never execute any Vivado mutation.
foreach name {set_max_delay set_bus_skew set_false_path set_clock_groups set_property} {
    proc $name args {error "UNEXPECTED_MUTATION"}
}
source [file join [file dirname [info script]] common_cdc.tcl]
source [file join [file dirname [info script]] board_audit.tcl]
proc get_cells args {return {}}
assert {[catch {common_cdc::bank absent_reg 5} message]} {missing Gray bank incorrectly accepted}
assert {[string match {*bank shape changed*} $message]} {wrong missing-bank diagnostic}
rename common_cdc::ff common_cdc::real_ff
rename common_cdc::drivers common_cdc::real_drivers
proc common_cdc::ff args {}
proc common_cdc::drivers args {return wrong_launch/Q}
assert {[catch {common_cdc::pair first second destination_clock} message]} {non-direct synchronizer accepted}
assert {[string match {*non-direct stage0*} $message]} {wrong direct-chain diagnostic}
puts COMMON_CDC_NEGATIVE_CONTROLS_PASS_MISSING_BANK_AND_WRONG_DRIVER
proc common_cdc::drivers args {return combinational/O}
assert {[catch {common_cdc::registered_level_source idle clk reset} message]} {combinational idle announcement accepted}
assert {[string match {*one direct source FF Q*} $message]} {wrong combinational idle diagnostic}
proc common_cdc::drivers args {return {source0/Q source1/Q}}
assert {[catch {common_cdc::registered_level_source idle clk reset} message]} {multiple idle drivers accepted}
puts COMMON_CDC_IDLE_NEGATIVE_CONTROLS_REJECT_COMBINATIONAL_AND_MULTIPLE_DRIVERS
puts COMMON_CDC_HELPER_TEST_PASS_NOT_NETLIST_QUALIFIED
