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
namespace eval common_cdc {}
proc common_cdc::one {kind name} {return $name}
proc common_cdc::names {objects} {return $objects}
proc common_cdc::clock {pin} {return clk}
proc common_cdc::constant {pin value} {error {not a literal constant}}
set ::fixture_ce GROUND
set ::fixture_init {1'b0}
set ::fixture_ref FDCE
set ::fixture_valid fifo/state/Q
set ::fixture_valid_disconnected 0
set ::fixture_valid_absent 0
set ::fixture_payload_absent 0
set ::fixture_source_present 0
proc get_cells {args} {
 if {[lsearch -exact $args -filter]>=0} {return fifo/state}
 if {[lsearch -exact $args -of_objects]>=0} {return [file dirname [lindex $args end]]}
 return [lindex $args end]
}
proc get_property {key object} {
 switch $key {
  NAME {return $object}
  TYPE {if {$object eq {ce_net}} {return $::fixture_ce};return SIGNAL}
  REF_NAME {return $::fixture_ref}
  INIT {return $::fixture_init}
  default {error "unexpected property $key"}
 }
}
proc get_pins {args} {
 set f [lsearch -exact $args -filter]
 if {$f>=0} {
  set query [lindex $args [expr {$f+1}]]
  if {$query eq {REF_PIN_NAME == source_valid}} {if {$::fixture_source_present} {return fifo/source_valid};return {}}
  if {$query eq {REF_PIN_NAME == destination_valid}} {if {$::fixture_valid_absent} {return {}};return fifo/destination_valid}
  if {$query eq {REF_PIN_NAME =~ destination_bits*}} {if {$::fixture_payload_absent} {return {}};return fifo/destination_bits0}
  if {$query eq {DIRECTION == OUT}} {
   set net [lindex $args [expr {[lsearch -exact $args -of_objects]+1}]]
   if {$net eq {valid_net}} {return $::fixture_valid}
   return external/Q
  }
 }
 error "unexpected pin query $args"
}
proc get_nets {args} {
 switch [lindex $args end] {
  fifo/destination_bits0 {return {}}
  fifo/destination_valid {if {$::fixture_valid_disconnected} {return {}};return valid_net}
  fifo/state/CE {return ce_net}
  fifo/state/D {return arbitrary_d_net}
  default {error "unexpected net query $args"}
 }
}
assert {[common_zero::prove fifo]==1} {disabled INIT-zero state not proved}
set ::fixture_source_present 1
assert {[common_zero::prove fifo]==1} {arbitrary retained input rejected despite full invariant-zero proof}
set ::fixture_ce SIGNAL
assert {[common_zero::prove fifo]==0} {arbitrary enabled D accepted}
set ::fixture_source_present 0
set ::fixture_ce GROUND
set ::fixture_init {1'b1}
assert {[common_zero::prove fifo]==0} {INIT-one state accepted}
set ::fixture_init {1'b0}
set ::fixture_ref RAM32M
assert {[common_zero::prove fifo]==0} {payload RAM accepted}
set ::fixture_ref FDCE
set ::fixture_valid external/Q
assert {[common_zero::prove fifo]==0} {arbitrary output valid accepted}
set ::fixture_valid_disconnected 1
assert {[common_zero::prove fifo]==1} {unobserved valid with invariant-zero state rejected}
set ::fixture_ce SIGNAL
assert {[common_zero::prove fifo]==0} {unobserved valid incorrectly waived live functional state}
set ::fixture_ce GROUND
set ::fixture_valid_disconnected 0
set ::fixture_valid fifo/state/Q
set ::fixture_payload_absent 1
assert {[common_zero::prove fifo]==1} {absent payload with zero state/valid rejected}
set ::fixture_ce SIGNAL
assert {[common_zero::prove fifo]==0} {absent payload incorrectly waived live state}
set ::fixture_valid_absent 1;set ::fixture_ce GROUND
assert {[common_zero::prove fifo]==1} {absent valid with invariant-zero state rejected}
set ::fixture_ce SIGNAL
assert {[common_zero::prove fifo]==0} {absent valid incorrectly waived live functional state}
puts INACTIVE_ZERO_INDUCTION_POSITIVE_AND_NEGATIVE_CONTROLS_PASS_NOT_NETLIST_QUALIFIED
