# Pure Tcl mapped-object mocks and mutation controls. NOT native Vivado or
# synthesized/routed-netlist qualification; no native endpoint list is assumed.
set ::mutation_calls 0
foreach command {set_property set_false_path set_clock_groups set_max_delay set_min_delay set_bus_skew reset_path create_clock} {
    proc $command args {incr ::mutation_calls; error "UNEXPECTED_MUTATION"}
}
source [file join [file dirname [info script]] common_cdc.tcl]
source [file join [file dirname [info script]] reset_locality_audit.tcl]
proc assert {condition why} {if {![uplevel 1 [list expr $condition]]} {error $why}}
namespace eval mock {variable props {}; variable pins {}; variable cells {}; variable nets {}; variable checks 0}
proc mock::put {object property value} {dict set ::mock::props $object $property $value}
proc mock::net {name {type SIGNAL} {clock {}}} {
    dict set ::mock::nets $name {}
    put $name NAME $name; put $name TYPE $type
    if {$clock ne {}} {put $name CLOCK $clock; put $clock NAME $clock}
}
proc mock::connect {pin net} {dict set ::mock::pins $pin $net}
proc mock::pin {cell tail direction net} {
    set name $cell/$tail
    put $name NAME $name; put $name CELL $cell; put $name REF_PIN_NAME $tail
    put $name DIRECTION $direction; put $name IS_INVERTED 0
    connect $name $net
}
proc mock::ff {name ref clock async} {
    dict set ::mock::cells $name {}
    put $name NAME $name; put $name REF_NAME $ref; put $name ASYNC_REG $async
    put $name INIT [expr {$ref eq {FDPE} ? {1'b1} : {1'b0}}]
    net $name/q
    pin $name C IN $clock; pin $name CE IN VCC; pin $name D IN GND; pin $name Q OUT $name/q
    pin $name [expr {$ref eq {FDPE} ? {PRE} : {CLR}}] IN GND
}
proc mock::lut {name init input output} {
    dict set ::mock::cells $name {}
    put $name NAME $name; put $name REF_NAME LUT1; put $name INIT $init
    pin $name I0 IN $input; pin $name O OUT $output
}
proc get_property {property objects} {
    set values {}
    foreach object $objects {
        if {![dict exists $::mock::props $object $property]} {error "MOCK missing property $property at $object"}
        lappend values [dict get $::mock::props $object $property]
    }
    if {[llength $values] == 1} {return [lindex $values 0]}
    return $values
}
proc mock::option {args name} {
    set index [lsearch -exact $args $name]
    if {$index < 0} {error "MOCK missing option $name: $args"}
    return [lindex $args [expr {$index + 1}]]
}
proc get_cells args {
    if {[lsearch -exact $args -of_objects] >= 0} {
        return [list [get_property CELL [mock::option $args -of_objects]]]
    }
    set result {}
    set pattern [mock::option $args -regexp]
    foreach cell [dict keys $::mock::cells] {
        if {[regexp $pattern $cell]} {lappend result $cell}
    }
    return $result
}
proc get_pins args {
    set result {}
    if {[lsearch -exact $args -of_objects] >= 0} {
        set nets [mock::option $args -of_objects]
        set filter [mock::option $args -filter]
        assert {$filter in {{DIRECTION == IN} {DIRECTION == OUT}}} "MOCK unsupported filter $filter"
        set direction [lindex $filter 2]
        dict for {pin net} $::mock::pins {
            if {$net in $nets && [get_property DIRECTION $pin] eq $direction} {lappend result $pin}
        }
    } else {
        set pattern [mock::option $args -regexp]
        foreach pin [dict keys $::mock::pins] {
            if {[regexp $pattern $pin]} {lappend result $pin}
        }
    }
    return [lsort -unique $result]
}
proc get_nets args {
    set pin [lindex [mock::option $args -of_objects] 0]
    set net [dict get $::mock::pins $pin]
    if {$net eq {}} {return {}}
    return [list $net]
}
proc get_clocks args {
    set pin [lindex [mock::option $args -of_objects] 0]
    set net [dict get $::mock::pins $pin]
    if {![dict exists $::mock::props $net CLOCK]} {return {}}
    return [list [dict get $::mock::props $net CLOCK]]
}
proc mock::setup {} {
    set ::mock::props {}; set ::mock::pins {}; set ::mock::cells {}; set ::mock::nets {}
    net GND GROUND; net VCC POWER
    net clk_source SIGNAL source_clock; net clk_local SIGNAL local_clock
    ff async_source FDPE clk_source FALSE
    ff wrong_source FDPE clk_local FALSE
    set ::stages [list {local/release_reg[0]} {local/release_reg[1]} {local/release_reg[2]}]
    set previous {}
    foreach cell $::stages {
        ff $cell FDPE clk_local TRUE
        connect $cell/PRE async_source/q
        if {$previous ne {}} {connect $cell/D $previous/q}
        set previous $cell
    }
    set ::final [lindex $::stages 2]/Q
    set finalnet [lindex $::stages 2]/q
    foreach {name ref async} {functional FDCE FALSE synchronizer FDCE TRUE preset FDPE FALSE} {
        ff $name $ref clk_local $async
        connect $name/[expr {$ref eq {FDPE} ? {PRE} : {CLR}}] $finalnet
    }
    dict set ::mock::cells vendor {}
    put vendor NAME vendor; put vendor REF_NAME MMCME4_ADV; pin vendor RST IN $finalnet
    set ::releases [dict create $::final [dict create stages $::stages clock local_clock \
        assert_source async_source/Q assert_clock source_clock]]
    set ::locals [dict create functional/CLR $::final synchronizer/CLR $::final preset/PRE $::final]
    set ::endpoints [concat [lmap c $::stages {format {%s/PRE} $c}] {functional/CLR synchronizer/CLR preset/PRE vendor/RST}]
}
proc mock::audit {} {return [reset_locality::audit $::releases $::locals $::endpoints]}
proc mock::row {result endpoint} {
    foreach row [dict get $result rows] {
        if {[dict get $row endpoint] eq $endpoint} {return $row}
    }
    error "MOCK missing result row $endpoint"
}
proc mock::unreviewed {endpoint pattern} {
    set row [row [audit] $endpoint]
    assert {[dict get $row classification] eq {UNREVIEWED}} "mutation accepted at $endpoint: $row"
    assert {[string match $pattern [dict get $row reason]]} "wrong rejection at $endpoint: $row (expected $pattern)"
    incr ::mock::checks
}
proc mock::classified {endpoint kind} {
    set row [row [audit] $endpoint]
    assert {[dict get $row classification] eq $kind} "valid topology rejected at $endpoint: $row"
    incr ::mock::checks
}
proc mock::contract_error {script pattern} {
    assert {[catch {uplevel 1 $script} message]} "malformed caller contract accepted: $script"
    assert {[string match $pattern $message]} "wrong contract rejection: $message (expected $pattern)"
    incr ::mock::checks
}

mock::setup
set baseline [mock::audit]
assert {[dict get $baseline endpoint_count] == 7 && [dict get $baseline unreviewed_count] == 1} {endpoint coverage/count changed}
assert {[dict get $baseline scope] eq {EXACT_CALLER_ENDPOINTS_ONLY} && [dict get $baseline timing] eq {UNCHECKED} && [dict get $baseline waiver] eq {NONE}} {unsupported qualification/waiver claim}
foreach c $::stages {mock::classified $c/PRE ASYNC_ASSERTION_LOCAL_RELEASE}
foreach endpoint {functional/CLR synchronizer/CLR preset/PRE} {mock::classified $endpoint LOCAL_RELEASE_CONTROL}
mock::unreviewed vendor/RST {*unsupported reset endpoint*}

# A synchronizer's ASYNC_REG must never hide a foreign/raw reset or wrong clock.
foreach endpoint {functional/CLR synchronizer/CLR preset/PRE} {
    foreach source {async_source/q wrong_source/q} {
        mock::setup; mock::connect $endpoint $source
        mock::unreviewed $endpoint {*unreviewed reset logic/source*}
    }
    mock::setup; mock::connect [lindex [split $endpoint /] 0]/C clk_source
    mock::unreviewed $endpoint {*wrong clock*}
    mock::setup; dict unset ::locals $endpoint
    mock::unreviewed $endpoint {*missing exact local source contract*}
}

# Exact physical source clocks and the entire ordered release chain are proved.
foreach mutation {wrong_source_clock unknown_source_primitive missing_async_reg wrong_primitive bad_init wrong_clock inverted_clock inverted_data inverted_ce unknown_ce_polarity gated_ce nonzero_first_d wrong_stage_driver early_fanout wrong_assert_source inverted_assert missing_stage self_assert} {
    mock::setup
    lassign $::stages first second third
    switch -- $mutation {
        wrong_source_clock {mock::connect async_source/C clk_local; set pattern {*wrong clock*}}
        unknown_source_primitive {mock::put async_source REF_NAME LUT1; set pattern {*unsupported reset source*}}
        missing_async_reg {mock::put $second ASYNC_REG FALSE; set pattern {*missing ASYNC_REG*}}
        wrong_primitive {mock::put $second REF_NAME FDCE; set pattern {*release must be FDPE*}}
        bad_init {mock::put $second INIT {1'b0}; set pattern {*release INIT must be one*}}
        wrong_clock {mock::connect $second/C clk_source; set pattern {*wrong clock*}}
        inverted_clock {mock::put $second/C IS_INVERTED 1; set pattern {*inverted clock*}}
        inverted_data {mock::put $second/D IS_INVERTED 1; set pattern {*inverted release data*}}
        inverted_ce {mock::put $second/CE IS_INVERTED 1; set pattern {*inverted release enable*}}
        unknown_ce_polarity {mock::put $second/CE IS_INVERTED unknown; set pattern {*unknown boolean*}}
        gated_ce {mock::connect $second/CE async_source/q; set pattern {*not constant 1*}}
        nonzero_first_d {mock::connect $first/D VCC; set pattern {*not constant 0*}}
        wrong_stage_driver {mock::connect $second/D wrong_source/q; set pattern {*non-direct release interstage*}}
        early_fanout {mock::connect functional/CLR $first/q; set pattern {*early release stage*}}
        wrong_assert_source {mock::connect $second/PRE wrong_source/q; set pattern {*unreviewed reset logic/source*}}
        inverted_assert {mock::put $second/PRE IS_INVERTED 1; set pattern {*wrong assertion polarity*}}
        missing_stage {dict unset ::mock::cells $second; set pattern {*missing exact object*}}
        self_assert {dict set ::releases $::final assert_source $::final; dict set ::releases $::final assert_clock local_clock; set pattern {*self-asserting release*}}
    }
    if {$mutation eq {wrong_primitive}} {
        mock::unreviewed $second/PRE {*unsupported reset endpoint*}
    } else {mock::unreviewed $second/PRE $pattern}
    mock::unreviewed synchronizer/CLR $pattern
}

# A recognized buffer/inverter is semantic, not a blanket LUT/name allowance.
foreach {init inverted} {{2'h2} 0 {2'h1} 1} {
    mock::setup; mock::net buffered
    mock::lut reset_buffer $init [lindex $::stages 2]/q buffered
    mock::connect synchronizer/CLR buffered; mock::put synchronizer/CLR IS_INVERTED $inverted
    mock::classified synchronizer/CLR LOCAL_RELEASE_CONTROL
    mock::put synchronizer/CLR IS_INVERTED [expr {!$inverted}]
    mock::unreviewed synchronizer/CLR {*wrong assertion polarity*}
}
foreach mutation {lut2 constant_lut cyclic multi_driver floating unknown_polarity} {
    mock::setup; mock::net buffered
    mock::lut reset_buffer {2'h2} [lindex $::stages 2]/q buffered
    mock::connect synchronizer/CLR buffered
    switch -- $mutation {
        lut2 {mock::put reset_buffer REF_NAME LUT2; set pattern {*unreviewed reset logic/source*}}
        constant_lut {mock::put reset_buffer INIT {2'h3}; set pattern {*unreviewed LUT1 function*}}
        cyclic {mock::connect reset_buffer/I0 buffered; set pattern {*cyclic reset logic*}}
        multi_driver {mock::connect wrong_source/Q buffered; set pattern {*ambiguous reset driver*}}
        floating {mock::connect synchronizer/CLR {}; set pattern {*ambiguous reset driver*}}
        unknown_polarity {mock::put synchronizer/CLR IS_INVERTED unknown; set pattern {*unknown boolean*}}
    }
    mock::unreviewed synchronizer/CLR $pattern
}

foreach length {7 8} {
    mock::setup; set previous [lindex $::stages 2]/q
    for {set i 0} {$i < $length} {incr i} {
        set net buffer_chain_$i
        mock::net $net; mock::lut buffer_$i {2'h2} $previous $net
        set previous $net
    }
    mock::connect synchronizer/CLR $previous
    if {$length == 7} {mock::classified synchronizer/CLR LOCAL_RELEASE_CONTROL
    } else {mock::unreviewed synchronizer/CLR {*reset trace depth exceeded*}}
}

# Names/attributes alone do not promote an unlisted release, wrong pin or vendor.
mock::setup; dict unset ::locals preset/PRE
mock::put preset ASYNC_REG TRUE
mock::unreviewed preset/PRE {*missing exact local source contract*}
mock::setup; lappend ::endpoints synchronizer/D
dict set ::locals synchronizer/D $::final
mock::unreviewed synchronizer/D {*unsupported reset endpoint*}
mock::setup; dict set ::locals vendor/RST $::final
mock::unreviewed vendor/RST {*unsupported reset endpoint*}
mock::setup; mock::put synchronizer/CLR DIRECTION OUT
mock::unreviewed synchronizer/CLR {*nonexact reset endpoint*}
mock::setup; dict set ::locals [lindex $::stages 0]/PRE $::final
mock::unreviewed [lindex $::stages 0]/PRE {*release PRE mislabeled*}

# Missing contracts do not erase an inventory, and an invalid supplied release
# remains visible even if this endpoint subset does not consume it.
mock::setup
set uncovered [reset_locality::audit {} {} $::endpoints]
assert {[dict get $uncovered unreviewed_count] == [llength $::endpoints]} {empty contracts silently approved endpoints}
mock::put [lindex $::stages 1] INIT {1'b0}
set subset [reset_locality::audit $::releases {} {vendor/RST}]
assert {[dict get $subset unreviewed_release_count] == 1} {invalid unused release omitted from result}

mock::setup
mock::contract_error {reset_locality::audit $::releases $::locals {}} {*empty exact endpoint*}
mock::contract_error {reset_locality::audit $::releases $::locals [concat $::endpoints {synchronizer/CLR}]} {*duplicate endpoint*}
mock::contract_error {reset_locality::audit $::releases $::locals {functional/CLR}} {*outside endpoint inventory*}
dict set ::locals synchronizer/CLR nonexistent/Q
mock::contract_error {mock::audit} {*unknown required release*}
mock::setup; dict set ::releases $::final stages [lrange $::stages 0 1]
mock::contract_error {mock::audit} {*three distinct ordered stages*}
mock::setup; dict set ::releases $::final typo ignored
mock::contract_error {mock::audit} {*invalid release fields*}
mock::setup
set wrongspec [dict get $::releases $::final]
dict unset ::releases $::final; dict set ::releases wrong/Q $wrongspec
mock::contract_error {mock::audit} {*final Q differs*}
mock::setup
dict set ::releases duplicate/Q [dict replace [dict get $::releases $::final] stages [list [lindex $::stages 0] spare duplicate]]
mock::contract_error {mock::audit} {*overlapping release stage*}

assert {$::mutation_calls == 0} {read-only reset audit attempted a netlist/constraint mutation}
puts "RESET_LOCALITY_EXACT_SOURCE_CLOCK_RELEASE_POLARITY_ASYNC_REG_AND_UNREVIEWED_NEGATIVES_PASS checks=$::mock::checks"
puts RESET_LOCALITY_MOCK_ONLY_NO_NATIVE_QUALIFICATION_NO_TIMING_WAIVER
