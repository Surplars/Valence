# Reuse the native-query mocks/old LOCKED regression; no mock result is native
# qualification. Every new negative enters the same production reset helper.
source [file join [file dirname [info script]] test_dynamic_locked.tcl]
source [file join [file dirname [info script]] dynamic reset_entry_constraints.tcl]

proc mock::reset_setup {} {
    mock::setup
    set ::mock::reset_mutation {}
    foreach {root target period} {cpu_clock cpu_target300 3.333333333333 fabric_clock fabric_target250 4.0} {
        put $target NAME $target; put $target PERIOD $period
        foreach role {raw managed} {
            set clockNet $root/$role
            net $clockNet SIGNAL $target
            set buffer [expr {$role eq "raw" ? "$root/observer_buffer" : "$root/managed_buffer"}]
            cell $buffer BUFGCE; pin $buffer O OUT $clockNet
            set source [expr {$role eq "raw" ? [format {%s/aon_reset_pipe_reg[2]} $root] : "$root/gate/evidence_clear_reg"}]
            ff $source FDPE
            set previous {}
            for {set i 0} {$i < 3} {incr i} {
                set stage [format {%s/gate/%s_reset_pipe_reg[%d]} $root $role $i]
                ff $stage FDPE
                connect $stage/C $clockNet; connect $stage/PRE $source/q
                if {$previous ne {}} {connect $stage/D $previous/q}
                set previous $stage
            }
            foreach endpoint [native_dynamic_reset::loads $root $role] {
                set name [file dirname $endpoint]
                ff $name FDCE; connect $name/C $clockNet; connect $endpoint $previous/q
                put $name/C IS_INVERTED [native_dynamic_reset::falling $endpoint]
            }
        }
    }
}
rename get_timing_paths old_get_timing_paths
proc get_timing_paths args {
    set from [mock::option $args -from]; set to [mock::option $args -to]
    set kind [mock::option $args -delay_type]
    lappend ::mock::queries [list $from $to $kind]
    if {$to in [concat {*}$::mock::cuts] || $::mock::reset_mutation eq "missing" ||
        ($::mock::reset_mutation eq "cut_later" && [llength $::mock::cuts])} {return {}}
    set target [get_clocks -quiet -of_objects $from]
    set period [get_property PERIOD $target]
    set falls [native_dynamic_reset::falling $to]
    set path "path:$from:$to:$kind"
    foreach {key value} [list STARTPOINT_PIN $from ENDPOINT_PIN $to STARTPOINT_CLOCK $target ENDPOINT_CLOCK $target \
        REQUIREMENT [expr {($kind eq "max" ? $period : 0)-($falls ? $period/2 : 0)}] SLACK 0.1 EXCEPTION {}] {
        mock::put $path $key $value
    }
    switch $::mock::reset_mutation {
        wrong_clock {mock::put $path ENDPOINT_CLOCK aon}
        wrong_endpoint {mock::put $path ENDPOINT_PIN other/CLR}
        excepted {mock::put $path EXCEPTION {False Path}}
        relaxed {mock::put $path REQUIREMENT 40}
        infinite {mock::put $path SLACK inf}
        negative {mock::put $path SLACK -0.1}
    }
    return $path
}
set rfirst {cpu_clock/gate/raw_reset_pipe_reg[0]}
set rsecond {cpu_clock/gate/raw_reset_pipe_reg[1]}
set rthird {cpu_clock/gate/raw_reset_pipe_reg[2]}
set negatives 0
proc reset_reject {mutation pattern {expectedCuts 0}} {
    mock::reset_setup; uplevel 1 $mutation
    assert {[catch {native_dynamic_reset::apply} reason]} "Reset mutation accepted: $mutation"
    assert {[string match $pattern $reason]} "Wrong reset rejection: $reason"
    assert {[llength $::mock::cuts]==$expectedCuts} "Reset cut emitted before complete proof: $mutation"
    assert {!$::native_dynamic_lookup::active} {Reset object cache escaped invocation}
    incr ::negatives
}
reset_reject {dict unset ::mock::cells $rsecond} {*reset stage census changed*}
reset_reject {mock::ff {cpu_clock/gate/raw_reset_pipe_reg[3]} FDPE} {*reset stage census changed*}
reset_reject {mock::put $rfirst REF_NAME FDCE} {*unreviewed reset stage*}
reset_reject {mock::put $rsecond ASYNC_REG 0} {*unreviewed reset stage*}
reset_reject {mock::put $rfirst INIT 0} {*unreviewed reset stage*}
reset_reject {mock::put $rfirst/PRE IS_INVERTED 1} {*inverted/unknown pin*}
reset_reject {mock::connect $rfirst/D VCC} {*stage0 D is not zero*}
reset_reject {mock::connect $rsecond/D GND} {*reset interstage/early fanout changed*}
reset_reject {mock::connect cpu_clock/gate/ce_reg/D $rfirst/q} {*reset interstage/early fanout changed*}
reset_reject {mock::connect $rfirst/PRE GND} {*wrong reset PRE driver*}
reset_reject {mock::connect $rfirst/C fabric_clock/raw} {*wrong release clock/buffer*}
reset_reject {mock::connect $rfirst/C cpu_clock/managed} {*wrong release clock/buffer*}
reset_reject {mock::put cpu_target300 PERIOD 20} {*changed target period*}
reset_reject {mock::connect cpu_clock/gate/ce_reg/CLR GND} {*functional reset fanout changed*}
reset_reject {mock::connect cpu_clock/gate/ce_reg/D $rthird/q} {*functional reset fanout changed*}
reset_reject {mock::connect cpu_clock/gate/ce_reg/C fabric_clock/raw} {*foreign functional reset clock*}
reset_reject {mock::put cpu_clock/gate/ce_reg/C IS_INVERTED 1} {*functional load clock polarity changed*}
reset_reject {mock::connect cpu_clock/gate/evidence_clear_reg/C cpu_clock/raw} {*reset source is not AON*}
foreach {mutation pattern} {
    missing {*missing retained*} wrong_clock {*wrong retained timing endpoints/clocks*}
    wrong_endpoint {*wrong retained timing endpoints/clocks*} excepted {*excepted retained reset path*}
    relaxed {*wrong/nonfinite retained*} infinite {*wrong/nonfinite retained*}
} {reset_reject [list set ::mock::reset_mutation $mutation] $pattern}
reset_reject {set ::mock::reset_mutation cut_later} {*missing retained*} 1

foreach mutation {{} negative} {
    mock::reset_setup; set ::mock::reset_mutation $mutation
    set plan [native_dynamic_reset::apply]
    set expected {}
    foreach root {cpu_clock fabric_clock} {foreach role {raw managed} {
        for {set i 0} {$i<3} {incr i} {lappend expected [format {%s/gate/%s_reset_pipe_reg[%d]/PRE} $root $role $i]}
    }}
    assert {$::mock::cuts eq [list $expected]} {Reset cut is not exactly the twelve PRE pins}
    assert {[llength $::mock::queries]==168} {Per-endpoint before/after max/min proof was reduced}
    assert {![llength $::mock::bounds]} {Reset helper changed a timing budget}
}
puts "DYNAMIC_RESET_ENTRY_PASS positives=2 negatives=$negatives exact_PRE=12 retained_queries=168 MOCK_ONLY_NATIVE_PENDING"
