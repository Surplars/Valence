# Reuse endpoint/clock/census mutations and then exercise the second explicit
# static topology profile. Mock tests are not synthesized-netlist qualification.
source [file join [file dirname [info script]] test_boot50_cdc.tcl]
set ::clockChecks {};set ::periodChecks {}
proc common_cdc::expect_clock {pin expected {period {}}} {
    dict set ::clockChecks $pin $expected
    if {$period ne {}} {dict set ::periodChecks $pin $period}
}
set scopes [common_cdc::collect_static u_soc u_soc/fixedTimer u_soc/debugCrossing performance300-static]
assert {[llength $scopes]==32} {performance boundary scopes changed}
assert {abs([dict get $::periodChecks u_soc/cpuClock]-1000.0/300)<0.000001} {performance CPU not 300 MHz}
assert {[dict get $::periodChecks u_soc/fabricClock]==4.0} {performance fabric not 250 MHz}
foreach pin {ddrClock timebaseClock debugClock} {
    assert {[dict get $::periodChecks u_soc/$pin]==4.0} {fixed domain not 250 MHz}
    assert {[dict get $::clockChecks u_soc/$pin] eq {fixed}} {fixed domain identity changed}
}
assert {[dict get $::periodChecks u_soc/alwaysOnClock]==20.0} {always-on not 50 MHz}
assert {[dict get $::clockChecks u_soc/fabricClock] eq {fabric}} {separate generated fabric clock lost}
assert {[catch {common_cdc::collect_static u_soc timer debug unreviewed} why]} {unknown profile accepted}
proc common_cdc::clock pin {
    switch -glob $pin {*/cpuClock {return cpu} */alwaysOnClock {return aon} default {return fixed}}
}
assert {[catch {common_cdc::collect_static u_soc timer debug performance300-static} why]} {fabric tied to UI unexpectedly accepted}
assert {[string match {*clock identities disagree*} $why]} {wrong collapsed-domain diagnostic}
puts PERFORMANCE300_CDC_PROFILE_AND_COLLAPSED_CLOCK_GUARDS_PASS_NOT_NETLIST_QUALIFIED

set ::collapseNet 0
proc get_nets args {
    if {$::collapseNet} {return shared_ui_net}
    return [list [lindex $args end]_net]
}
common_cdc::tested_distinct_net fabricClock ddrClock
set ::collapseNet 1
assert {[catch {common_cdc::tested_distinct_net fabricClock ddrClock} why]} {aliased physical net accepted}
assert {[string match {*physical clock nets collapsed*} $why]} {wrong physical-net diagnostic}
proc get_nets args {return {}}
assert {[catch {common_cdc::tested_distinct_net fabricClock ddrClock} why]} {unconnected physical clock accepted}
puts PERFORMANCE300_EXACT_PHYSICAL_CLOCK_NET_GUARDS_PASS
