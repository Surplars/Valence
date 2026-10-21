# Pure mapping contracts with deliberately incomplete/mutated mock netlists.
# These do NOT substitute for native synthesis/CDC/timing qualification.
source [file join [file dirname [info script]] common_cdc.tcl]
proc assert {condition why} {if {![uplevel 1 [list expr $condition]]} {error $why}}
foreach name {set_max_delay set_bus_skew set_false_path set_clock_groups set_property} {
    proc $name args {error "UNEXPECTED_MUTATION"}
}
proc get_pins args {return {}}
assert {[catch {common_cdc::clock absent/C} why]} {missing endpoint accepted}
assert {[string match {*missing exact object*} $why]} {wrong missing endpoint diagnostic}
rename common_cdc::clock common_cdc::actual_clock
proc common_cdc::clock pin {return wrong_clock}
assert {[catch {common_cdc::expect_clock endpoint/C fixed_clock} why]} {wrong clock accepted}
assert {[string match {*incorrect clock at*} $why]} {wrong clock diagnostic}
proc common_cdc::clock pin {return fixed_clock}
proc get_clocks args {return fixed_clock}
proc get_property {key object} {if {$key eq {PERIOD}} {return 20.0};return $object}
assert {[catch {common_cdc::expect_clock endpoint/C fixed_clock 4.0} why]} {fixed timebase slowed to fabric accepted}
assert {[string match {*incorrect clock period*} $why]} {wrong period diagnostic}
proc get_cells args {return {}}
assert {[catch {common_cdc::exact_modules root HeldResponseCdcDataFifo* {root/empty_fifo}} why]} {missing AXI lane accepted}
assert {[string match {*exact module census changed*} $why]} {wrong census diagnostic}
assert {[catch {common_cdc::register_payload bridge requestHeld request {data 64} fabric fixed} why]} {missing MMIO payload accepted}
assert {[string match {*missing dynamic register payload*} $why]} {wrong MMIO diagnostic}
# A new first stage cannot be silently omitted even if ASYNC_REG is correct.
proc get_cells args {return {root/newSync_stage0_reg[0]}}
proc get_property {key object} {
    switch $key {NAME {return $object} REF_NAME {return FDCE} ASYNC_REG {return TRUE}}
}
assert {[catch {common_cdc::new_stage_coverage {root} {}} why]} {unmapped new stage accepted}
assert {[string match {*uncovered new first-stage*} $why]} {wrong stage coverage diagnostic}
# Missing exact exported mailbox bits must never be treated as constants.
proc get_cells args {return {}}
assert {[catch {common_cdc::mailbox_width mailbox 41 fixed_clock fixed_clock} why]} {missing mailbox endpoint accepted}
assert {[string match {*missing exact object*} $why]} {wrong mailbox endpoint diagnostic}
puts BOOT50_CDC_NEGATIVE_CONTROLS_PASS_NOT_NETLIST_QUALIFIED
# Exercise actual ABI parsing and source/destination mapping, not just absence.
proc get_cells args {return {bridge/request_data_reg[3] bridge/request_write_reg}}
proc get_property {key object} {return $object}
rename common_cdc::ff common_cdc::original_ff
proc common_cdc::ff {cell expected args} {}
rename common_cdc::constant common_cdc::original_constant
proc common_cdc::constant args {error dynamic}
rename common_cdc::drivers common_cdc::original_drivers
proc common_cdc::drivers pin {return [list [string map {request_ requestHeld_ /D /Q} $pin]]}
rename common_cdc::budget common_cdc::original_budget
proc common_cdc::budget args {return 4.0}
set scope [common_cdc::register_payload bridge requestHeld request {data 64 write 1} fabric fixed]
assert {[dict get $scope ends] eq {{bridge/request_data_reg[3]/D} bridge/request_write_reg/D}} {MMIO capture mapping changed}
proc common_cdc::drivers pin {return unrelated/Q}
assert {[catch {common_cdc::register_payload bridge requestHeld request {data 64 write 1} fabric fixed} why]} {MMIO bypass accepted}
assert {[string match {*register payload bypass*} $why]} {wrong bypass diagnostic}
puts BOOT50_REGISTER_ABI_MAPPING_AND_BYPASS_TEST_PASS
# Dry-run collection verifies all live channel directions and expected 32 scopes.
# Endpoint proofs above remain separate; this mock is never netlist evidence.
foreach name {one expect_clock exact_modules gray payload level mailbox_width register_payload new_stage_coverage distinct_net} {
    rename common_cdc::$name common_cdc::tested_$name
}
proc common_cdc::one args {}
proc common_cdc::clock pin {
    switch -glob $pin {*/cpuClock {return cpu} */fabricClock {return fabric} */alwaysOnClock {return aon} default {return fixed}}
}
set ::clockChecks {}
proc common_cdc::expect_clock {pin expected args} {dict set ::clockChecks $pin $expected}
proc common_cdc::exact_modules args {}
proc common_cdc::distinct_net args {}
proc common_cdc::gray {h direction args} {return [list label $h/$direction]}
proc common_cdc::payload h {return [list label $h/payload]}
proc common_cdc::level h {return [list label $h]}
proc common_cdc::mailbox_width {h width source destination} {return [list label $h width $width]}
proc common_cdc::register_payload {h from to args} {return [list label $h/$to]}
proc common_cdc::new_stage_coverage args {}
set scopes [common_cdc::collect_boot50 u_soc u_soc/fixedTimer u_soc/debugCrossing]
assert {[llength $scopes]==32} {new boundary scope census changed}
foreach suffix {{} _1 _3} {
    assert {[dict get $::clockChecks u_soc/ddrCrossing/empty_fifo$suffix/sourceClock] eq {fabric}} {AXI forward source changed}
    assert {[dict get $::clockChecks u_soc/ddrCrossing/empty_fifo$suffix/destinationClock] eq {fixed}} {AXI forward destination changed}
}
foreach suffix {_2 _4} {
    assert {[dict get $::clockChecks u_soc/ddrCrossing/empty_fifo$suffix/sourceClock] eq {fixed}} {AXI return source changed}
    assert {[dict get $::clockChecks u_soc/ddrCrossing/empty_fifo$suffix/destinationClock] eq {fabric}} {AXI return destination changed}
}
assert {[dict get $::clockChecks u_soc/timebaseClock] eq {fixed}} {timebase not fixed}
assert {[dict get $::clockChecks u_soc/debugClock] eq {fixed}} {debug transport not fixed}
assert {[dict get $::clockChecks u_soc/fabricDdrReady_ddrReadySync/clockIn] eq {fabric}} {actual emitted DDR-ready instance not mapped}
puts BOOT50_SCOPE_CENSUS_AND_DIRECTIONS_PASS_NOT_NETLIST_QUALIFIED
# Exact constant output proof permits optimized-away constant mailbox bits only.
proc common_cdc::one {kind name} {return $name}
proc get_cells args {return {}}
proc common_cdc::constant {pin value} {
    if {$pin eq {mailbox/destination_bits[2]} && $value==0} {return}
    error dynamic
}
proc common_cdc::drivers pin {
    if {[regexp {^mailbox/captured_reg\[([0-9]+)\]/D$} $pin -> bit]} {
        return [list [format {mailbox/held_reg[%d]/Q} $bit]]
    }
    if {[regexp {^mailbox/destination_bits\[([0-9]+)\]$} $pin -> bit]} {
        return [list [format {mailbox/captured_reg[%d]/Q} $bit]]
    }
    error "Unexpected test endpoint $pin"
}
set scope [common_cdc::tested_mailbox_width mailbox 3 fixed fabric]
assert {[llength [dict get $scope ends]]==2} {constant mailbox output not proved narrowly}
proc common_cdc::one {kind name} {
    if {$name eq {mailbox/destination_bits[2]}} {error {COMMON_CDC missing exact object}}
    return $name
}
assert {[catch {common_cdc::tested_mailbox_width mailbox 3 fixed fabric} why]} {missing output mistaken for literal}
assert {[string match {*missing exact object*} $why]} {wrong missing constant endpoint diagnostic}
puts BOOT50_MAILBOX_CONSTANT_OUTPUT_PROOF_TEST_PASS
