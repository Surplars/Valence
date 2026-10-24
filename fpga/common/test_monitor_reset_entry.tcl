# Mock API/structural guards only; never native timing qualification.
set here [file dirname [info script]]
source [file join $here dynamic dynamic_clock_constraints.tcl]
set helper [file join $here dynamic monitor_reset_entry.tcl]
source $helper
proc assert {condition reason} {if {![uplevel 1 [list expr $condition]]} {error $reason}}
proc ff {name ref clock} {
    dict set ::props $name [dict create CLASS cell NAME $name REF_NAME $ref INIT [expr {$ref eq "FDPE" ? "1'b1" : "1'b0"}] ASYNC_REG [expr {$ref eq "FDPE" ? 1 : 0}]]
    lappend ::allcells $name
    set reset [expr {$ref eq "FDPE" ? "PRE" : "CLR"}]
    foreach p [list C D CE $reset Q] {
        set pin $name/$p
        dict set ::props $pin [dict create CLASS pin NAME $pin DIRECTION [expr {$p eq "Q" ? "OUT" : "IN"}] REF_PIN_NAME $p IS_INVERTED 0]
        dict lappend ::cellpins $name $pin
        if {$p eq "C"} {dict set ::pinclocks $pin $clock}
    }
}
proc net {name type driver loads} {
    dict set ::props $name [dict create CLASS net NAME $name TYPE $type]
    dict set ::netout $name [list $driver];dict set ::netin $name $loads
    foreach pin [concat [list $driver] $loads] {dict set ::pinnets $pin $name}
    if {![dict exists $::props $driver]} {dict set ::props $driver [dict create CLASS pin NAME $driver DIRECTION OUT REF_PIN_NAME [file tail $driver] IS_INVERTED 0]}
}
proc reset_fixture {} {
    foreach variable {props cellpins pinclocks pinnets netout netin} {set ::$variable {}}
    set ::allcells {};set ::applied {};set ::queries 0;set ::mutation none;set ::monitor_reset_entry::attempted 0
    ff {ui_reset_pipe_reg[2]} FDPE ui250
    set allpres {}
    foreach {root lane target period} {u_soc/monitor/domain0 cpu_clock cpu_target300 3.333333333333 u_soc/monitor/domain1 fabric_clock fabric_target250 4.0} {
        dict set ::props $target [dict create CLASS clock NAME $target PERIOD $period]
        set stages {};set cpins {};set ces {}
        for {set i 0} {$i<3} {incr i} {
            set name [format {%s/sourceRelease/release_0_reg[%d]} $root $i]
            ff $name FDPE $target;lappend stages $name;lappend cpins $name/C;lappend ces $name/CE;lappend allpres $name/PRE
        }
        net $root/ground GROUND $root/GND/G [list [lindex $stages 0]/D]
        net $root/power POWER $root/VCC/P $ces
        for {set i 1} {$i<3} {incr i} {net $root/link$i SIGNAL [lindex $stages [expr {$i-1}]]/Q [list [lindex $stages $i]/D]}
        set loads [monitor_reset_entry::expected_loads $root]
        foreach load $loads {set owner [file dirname $load];ff $owner FDCE $target;lappend cpins $owner/C}
        net $root/final SIGNAL [lindex $stages 2]/Q $loads
        net $root/clock SIGNAL $lane/managed_buffer/O $cpins
    }
    net reset SIGNAL {ui_reset_pipe_reg[2]/Q} $allpres
    dict set ::props ui250 [dict create CLASS clock NAME ui250 PERIOD 4.0]
}
proc get_cells {args} {return $::allcells}
proc get_pins {args} {
    set objects [lindex $args [expr {[lsearch -exact $args -of_objects]+1}]]
    set result {}
    foreach object $objects {
        if {[dict exists $::cellpins $object]} {lappend result {*}[dict get $::cellpins $object]} else {
            set direction [lindex [lindex $args [expr {[lsearch -exact $args -filter]+1}]] 2]
            if {$direction eq "OUT"} {lappend result {*}[dict get $::netout $object]} else {lappend result {*}[dict get $::netin $object]}
        }
    }
    return $result
}
proc get_nets {args} {
    set pin [lindex $args end]
    if {![dict exists $::pinnets $pin]} {return {}}
    return [dict get $::pinnets $pin]
}
proc get_clocks {args} {
    if {[lsearch -exact $args -of_objects]>=0} {
        set pin [lindex $args end]
        if {![dict exists $::pinclocks $pin]} {return {}}
        return [dict get $::pinclocks $pin]
    }
    return [lindex $args end]
}
proc get_property {key objects} {
    set result {}
    foreach object $objects {
        if {[string match T:* $object]} {
            lassign [split [string range $object 2 end] |] from to kind
            set clk [dict get $::pinclocks $from];set period [dict get $::props $clk PERIOD]
            set values [dict create STARTPOINT_PIN $from ENDPOINT_PIN $to STARTPOINT_CLOCK $clk ENDPOINT_CLOCK $clk REQUIREMENT [expr {$kind eq "max" ? $period : 0.0}] SLACK [expr {$kind eq "max" ? -0.1 : 0.2}] EXCEPTION {}]
            if {$::mutation eq "exception"} {dict set values EXCEPTION false_path}
            if {$::mutation eq "nonfinite"} {dict set values SLACK Inf}
            if {$::mutation eq "changed_after" && [llength $::applied]} {dict set values SLACK 0.9}
            lappend result [dict get $values $key]
        } else {lappend result [dict get $::props $object $key]}
    }
    if {$::mutation eq "short_properties" && $key eq "ENDPOINT_PIN"} {set result [lrange $result 1 end]}
    return $result
}
proc get_timing_paths {args} {
    incr ::queries
    set from [lindex $args [expr {[lsearch -exact $args -from]+1}]]
    set ends [lindex $args [expr {[lsearch -exact $args -to]+1}]]
    set kind [lindex $args [expr {[lsearch -exact $args -delay_type]+1}]]
    assert {[lindex $args [expr {[lsearch -exact $args -nworst]+1}]]==1} "nworst changed"
    assert {[lindex $args end]==[llength $ends]} "max_paths changed"
    set result {};foreach end $ends {lappend result T:$from|$end|$kind}
    if {$::mutation eq "missing_path"} {set result [lrange $result 1 end]}
    if {$::mutation eq "duplicate_path" && [llength $result]>1} {lset result 0 [lindex $result 1]}
    return $result
}
proc set_false_path {args} {
    assert {[llength $args]==2 && [lindex $args 0] eq "-to"} "wrong exception form"
    set ::applied [lindex $args 1]
    assert {[llength $::applied]==6} "wrong cut count"
    foreach pin $::applied {assert {[regexp {^u_soc/monitor/domain[01]/sourceRelease/release_0_reg\[[012]\]/PRE$} $pin]} "broad cut"}
    if {$::mutation eq "partial_failure"} {error "simulated native cut failure"}
}
proc rejected {body label} {assert {[catch {uplevel 1 $body} why]} "negative accepted $label";assert {[string match DYNAMIC_LOCK* $why] || [string match MONITOR_RESET* $why] || $why eq "simulated native cut failure"} "mock failed before ordinary guard: $why";puts "NEGATIVE_PASS $label $why"}
reset_fixture
set plan [monitor_reset_entry::inspect]
assert {[llength $plan]==2 && [llength $::applied]==0} "inspect mutated"
monitor_reset_entry::apply $plan
assert {$::queries==24} "expected24 bounded grouped timing queries"
puts "POSITIVE_PASS six_PRE_only all1042_D_CLR_endpoints max_min before_after"
set negatives 0
foreach case {missing_path duplicate_path short_properties nonfinite exception changed_after partial_failure} {
    reset_fixture;set plan [monitor_reset_entry::inspect];set ::mutation $case
    rejected {monitor_reset_entry::apply $plan} $case;incr negatives
}
# Re-source must not clear the one-shot guard following a partial mutation.
source $helper
rejected {monitor_reset_entry::apply $plan} resource_after_partial;incr negatives
foreach case {bad_ref bad_init bad_async bad_inversion bad_ce bad_ground early_fanout missing_load foreign_clock wrong_buffer wrong_pre extra_stage a1_unreviewed} {
    reset_fixture
    set first {u_soc/monitor/domain0/sourceRelease/release_0_reg[0]}
    switch $case {
        a1_unreviewed {ff {u_soc/monitor/cpuRetireLane1/sourceRelease/release_0_reg[0]} FDPE cpu_target300}
        bad_ref {dict set ::props $first REF_NAME FDCE}
        bad_init {dict set ::props $first INIT 0}
        bad_async {dict set ::props $first ASYNC_REG 0}
        bad_inversion {dict set ::props $first/PRE IS_INVERTED 1}
        bad_ce {dict set ::props u_soc/monitor/domain0/power TYPE SIGNAL}
        bad_ground {dict set ::props u_soc/monitor/domain0/ground TYPE SIGNAL}
        early_fanout {ff u_soc/monitor/domain0/unexpected FDCE cpu_target300;dict lappend ::netin u_soc/monitor/domain0/link1 u_soc/monitor/domain0/unexpected/D}
        missing_load {dict set ::netin u_soc/monitor/domain0/final [lrange [dict get $::netin u_soc/monitor/domain0/final] 1 end]}
        foreign_clock {dict set ::pinclocks {u_soc/monitor/domain0/gray_0_reg[0]/C} fabric_target250}
        wrong_buffer {dict set ::netout u_soc/monitor/domain0/clock [list fabric_clock/managed_buffer/O]}
        wrong_pre {dict set ::netout reset [list $first/Q]}
        extra_stage {ff {u_soc/monitor/domain0/sourceRelease/release_0_reg[3]} FDPE cpu_target300}
    }
    rejected {monitor_reset_entry::inspect} $case;incr negatives
    assert {[llength $::applied]==0} "inspect negative cut constraints"
}
reset_fixture;set plan [monitor_reset_entry::inspect];set first [lindex $plan 0];dict set first period 20;lset plan 0 $first
rejected {monitor_reset_entry::apply $plan} wrong_reviewed_plan;incr negatives
puts "MONITOR_RESET_ENTRY_MOCK_PASS positives=1 negatives=$negatives native=0"
