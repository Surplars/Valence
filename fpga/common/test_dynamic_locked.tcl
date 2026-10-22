# Pure Tcl mapped-object controls. These do not qualify a native checkpoint.
source [file join [file dirname [info script]] dynamic dynamic_clock_constraints.tcl]
proc assert {condition why} {if {![uplevel 1 [list expr $condition]]} {error $why}}
namespace eval mock {variable props {}; variable cells {}; variable pins {}; variable cuts {}; variable bounds {}; variable queries {}}
proc mock::put {object property value} {dict set ::mock::props $object $property $value}
proc mock::net {name {type SIGNAL} {clock {}}} {
    put $name NAME $name; put $name TYPE $type
    if {$clock ne {}} {put $name CLOCK $clock; put $clock NAME $clock}
}
proc mock::pin {cell tail direction net} {
    set name $cell/$tail
    put $name NAME $name; put $name REF_PIN_NAME $tail; put $name DIRECTION $direction; put $name IS_INVERTED 0
    dict set ::mock::pins $name $net
}
proc mock::connect {pin net} {dict set ::mock::pins $pin $net}
proc mock::cell {name ref} {
    dict set ::mock::cells $name 1; put $name NAME $name; put $name REF_NAME $ref
}
proc mock::ff {name {ref FDCE}} {
    cell $name $ref; put $name ASYNC_REG TRUE
    put $name INIT [expr {$ref eq "FDPE" ? {1'b1} : {1'b0}}]
    net $name/q
    foreach {tail direction net} [list C IN aon_net CE IN VCC D IN GND Q OUT $name/q] {pin $name $tail $direction $net}
    pin $name [expr {$ref eq "FDPE" ? "PRE" : "CLR"}] IN GND
}
proc mock::option {args name} {
    set i [lsearch -exact $args $name]
    if {$i < 0} {error "MOCK missing $name in $args"}
    return [lindex $args [expr {$i + 1}]]
}
proc get_property {key objects} {
    set values {}
    foreach object $objects {
        if {![dict exists $::mock::props $object $key]} {error "MOCK missing $key on $object"}
        lappend values [dict get $::mock::props $object $key]
    }
    if {[llength $values] == 1} {return [lindex $values 0]}
    return $values
}
proc set_property {key value objects} {
    assert {$key eq "CLOCK_DEDICATED_ROUTE" && $value eq "SAME_CMT_COLUMN" && $objects eq "ui_net"} {Unexpected routing mutation}
    lappend ::mock::routing [list $key $value $objects]
    if {!$::mock::drop_route_write} {mock::put $objects $key $value}
}
proc get_cells args {
    if {[lsearch -exact $args -regexp] < 0} {
        set name [lindex $args end]; return [expr {[dict exists $::mock::cells $name] ? [list $name] : {}}]
    }
    set result {}; set pattern [mock::option $args -regexp]
    foreach cell [dict keys $::mock::cells] {if {[regexp $pattern $cell]} {lappend result $cell}}
    if {[llength $result] == 1} {return [lindex $result 0]}
    return $result
}
proc get_pins args {
    set result {}
    if {[lsearch -exact $args -of_objects] >= 0} {
        set nets [mock::option $args -of_objects]; set condition [mock::option $args -filter]
        assert {$condition in {{DIRECTION == IN} {DIRECTION == OUT}}} "Unexpected filter $condition"
        dict for {pin net} $::mock::pins {
            if {$net in $nets && [get_property DIRECTION $pin] eq [lindex $condition 2]} {lappend result $pin}
        }
    } elseif {[lsearch -exact $args -regexp] >= 0} {
        set pattern [mock::option $args -regexp]
        foreach pin [dict keys $::mock::pins] {if {[regexp $pattern $pin]} {lappend result $pin}}
    } else {
        set pin [lindex $args end]
        if {[dict exists $::mock::pins $pin]} {lappend result $pin}
    }
    set result [lsort -unique $result]
    if {[llength $result] == 1} {return [lindex $result 0]}
    return $result
}
proc get_nets args {
    set pin [lindex [mock::option $args -of_objects] 0]
    set net [dict get $::mock::pins $pin]
    return [expr {$net eq {} ? {} : [list $net]}]
}
proc get_clocks args {
    if {[lsearch -exact $args -of_objects] < 0} {return [list [lindex $args end]]}
    set pin [lindex [mock::option $args -of_objects] 0]; set net [dict get $::mock::pins $pin]
    if {![dict exists $::mock::props $net CLOCK]} {return {}}
    return [get_property CLOCK $net]
}
proc all_fanin args {return [list gate_source/C]}
proc filter {objects condition} {return $objects}
proc set_max_delay args {lappend ::mock::bounds $args}
proc set_false_path args {
    assert {[llength $args] == 2 && [lindex $args 0] eq "-to"} "Non-endpoint-only false path: $args"
    lappend ::mock::cuts [lindex $args 1]
}
proc report_timing args {}
proc get_timing_paths args {
    set from [mock::option $args -from]; set to [mock::option $args -to]
    if {[string match */managed_buffer/CE $to]} {return ce_path}
    set kind [mock::option $args -delay_type]
    lappend ::mock::queries [list $from $to $kind]
    if {$to in $::mock::cuts || $::mock::timing_mutation eq "missing" ||
        ($::mock::timing_mutation eq "cut_after_exception" && [llength $::mock::cuts])} {return {}}
    set path "path:$from:$to:$kind"
    foreach {key value} [list STARTPOINT_PIN $from ENDPOINT_PIN $to STARTPOINT_CLOCK aon ENDPOINT_CLOCK aon \
        REQUIREMENT [expr {$kind eq "max" ? 20.0 : 0.0}] SLACK [expr {$kind eq "max" ? 19.4 : 0.1}] EXCEPTION {}] {mock::put $path $key $value}
    switch $::mock::timing_mutation {
        infinite {mock::put $path SLACK inf}
        nan {mock::put $path SLACK NaN}
        wrong_endpoint {mock::put $path ENDPOINT_PIN wrong/D}
        wrong_startpoint {mock::put $path STARTPOINT_PIN wrong/C}
        wrong_clock {mock::put $path STARTPOINT_CLOCK other}
        maxdelay {mock::put $path EXCEPTION {Max Delay}}
        multicycle {mock::put $path EXCEPTION {Multicycle Path}}
        relaxed {mock::put $path REQUIREMENT 40.0}
        negative {mock::put $path SLACK -0.1}
    }
    return [list $path]
}
proc mock::setup {} {
    set ::mock::props {}; set ::mock::cells {}; set ::mock::pins {}; set ::mock::cuts {}; set ::mock::bounds {}; set ::mock::queries {}
    set ::mock::timing_mutation {}
    set ::mock::routing {}; set ::mock::drop_route_write 0
    net VCC POWER; net GND GROUND; net aon_net SIGNAL aon; net ui_net SIGNAL ui
    put aon PERIOD 20.0; put ui PERIOD 4.0
    set uiBuffer u_ddr/inst/u_ddr4_infrastructure/u_bufg_divClk
    cell $uiBuffer BUFGCE; pin $uiBuffer O OUT ui_net
    put ui_net CLOCK_DEDICATED_ROUTE {}
    pin u_clk_wiz clk_out1 OUT aon_net; pin u_ddr c0_ddr4_ui_clk OUT ui_net
    foreach root {cpu_clock fabric_clock} {
        cell $root/mmcm MMCME4_ADV
        foreach {attribute value} {DIVCLK_DIVIDE 10 CLKFBOUT_MULT_F 40.000 CLKOUT0_DIVIDE_F 20.000} {put $root/mmcm $attribute $value}
        pin $root/mmcm CLKIN1 IN ui_net; net $root/locked; pin $root/mmcm LOCKED OUT $root/locked
        set reset [format {%s/aon_reset_pipe_reg[2]} $root]; ff $reset FDPE
        set previous {}
        for {set n 0} {$n < 3} {incr n} {
            set cell [format {%s/lock_sync_reg[%d]} $root $n]; ff $cell
            connect $cell/CLR $reset/q
            connect $cell/D [expr {$previous eq {} ? "$root/locked" : "$previous/q"}]
            set previous $cell
        }
        cell $root/managed_buffer BUFGCE; put $root/managed_buffer CE_TYPE SYNC
        pin $root/managed_buffer CE IN GND; ff $root/gate/ce_reg
        foreach chain {enable_sync token_sync closed_sync token_ack_sync open_sync resumed_sync} {
            for {set n 0} {$n < 3} {incr n} {ff [format {%s/gate/%s_reg[%d]} $root $chain $n]}
        }
    }
}
set ::first {cpu_clock/lock_sync_reg[0]}; set ::second {cpu_clock/lock_sync_reg[1]}; set ::third {cpu_clock/lock_sync_reg[2]}
proc reject {mutation pattern {cuts 0}} {
    mock::setup; uplevel 1 $mutation
    assert {[catch {native_dynamic_lock::constrain cpu_clock} reason]} "Mutation accepted: $mutation"
    assert {[string match $pattern $reason]} "Wrong rejection for $mutation: $reason"
    assert {[llength $::mock::cuts] == $cuts} "Exception emitted before proof for $mutation"
    assert {![llength $::mock::bounds]} "LOCKED received a max-delay bound"
    incr ::negatives
}
mock::setup
# The production entry writes evidence in pwd. Keep standalone Tcl execution
# hermetic too, not just the Python wrapper's TemporaryDirectory invocation.
set previous_directory [pwd]
set temporary_channel [file tempfile temporary_directory]
close $temporary_channel
file delete -- $temporary_directory
file mkdir $temporary_directory
try {
    cd $temporary_directory
    native_dynamic_clock_constraints
} finally {
    cd $previous_directory
    file delete -force -- $temporary_directory
}
assert {$::mock::cuts eq [list $::first/D {fabric_clock/lock_sync_reg[0]/D}]} {False path is not exactly the two first-stage D pins}
assert {$::mock::routing eq {{CLOCK_DEDICATED_ROUTE SAME_CMT_COLUMN ui_net}}} {UI dedicated routing not applied exactly once}
assert {[llength $::mock::bounds] == 12} {FF-source CDC bounds changed}
foreach bound $::mock::bounds {
    assert {[lrange $bound 0 1] eq {-datapath_only 3.333}} {FF-source bound relaxed}
    assert {[lindex $bound 3] eq "gate_source/C"} {FF-source launch changed}
    assert {![string match *lock_sync* [lindex $bound end]]} {LOCKED received a false numeric bound}
}
assert {[llength $::mock::queries] == 16} {Both interstage max/min paths were not checked before and after each exception}
set ::negatives 0
foreach cell [list $::first $::second $::third] {
    foreach pin {C D CE CLR} {
        reject [list mock::put $cell/$pin IS_INVERTED 1] {*inverted/unknown pin*}
        reject [list mock::put $cell/$pin IS_INVERTED unknown] {*inverted/unknown pin*}
    }
    reject [list mock::put $cell REF_NAME FDRE] {*unreviewed zero-reset synchronizer*}
    reject [list mock::put $cell INIT {1'b1}] {*unreviewed zero-reset synchronizer*}
    reject [list mock::put $cell ASYNC_REG FALSE] {*unreviewed zero-reset synchronizer*}
    reject [list mock::connect $cell/C ui_net] {*wrong synchronizer clock*}
    reject [list mock::connect $cell/CE GND] {*enable is not constant one*}
    reject [list mock::connect $cell/CLR GND] {*wrong/shared reset driver*}
}
reject {mock::ff {cpu_clock/lock_sync_reg[3]}} {*stage census changed*}
reject {dict unset ::mock::cells $::third} {*stage census changed*}
reject {mock::put cpu_clock/mmcm REF_NAME LUT1} {*unreviewed LOCKED primitive*}
reject {mock::put cpu_clock/locked CLOCK aon} {*unexpected launch clock*}
reject {mock::put aon PERIOD 40.0} {*AON clock is not 50 MHz*}
reject {mock::put aon PERIOD inf} {*AON clock is not 50 MHz*}
reject {mock::put aon_net CLOCK {aon other}} {*missing/ambiguous clock*}
reject {mock::connect $::first/D GND} {*not unique direct first-stage driver*}
reject {mock::pin extra Q OUT cpu_clock/locked} {*not unique direct first-stage driver*}
reject {mock::pin extra D IN cpu_clock/locked} {*LOCKED leaf fanout changed*}
foreach cell [list $::first $::second] {
    reject [list mock::pin extra D IN $cell/q] {*early synchronizer fanout changed*}
}
foreach cell [list $::second $::third] {
    reject [list mock::connect $cell/D cpu_clock/locked] {*LOCKED leaf fanout changed*}
    reject [list mock::connect $cell/D GND] {*non-direct interstage*}
    set previous [expr {$cell eq $::second ? $::first : $::second}]
    reject [list mock::pin extra Q OUT $previous/q] {*non-direct interstage*}
}
set reset {cpu_clock/aon_reset_pipe_reg[2]}
reject [list mock::put $reset REF_NAME FDCE] {*unreviewed local reset source*}
reject [list mock::put $reset INIT {1'b0}] {*unreviewed local reset source*}
reject [list mock::connect $reset/C ui_net] {*reset source not AON clocked*}
reject [list mock::put $reset/PRE IS_INVERTED 1] {*inverted/unknown pin*}
reject [list mock::connect $reset/CE GND] {*enable is not constant one*}
foreach mutation {missing infinite nan wrong_endpoint wrong_startpoint wrong_clock maxdelay multicycle relaxed} {
    reject [list set ::mock::timing_mutation $mutation] {*interstage*}
}
reject {set ::mock::timing_mutation cut_after_exception} {*missing/excepted interstage*} 1
mock::setup; set ::mock::timing_mutation negative
native_dynamic_lock::constrain cpu_clock
assert {$::mock::cuts eq [list $::first/D]} {Negative measured slack broadened exception}
puts "DYNAMIC_LOCKED_CONTRACT_PASS negatives=$::negatives MOCK_ONLY_NOT_NATIVE_QUALIFICATION"
set route_negatives 0
set uiBuffer u_ddr/inst/u_ddr4_infrastructure/u_bufg_divClk
foreach {mutation pattern writes} [list \
    [list dict unset ::mock::cells $uiBuffer] {*missing exact MIG*} 0 \
    [list mock::put $uiBuffer REF_NAME LUT1] {*missing exact MIG*} 0 \
    [list mock::put $uiBuffer NAME wrong] {*missing exact MIG*} 0 \
    [list dict unset ::mock::pins $uiBuffer/O] {*missing exact MIG*} 0 \
    [list mock::put $uiBuffer/O NAME wrong/O] {*missing exact MIG*} 0 \
    [list mock::put $uiBuffer/O DIRECTION IN] {*missing exact MIG*} 0 \
    [list mock::connect $uiBuffer/O {}] {*missing unique MIG*} 0 \
    {mock::put ui_net CLOCK_DEDICATED_ROUTE FALSE} {*unexpected UI routing policy*} 0 \
    {mock::put ui_net CLOCK_DEDICATED_ROUTE ANY_CMT_COLUMN} {*unexpected UI routing policy*} 0 \
    {set ::mock::drop_route_write 1} {*property not retained*} 1] {
    mock::setup; eval $mutation
    set rejected [catch {native_dynamic_ui_route} reason]
    assert {$rejected && [string match $pattern $reason]} "Wrong routing rejection: $reason"
    assert {[llength $::mock::routing]==$writes} {Unexpected routing write count}
    incr route_negatives
}
foreach prior {{} TRUE SAME_CMT_COLUMN} {
    mock::setup; mock::put ui_net CLOCK_DEDICATED_ROUTE $prior
    native_dynamic_ui_route
    assert {$::mock::routing eq {{CLOCK_DEDICATED_ROUTE SAME_CMT_COLUMN ui_net}}} {UI routing changed scope}
}
puts "DYNAMIC_UI_ROUTE_PASS positives=3 negatives=$route_negatives MOCK_ONLY_NOT_NATIVE_QUALIFICATION"
