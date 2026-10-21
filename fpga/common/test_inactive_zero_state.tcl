source [file join [file dirname [info script]] inactive_zero_state.tcl]
proc assert {condition text} {if {![uplevel 1 [list expr $condition]]} {error $text}}
# Ternary evaluation is conservative: unknowns represent both values, with no
# inferred correlation. I0 is the least significant LUT truth-table index.
assert {[common_zero::lut 4'h8 {0 X}] eq {0}} {AND annihilator failed}
assert {[common_zero::lut 4'h8 {1 X}] eq {X}} {live AND incorrectly constant}
assert {[common_zero::lut 4'h6 {X X}] eq {X}} {unknown XOR treated as correlated}
assert {[common_zero::lut 2'h1 {0}] eq {1}} {inverter failed}
assert {[common_zero::lut 8'h80 {1 1 1}] eq {1}} {LUT index order changed}
assert {[common_zero::lut 64'h8000000000000000 {1 1 1 1 1 X}] eq {X}} {64-bit INIT truncated}
assert {[common_zero::lut 64'h8000000000000000 {1 1 1 1 1 1}] eq {1}} {64-bit INIT lost high bit}
assert {[catch {common_zero::lut 4'hx {0 0}}]} {unknown INIT accepted}
puts INACTIVE_ZERO_LUT_TEST_PASS_NOT_NETLIST_QUALIFIED
