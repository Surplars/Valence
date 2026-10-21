# Actual native pin names; pure mock proofs are NOT native mapped qualification.
source [file join [file dirname [info script]] common_cdc.tcl]
proc assert {condition why} {if {![uplevel 1 [list expr $condition]]} {error $why}}
set ::fixedSource u_ddr/inst/u_ddr4_infrastructure/u_bufg_divClk/O
set ::fabricSource u_clk_wiz/inst/clkout3_buf/O
set ::domains {};set ::fault {};set ::aliasState GROUND
foreach pin [list $::fixedSource u_soc/ddrClock u_soc/ddrCrossing/ddrClock u_soc/fixedTimer/timebaseClock u_soc/fixedTimer/timer/clock u_soc/debugCrossing/sourceClock u_soc/debugCrossing/requests/sourceClock u_debug/debug_clk] {dict set ::domains $pin fixed}
foreach pin [list $::fabricSource u_soc/fabricClock u_soc/ddrCrossing/fabricClock u_soc/fixedTimer/fabricClock u_soc/debugCrossing/destinationClock u_soc/debugCrossing/requests/destinationClock] {dict set ::domains $pin fabric}
proc common_cdc::one {kind name} {
    if {![dict exists $::domains $name] && $name ni {u_soc/timebaseClock u_soc/debugClock}} {error "missing actual pin $name"}
    return $name
}
proc common_cdc::clock pin {
    if {$::fault eq {active_floating} && $pin eq {u_soc/debugCrossing/sourceClock}} {error {active clock floating}}
    if {$::fault eq {wrong_clock} && $pin eq {u_soc/debugCrossing/sourceClock}} {return fabric}
    return [dict get $::domains $pin]
}
proc get_clocks args {
    if {[lsearch -exact $args -of_objects]>=0} {return {}}
    return [lindex $args end]
}
proc get_property {key object} {
    if {$key eq {PERIOD}} {return 4.0}
    if {$key eq {DIRECTION}} {return [expr {$::fault eq {wrong_direction} ? {OUT} : {IN}}]}
    return $object
}
proc get_nets args {if {$::aliasState eq {DISCONNECTED}} {return {}};return literal_ground}
proc all_fanout args {if {$::fault eq {residual_load}} {return active_ff/C};return {}}
proc common_cdc::same_net {a b} {
    if {[dict get $::domains $a] ne [dict get $::domains $b]} {error {active nets differ}}
}
proc common_cdc::distinct_net {a b} {
    if {[dict get $::domains $a] eq [dict get $::domains $b]} {error {active nets collapsed}}
}
proc common_cdc::drivers pin {
    if {$::fault eq {wrong_driver} && $pin eq {u_soc/fixedTimer/timer/clock}} {return unrelated/O}
    if {[dict get $::domains $pin] eq {fixed}} {return [list $::fixedSource]}
    return [list $::fabricSource]
}
proc common_cdc::constant {pin value} {
    if {$::fault eq {dynamic_alias} || $pin ni {u_soc/timebaseClock u_soc/debugClock} || $value!=0} {error {alias not literal GND}}
}
assert {[common_cdc::static_clock_anchors u_soc u_soc/fixedTimer u_soc/debugCrossing] eq {fixed}} {GND aliases rejected despite proved active anchors}
foreach ::fault {wrong_clock wrong_driver dynamic_alias wrong_direction} {
    assert {[catch {common_cdc::static_clock_anchors u_soc u_soc/fixedTimer u_soc/debugCrossing} why]} "active anchor mutation accepted: $::fault"
}
set ::fault {};set ::aliasState DISCONNECTED
assert {[common_cdc::static_clock_anchors u_soc u_soc/fixedTimer u_soc/debugCrossing] eq {fixed}} {opt-disconnected exact aliases rejected}
foreach ::fault {active_floating residual_load wrong_driver wrong_clock wrong_direction} {
    assert {[catch {common_cdc::static_clock_anchors u_soc u_soc/fixedTimer u_soc/debugCrossing} why]} "disconnected alias mutation accepted: $::fault"
}
set ::fault {}
assert {[catch {common_cdc::clock_alias u_soc/otherClock u_soc/debugCrossing/sourceClock fixed} why]} {unreviewed disconnected alias accepted}
dict set ::domains u_soc/debugCrossing/requests/sourceClock fabric
assert {[catch {common_cdc::static_clock_anchors u_soc u_soc/fixedTimer u_soc/debugCrossing} why]} {mailbox source miswire accepted}
puts ACTIVE_CLOCK_ANCHOR_GND_AND_DISCONNECTED_ALIAS_POSITIVES_ACTIVE_FLOATING_RESIDUAL_LOAD_DIRECTION_DRIVER_AND_MAILBOX_NEGATIVES_PASS
