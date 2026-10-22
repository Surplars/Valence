# Inactive payloads must not hide retained register-to-Gray-stage0 paths.
source [file join [file dirname [info script]] common_cdc.tcl]
proc assert {condition why} {if {![uplevel 1 [list expr $condition]]} {error $why}}
set ::cells {};set ::mode retained;set ::common_cdc::constant_stage0_endpoints {}
foreach direction {write captured} {
    set stem [dict get {write writeGray captured capturedGray} $direction]
    foreach suffix {{} Sync_stage0 Sync} {
        for {set i 0} {$i<5} {incr i} {lappend ::cells [format {fifo/%s%s_reg[%d]} $stem $suffix $i]}
    }
}
proc get_cells args {
    if {[lsearch -exact $args -of_objects]>=0} {return [file dirname [lindex $args end]]}
    if {[lsearch -exact $args -filter]>=0} {return $::cells}
    set pattern [lindex $args end];set found {}
    foreach c $::cells {if {[regexp $pattern $c]} {lappend found $c}}
    return $found
}
proc get_property {key object} {if {$key eq {REF_NAME}} {return FDCE};if {$key eq {INIT}} {return [expr {$::mode eq {bad_init} ? {1'b1} : {1'b0}}]};return $object}
proc common_cdc::one {kind name} {return $name}
proc common_cdc::clock pin {return [expr {[string match */sourceClock $pin] ? {cpu} : {fabric}}]}
proc common_cdc::budget args {return 3.3333333333333335}
proc common_cdc::pair args {}
proc common_cdc::ff args {}
proc common_cdc::constant {pin value} {
    if {$::mode in {literal bad_init} && $value==0} {return}
    error not_literal
}
proc common_cdc::drivers pin {
    if {$::mode eq {wrong_driver}} {return unrelated/Q}
    return [list [string map {Sync_stage0 {} /D /Q} $pin]]
}
foreach d {write captured} {
    set scope [common_cdc::inactive_gray fifo $d]
    assert {[llength [dict get $scope starts]]==5 && [llength [dict get $scope ends]]==5} {inactive retained Gray was omitted}
    assert {abs([dict get $scope budget]-1000.0/300)<0.000001} {inactive Gray budget changed}
}
assert {$::common_cdc::constant_stage0_endpoints eq {}} {register-driven inactive Gray falsely certified constant}
set ::mode wrong_driver
assert {[catch {common_cdc::inactive_gray fifo captured} why]} {inactive status bypassed Gray driver proof}
set ::mode literal
assert {[common_cdc::inactive_gray fifo captured] eq {}} {literal zero stages should have no register crossing}
assert {[llength $::common_cdc::constant_stage0_endpoints]==5} {constant proof must name exact endpoints}
set ::mode bad_init
assert {[catch {common_cdc::inactive_gray fifo captured} why]} {nonzero constant-stage INIT accepted}
set ::mode retained
set saved $::cells
set ::cells [lsearch -all -inline -not -exact $::cells {fifo/capturedGraySync_stage0_reg[4]}]
assert {[catch {common_cdc::inactive_gray fifo captured} why]} {partial missing receiver bank accepted}
set ::cells {}
assert {[common_cdc::inactive_gray fifo captured] eq {}} {fully absent receiver should require no exception}
set ::cells {fifo/unreviewed_replica_reg}
assert {[catch {common_cdc::inactive_gray fifo captured} why]} {renamed retained receiver hidden by absence proof}
# Missing application must also fail the existing exact endpoint timing audit.
rename common_cdc::objects common_cdc::original_objects
proc common_cdc::objects {kind names} {return $names}
proc get_timing_paths args {return path}
proc get_property {key object} {
    switch $key {ENDPOINT_PIN {return target/D} REQUIREMENT {return 0.667} SLACK {return -0.852} EXCEPTION {return {}} default {return $object}}
}
set out [file join /tmp inactive-gray-test-[pid]];file mkdir $out
set scope [dict create label inactive-retained starts source/C ends target/D budget 3.3333333333333335 skew 1 second {}]
assert {[catch {common_cdc::audit_timing [list $scope] $out} why]} {missing Gray maxdelay passed audit}
assert {[string match {*missing/relaxed/violating max-delay*} $why]} {wrong missing-constraint diagnostic}
file delete -force $out
# Exercise the real collect branch: all 26 inactive lanes still visit both
# Gray directions. Merely adding an unused helper would fail this regression.
source [file join [file dirname [info script]] common_cdc.tcl]
set ::visited {};set ::modules {root/time_0 root/scalar}
for {set i 0} {$i<26} {incr i} {lappend ::modules root/fifo$i}
proc common_cdc::one {kind name} {return $name}
proc get_cells args {if {[lsearch -exact $args -filter]>=0} {return {}};return $::modules}
proc get_property {key objects} {
    set values {}
    foreach object $objects {
        if {$key eq {NAME}} {lappend values $object
        } elseif {$key eq {CLASS}} {lappend values cell
        } elseif {[string match root/fifo* $object]} {lappend values HeldResponseCdcDataFifo
        } elseif {$object eq {root/time_0}} {lappend values CdcMailbox
        } else {lappend values CdcLevel}
    }
    if {[llength $objects]==1} {return [lindex $values 0]}
    return $values
}
proc common_cdc::inactive h {return 1}
proc common_cdc::inactive_gray {h direction} {
    lappend ::visited [list $h $direction]
    return [dict create label $h/$direction ends $h/$direction/D]
}
proc common_cdc::level h {return [dict create ends $h/D]}
proc common_cdc::mailbox h {return [dict create ends $h/D]}
proc common_cdc::clock pin {return clk}
proc common_cdc::exported_idle_source args {}
set actual [common_cdc::collect root]
assert {[llength $::visited]==52 && [llength $actual]==54} {inactive payload skipped retained Gray scopes}
puts INACTIVE_PAYLOAD_RETAINED_GRAY_AND_EXACT_CONSTANT_ABSENCE_NEGATIVES_PASS
