source [file join [file dirname [info script]] common_cdc.tcl]
proc assert {condition why} {if {![uplevel 1 [list expr $condition]]} {error $why}}
set ::literal 0;set ::init 0;set ::pair_valid 1
proc common_cdc::bank {prefix width} {return {first second}}
proc common_cdc::constant {pin value} {if {$::literal ne "$value"} {error {dynamic or different literal}}}
proc common_cdc::clock {pin} {return destination_clock}
proc common_cdc::pair args {if {!$::pair_valid} {error {wrong clock, reset, fanout or FF structure}}}
proc common_cdc::one {kind name} {return $name}
proc get_property {key cell} {if {$key ne {INIT}} {error {unexpected property}};return $::init}
assert {[common_cdc::constant_zero_level scalar]} {valid zero scalar rejected}
set ::literal dynamic
assert {![common_cdc::constant_zero_level scalar]} {dynamic scalar classified static}
set ::literal 1
assert {![common_cdc::constant_zero_level scalar]} {reset-low literal-one transition classified static}
set ::literal 0;set ::init 1
assert {[catch {common_cdc::constant_zero_level scalar}]} {nonzero initial state accepted}
set ::init X
assert {[catch {common_cdc::constant_zero_level scalar}]} {unknown initial state accepted}
set ::init 0;set ::pair_valid 0
assert {[catch {common_cdc::constant_zero_level scalar}]} {invalid actual synchronizer pair accepted}
puts CONSTANT_SCALAR_ZERO_INVARIANT_POSITIVE_NEGATIVE_CONTROLS_PASS
