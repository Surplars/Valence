# Finite Tcl model of native objects. This tests guards and exact mutation, not STA.
set helper [file normalize [file join [file dirname [info script]] dynamic reset_distribution_eco.tcl]]
source $helper
namespace eval mock {}
proc mock::object {name values} {variable db; dict set db $name [dict merge [dict create NAME $name] $values]}
proc mock::attach {pin net} {
    variable pn; variable np
    dict set pn $pin $net; dict lappend np $net $pin
}
proc mock::ff {n release index} {
    variable cells
    lappend cells $n
    object $n [dict create REF_NAME FDPE INIT 1'b1 ASYNC_REG [expr {$release ? 1 : ""}] DONT_TOUCH {} LOC SLICE_X1Y$index BEL SLICEL.AFF]
    foreach ref {C D CE PRE Q} {
        object $n/$ref [dict create DIRECTION [expr {$ref eq "Q" ? "OUT" : "IN"}] REF_PIN_NAME $ref IS_LEAF 1 IS_INVERTED 0]
    }
}
proc mock::init {} {
    variable db {}; variable pn {}; variable np {}; variable cells {}; variable calls 0; variable corrupt {}; variable root u_soc/cpuFunctionalReset_cpuResetDistribution
    set ::r38_reset_eco::used 0
    object design [dict create PART xczu15eg-ffvb1156-2-i TOP soc_top_common_ddr]
    object cpu_target300 [dict create PERIOD 3.333333333333]; object fabric_target250 [dict create PERIOD 4.0]
    foreach {n type driver ref} {
        clk SIGNAL cpu_clock/managed_buffer/O BUFGCE
        raw SIGNAL u_soc/cpuRelease_i_1/O LUT2
        ground GROUND u_soc/cpuRelease/GND/G GND
        power POWER u_soc/cpuRelease/VCC/P VCC
        power2 POWER u_soc/cpuFunctionalReset_cpuResetDistribution/VCC/P VCC
        local SIGNAL {u_soc/cpuRelease/release_0_reg[2]/Q} FDPE
        s0 SIGNAL {u_soc/cpuRelease/release_0_reg[0]/Q} FDPE
        s1 SIGNAL {u_soc/cpuRelease/release_0_reg[1]/Q} FDPE
    } {
        object $n [dict create TYPE $type]
        object [file dirname $driver] [dict create REF_NAME $ref]
        object $driver [dict create DIRECTION OUT IS_LEAF 1 IS_INVERTED 0 REF_PIN_NAME [file tail $driver]]
        attach $driver $n
    }
    for {set i 0} {$i<3} {incr i} {
        set n [format {u_soc/cpuRelease/release_0_reg[%d]} $i]; ff $n 1 $i
        foreach {ref net} [list C clk CE power PRE raw D [lindex {ground s0 s1} $i]] {attach $n/$ref $net}
    }
    set names [list $root/distributed_reg $root/distributed_reg_replica]
    for {set i 1} {$i<=39} {incr i} {lappend names $root/distributed_reg_replica_$i}
    set i 0
    foreach n $names {
        ff $n 0 $i
        foreach {ref net} {C clk CE power2 D local PRE raw} {attach $n/$ref $net}
        set qnet q$i; object $qnet [dict create TYPE SIGNAL]; attach $n/Q $qnet
        set count [expr {$i==40 ? 147 : 146}]
        for {set j 0} {$j<$count} {incr j} {
            set load u_soc/cpu/f${i}_$j/CLR; object $load [dict create DIRECTION IN]; attach $load $qnet
        }
        incr i
    }
    foreach net {raw local ground} {
        object other/$net [dict create DIRECTION IN]; attach other/$net $net
    }
}
proc mock::arg {args key} {set i [lsearch -exact $args $key]; if {$i<0} {error "Missing option $key"}; return [lindex $args [expr {$i+1}]]}
proc current_design {} {return design}
proc get_property {key xs} {
    set out {}; foreach x $xs {lappend out [dict get $::mock::db $x $key]}; if {[llength $out]==1} {return [lindex $out 0]}; return $out
}
proc get_cells {args} {
    if {[lsearch -exact $args -of_objects]>=0} {
        set result {}; foreach p [mock::arg $args -of_objects] {lappend result [file dirname $p]}; return [lsort -unique $result]
    }
    set pattern [lindex [mock::arg $args -filter] 2]; set out {}
    foreach c $::mock::cells {if {[string match $pattern $c]} {lappend out $c}}; return $out
}
proc get_clocks {args} {
    if {[lsearch -exact $args -of_objects]>=0} {return cpu_target300}
    return [lindex $args end]
}
proc get_pins {args} {
    set objects [mock::arg $args -of_objects]; set filter [mock::arg $args -filter]; set out {}
    foreach obj $objects {
        if {[dict exists $::mock::np $obj]} {set candidates [dict get $::mock::np $obj]} else {
            set candidates {}; foreach r {C D CE PRE Q} {lappend candidates $obj/$r}
        }
        foreach p $candidates {
            if {[lsearch -exact $args -leaf]>=0 && [dict exists $::mock::db $p IS_LEAF] && ![dict get $::mock::db $p IS_LEAF]} {continue}
            lassign $filter key op value
            if {[dict get $::mock::db $p $key] eq $value} {lappend out $p}
        }
    }
    return [lsort -unique $out]
}
proc get_nets {args} {
    set out {}; foreach p [mock::arg $args -of_objects] {if {[dict exists $::mock::pn $p]} {lappend out [dict get $::mock::pn $p]}}
    return [lsort -unique $out]
}
proc disconnect_net {args} {
    incr ::mock::calls
    set n [mock::arg $args -net]
    foreach p [mock::arg $args -pinlist] {
        if {[dict get $::mock::pn $p] ne $n} {error "disconnect wrong net"}
        dict unset ::mock::pn $p
        dict set ::mock::np $n [r38_reset_eco::subtract [dict get $::mock::np $n] [list $p]]
    }
}
proc connect_net {args} {
    incr ::mock::calls
    set n [mock::arg $args -net]
    foreach p [mock::arg $args -objects] {
        if {[dict exists $::mock::pn $p]} {error "connect still connected"}
        mock::attach $p $n
    }
    if {$::mock::calls==4 && $::mock::corrupt ne {}} {uplevel #0 $::mock::corrupt}
}
proc test {name perturb expected {post 0}} {
    mock::init
    if {$post} {set ::mock::corrupt $perturb} else {uplevel #0 $perturb}
    set dir [file join /tmp r38-reset-eco-test-[pid]-$name]
    set failed [catch {r38_reset_eco::apply $dir} error options]
    if {$expected eq "PASS"} {
        if {$failed} {return -options $options $error}
        if {$::mock::calls!=4} {error "wrong mutation call count"}
        if {![catch {r38_reset_eco::apply ${dir}-retry} again] || ![string match *one-shot* $again]} {error "retry was permitted"}
    } else {
        if {!$failed || ![string match *$expected* $error]} {error "case $name wrong result: $error"}
        if {!$post && $::mock::calls!=0} {error "case $name mutated before rejection"}
        if {$post} {
            source $::helper
            if {!$::r38_reset_eco::used || ![catch {r38_reset_eco::apply ${dir}-retry} again] || ![string match *one-shot* $again]} {error "partial mutation re-source retry guard lost"}
        }
    }
    file delete -force $dir
    puts "PASS $name"
}
set root u_soc/cpuFunctionalReset_cpuResetDistribution
set ff $root/distributed_reg
set source {u_soc/cpuRelease/release_0_reg[2]}
test normal {} PASS
test missing {set ::mock::cells [lrange $::mock::cells 1 end]} {three-stage}
test extra {mock::ff $::ff-extra 0 100} {41-copy}
test bad_ref {dict set ::mock::db $::ff REF_NAME FDRE} {FF/INIT}
test bad_init {dict set ::mock::db $::ff INIT 1'b0} {FF/INIT}
test protected {dict set ::mock::db $::ff DONT_TOUCH 1} {protected distribution}
test async_driver {dict set ::mock::db $::ff ASYNC_REG 1} {protected distribution}
test unplaced {dict set ::mock::db $::ff LOC {}} {unplaced}
test invert {dict set ::mock::db $::ff/PRE IS_INVERTED 1} {polarity}
test notleaf {dict set ::mock::db $::ff/D IS_LEAF 0} {missing}
test early {dict set ::mock::pn $::ff/D s1} {D/PRE}
test wrongpre {dict set ::mock::pn $::ff/PRE local} {D/PRE}
test wrongclock {dict set ::mock::pn $::ff/C raw} {CPU clock}
test badtarget {dict set ::mock::db cpu_target300 PERIOD 20} {target}
test power {dict set ::mock::db power2 TYPE SIGNAL} {nonconstant}
test ground {dict set ::mock::db ground TYPE SIGNAL} {nonconstant}
test falseground {dict set ::mock::db u_soc/cpuRelease/GND REF_NAME LUT1} {constant primitive}
test shortchain {dict set ::mock::db $::source ASYNC_REG 0} {unprotected release}
test earlyfanout {mock::object leak [dict create DIRECTION IN]; mock::attach leak s0} {early release bypass}
test loads {set q [dict get $::mock::pn $::ff/Q]; dict set ::mock::np $q [lrange [dict get $::mock::np $q] 0 end-1]} {total/aliased}
test postloc {dict set ::mock::db $::ff LOC SLICE_X99Y99} {attributes/clocks} 1
test lost_other {dict set ::mock::np raw [r38_reset_eco::subtract [dict get $::mock::np raw] {other/raw}]} {raw reset load} 1
test extra_ground {mock::object leak [dict create DIRECTION IN]; mock::attach leak ground} {ground load} 1
test lost_output {set q [dict get $::mock::pn $::ff/Q]; dict set ::mock::np $q [lrange [dict get $::mock::np $q] 0 end-1]} {total/aliased} 1
puts {R38_RESET_ECO_TEST_PASS positive=1 negatives=23 MOCK_ONLY_NO_NATIVE_TIMING}
