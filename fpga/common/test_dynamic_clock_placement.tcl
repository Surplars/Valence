# Pure Tcl checks; never a native placement/timing qualification.
source [file join [file dirname [info script]] dynamic clock_placement.tcl]
proc check {condition reason} {if {![uplevel 1 [list expr $condition]]} {error $reason}}
set props {};set pinNets {};set cells {};set writes {}
proc put {object property value} {dict set ::props $object $property $value}
proc pin {name direction net {ref {}}} {
    dict set ::pinNets $name $net;put $name NAME $name;put $name DIRECTION $direction
    put $name IS_INVERTED 0;put $name REF_PIN_NAME [expr {$ref eq {} ? [file tail $name] : $ref}]
}
proc setup {} {
    set ::props {};set ::pinNets {};set ::cells {};set ::writes {};set ::dropWrite 0
    foreach {lane clock period} {cpu_clock cpu_target300 3.333333333333 fabric_clock fabric_target250 4.0} {
        dict set ::cells $lane/mmcm 1;put $lane/mmcm NAME $lane/mmcm;put $lane/mmcm REF_NAME MMCME4_ADV
        pin $lane/mmcm/CLKOUT0 OUT $lane/out
        pin $lane/mmcm/CLKFBOUT OUT $lane/fbout
        pin $lane/mmcm/CLKFBIN IN $lane/feedback
        put $clock NAME $clock;put $clock PERIOD $period
        foreach role {observer managed feedback} {
            set cell $lane/${role}_buffer;dict set ::cells $cell 1
            put $cell NAME $cell;put $cell REF_NAME BUFGCE;put $cell CE_TYPE [expr {$role eq "managed" ? "SYNC" : "ASYNC"}]
            pin $cell/I IN [expr {$role eq "feedback" ? "$lane/fbout" : "$lane/out"}]
            pin $cell/O OUT $lane/$role
            put $lane/$role NAME $lane/$role
            foreach key {CLOCK_DELAY_GROUP USER_CLOCK_ROOT CLOCK_LOW_FANOUT CLOCK_DEDICATED_ROUTE} {put $lane/$role $key {}}
            put $cell/O CLOCK $clock
        }
        pin $lane/gate/ce_reg/Q OUT $lane/ce
        pin $lane/gate/ce_reg/C IN $lane/observer
        pin $lane/managed_buffer/CE IN $lane/ce
        pin $lane/gate/other_reg/C IN $lane/observer
    }
}
proc get_property {key objects} {
    set values {}
    foreach object $objects {lappend values [dict get $::props $object $key]}
    if {[llength $objects]==1} {return [lindex $values 0]}
    return $values
}
proc get_cells args {
    set name [lindex $args end]; if {[dict exists $::cells $name]} {return [list $name]};return {}
}
proc get_pins args {
    set at [lsearch -exact $args -of_objects]
    if {$at<0} {set name [lindex $args end];if {[dict exists $::pinNets $name]} {return [list $name]};return {}}
    set nets [lindex $args [expr {$at+1}]];set direction [lindex [lindex $args end] 2];set result {}
    dict for {name net} $::pinNets {
        if {$net in $nets && [get_property DIRECTION $name] eq $direction} {lappend result $name}
    }
    return $result
}
proc get_nets args {set name [lindex $args end];return [dict get $::pinNets $name]}
proc get_clocks args {return [dict get $::props [lindex $args end] CLOCK]}
proc set_property {key value object} {
    check {$key in {CLOCK_DELAY_GROUP CLOCK_LOW_FANOUT}} {Unexpected physical mutation}
    lappend ::writes [list $key $value $object]
    if {!$::dropWrite} {put $object $key $value}
}
setup;native_dynamic_placement::apply
check {[llength $writes]==6} {Expected six physical properties only}
set expected $writes
foreach lane {cpu_clock fabric_clock} {
    check {[get_property USER_CLOCK_ROOT $lane/managed] eq {} && [get_property USER_CLOCK_ROOT $lane/feedback] eq {}} {Forced high-fanout root}
    check {[get_property CLOCK_DELAY_GROUP $lane/observer] eq {}} {Observer joined high-fanout group}
}
set writes {};native_dynamic_placement::apply
check {$writes eq $expected} {Reapplication changed scope}
set negatives 0
foreach mutation {
    {dict unset ::cells cpu_clock/mmcm}
    {put fabric_clock/mmcm REF_NAME PLLE4_ADV}
    {put fabric_clock/observer_buffer REF_NAME LUT1}
    {put cpu_clock/managed_buffer/I IS_INVERTED 1}
    {dict set ::pinNets fabric_clock/observer_buffer/I cpu_clock/out}
    {dict set ::pinNets cpu_clock/mmcm/CLKFBIN fabric_clock/feedback}
    {dict set ::pinNets cpu_clock/managed_buffer/CE fabric_clock/ce}
    {dict set ::pinNets cpu_clock/gate/ce_reg/C fabric_clock/observer}
    {put cpu_clock/gate/ce_reg/C IS_INVERTED 1}
    {put cpu_clock/managed_buffer CE_TYPE ASYNC}
    {put cpu_target300 PERIOD 20.0}
    {put fabric_clock/managed_buffer/O CLOCK {fabric_target250 cpu_target300}}
    {put cpu_clock/managed USER_CLOCK_ROOT X3Y0}
    {put cpu_clock/observer USER_CLOCK_ROOT X3Y0}
    {put fabric_clock/feedback CLOCK_DELAY_GROUP wrong}
    {put cpu_clock/observer CLOCK_DELAY_GROUP wrong}
    {put fabric_clock/managed CLOCK_LOW_FANOUT TRUE}
    {put cpu_clock/observer CLOCK_DEDICATED_ROUTE FALSE}
    {pin cpu_clock/not_control/C IN cpu_clock/observer}
    {pin cpu_clock/gate/data_reg/D IN cpu_clock/observer}
    {for {set i 0} {$i<1999} {incr i} {pin cpu_clock/gate/extra$i/C IN cpu_clock/observer}}
} {
    setup;uplevel #0 $mutation
    check {[catch {native_dynamic_placement::apply} reason]} "Accepted $mutation"
    check {$writes eq {}} "Wrote property before complete preflight: $mutation"
    incr negatives
}
setup;set dropWrite 1
check {[catch {native_dynamic_placement::apply} reason] && [string match {*readback*} $reason]} {Lost property write not detected}
incr negatives
puts "DYNAMIC_PREPLACE_CONTRACT_PASS positives=2 negatives=$negatives SIX_PHYSICAL_PROPERTIES_ONLY NATIVE_PENDING"
