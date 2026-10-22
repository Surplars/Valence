# Structural Tcl model only. This does not invoke Vivado or qualify a netlist.
# Examples:
#   tclsh test_mailbox_internal_constant.tcl --candidate common_cdc.tcl
#   tclsh test_mailbox_internal_constant.tcl --candidate common_cdc.tcl --baseline ../../common_cdc.baseline.tcl
# No common_cdc checker, lookup, clock, FF, or connectivity helper is mocked.
set candidate [file join [file dirname [info script]] common_cdc.tcl]
set baseline {}; set expectOld 0
for {set i 0} {$i<[llength $argv]} {incr i} {
    set option [lindex $argv $i]
    switch -- $option {
        --candidate {set candidate [lindex $argv [incr i]]}
        --baseline {set baseline [lindex $argv [incr i]]}
        --expect-old-rejection {set expectOld 1}
        default {error "unknown option $option"}
    }
}
if {![file isfile $candidate]} {error "candidate not found: $candidate"}
# The standalone baseline can live outside fpga/common. Reuse the dependency
# accompanying this test, not an invented/mock inactive_zero_state.tcl.
set ::valence(root) [file normalize [file join [file dirname [info script]] ../..]]
source $candidate
proc assert {condition why} {
    if {![uplevel 1 [list expr $condition]]} {error $why}
}
foreach command {set_max_delay set_min_delay set_bus_skew set_false_path set_clock_groups set_property} {
    proc $command args {error UNEXPECTED_CONSTRAINT_MUTATION}
}
set ::caseCount 0
proc pass {name} {incr ::caseCount; puts "PASS $name"}
proc object {name class args} {
    dict set ::properties $name [dict create NAME $name CLASS $class {*}$args]
    return $name
}
proc cell {name ref {primitive 1}} {
    object $name cell REF_NAME $ref IS_PRIMITIVE $primitive
}
proc pin {name direction leaf {owner {}} {inverted 0}} {
    object $name pin DIRECTION $direction IS_LEAF $leaf IS_INVERTED $inverted REF_PIN_NAME [file tail $name]
    if {$owner ne {}} {dict set ::owners $name $owner}
}
proc net {name type pins} {
    object $name net TYPE $type
    dict set ::netPins $name $pins
    foreach p $pins {
        if {![dict exists $::pinNets $p]} {dict set ::pinNets $p {}}
        dict lappend ::pinNets $p $name
    }
}
proc remove_cell {name} {
    if {[dict exists $::properties $name]} {dict unset ::properties $name}
    dict for {p owner} $::owners {
        if {$owner eq $name} {dict unset ::owners $p; dict unset ::properties $p}
    }
}
proc ff_cell {name clock} {
    cell $name FDRE
    foreach p {C D Q CE R} {pin $name/$p [expr {$p eq {Q} ? {OUT} : {IN}}] 1 $name}
    dict set ::pinClocks $name/C [list $clock]
}
proc fixture {{literal GND} {period 3.333}} {
    foreach v {properties owners netPins pinNets lowerNets lowerSegments pinClocks fanin fanout queryErrors queries} {set ::$v {}}
    object fabric clock PERIOD $period
    object aon clock PERIOD 20.0
    cell m CdcMailbox35 0
    pin m/sourceClock IN 0 m; pin m/destinationClock IN 0 m
    dict set ::pinClocks m/sourceClock fabric; dict set ::pinClocks m/destinationClock aon
    cell m/const0 GND; pin m/const0/G OUT 1 m/const0
    cell m/const1 VCC; pin m/const1/P OUT 1 m/const1
    for {set i 0} {$i<35} {incr i} {
        set output [format {m/destination_bits[%d]} $i]
        pin $output OUT 0 m
        if {$i<27} {
            set a [format {m/held_reg[%d]} $i]; set b [format {m/captured_reg[%d]} $i]
            ff_cell $a fabric; ff_cell $b aon
            net held_$i SIGNAL [list $a/Q $b/D]
            net output_$i SIGNAL [list $b/Q $output]
        } else {
            set driver [expr {$literal eq {GND} ? {m/const0/G} : {m/const1/P}}]
            net lower_$i [expr {$literal eq {GND} ? {GROUND} : {POWER}}] [list $driver]
            dict set ::lowerNets $output [list lower_$i]
            dict set ::lowerSegments $output [list lower_$i]
            dict set ::fanin lower_$i [list $driver]
            dict set ::fanout $output {}
        }
    }
}
proc arg_value {args option} {
    set i [lsearch -exact $args $option]
    if {$i<0 || $i==[llength $args]-1} {error "missing $option in $args"}
    return [lindex $args [expr {$i+1}]]
}
proc record_query {command args} {
    lappend ::queries [list $command {*}$args]
}
proc fail_query {command target args} {
    set key [list $command $target]
    if {[dict exists $::queryErrors $key]} {
        # Model the precise hazard: -quiet would hide the injected tool failure.
        if {[lsearch -exact $args -quiet]>=0} {return 1}
        error [dict get $::queryErrors $key]
    }
    return 0
}
proc select_regexp {class args} {
    set raw [arg_value $args -regexp]
    set patterns [list $raw]
    if {[llength $raw]>1} {set patterns $raw}
    set result {}
    dict for {name properties} $::properties {
        # Query object class must not change when a property is deliberately
        # malformed. Use membership recorded by structural fixture relationships.
        if {$class eq {cell}} {
            set isClass [expr {[dict exists $properties REF_NAME]}]
        } else {
            set isClass [expr {[dict exists $properties REF_PIN_NAME]}]
        }
        if {!$isClass} {continue}
        foreach pattern $patterns {if {[regexp $pattern $name]} {lappend result $name; break}}
    }
    return [lsort -unique $result]
}
proc get_cells args {
    record_query get_cells {*}$args
    if {[lsearch -exact $args -of_objects]>=0} {
        set result {}
        foreach p [arg_value $args -of_objects] {
            if {[fail_query get_cells $p {*}$args]} {continue}
            if {[dict exists $::owners $p]} {lappend result {*}[dict get $::owners $p]}
        }
        return [lsort -unique $result]
    }
    return [select_regexp cell {*}$args]
}
proc get_pins args {
    record_query get_pins {*}$args
    if {[lsearch -exact $args -of_objects]>=0} {
        set result {}
        foreach n [arg_value $args -of_objects] {
            if {![dict exists $::netPins $n]} {error "mock unknown net $n"}
            foreach p [dict get $::netPins $n] {
                if {![dict exists $::properties $p]} {continue}
                if {[lsearch -exact $args -leaf]>=0 && [get_property IS_LEAF $p] ni {1 true TRUE}} {continue}
                if {[lsearch -exact $args -filter]>=0} {
                    set filter [arg_value $args -filter]
                    if {$filter ni {{DIRECTION == OUT} {DIRECTION == IN}}} {error "mock unsupported filter $filter"}
                    if {[get_property DIRECTION $p] ne [lindex $filter 2]} {continue}
                }
                lappend result $p
            }
        }
        return [lsort -unique $result]
    }
    return [select_regexp pin {*}$args]
}
proc get_nets args {
    record_query get_nets {*}$args
    set result {}
    foreach p [arg_value $args -of_objects] {
        if {[fail_query get_nets $p {*}$args]} {continue}
        set boundary upper
        if {[lsearch -exact $args -boundary_type]>=0} {set boundary [arg_value $args -boundary_type]}
        if {$boundary eq {lower}} {
            set mapping [expr {[lsearch -exact $args -segments]>=0 ? $::lowerSegments : $::lowerNets}]
            if {[dict exists $mapping $p]} {lappend result {*}[dict get $mapping $p]}
        } elseif {$boundary eq {upper}} {
            if {[dict exists $::pinNets $p]} {lappend result {*}[dict get $::pinNets $p]}
        } else {error "mock unsupported boundary $boundary"}
    }
    return [lsort -unique $result]
}
proc get_clocks args {
    record_query get_clocks {*}$args
    if {[lsearch -exact $args -of_objects]>=0} {
        set result {}
        foreach p [arg_value $args -of_objects] {
            if {[fail_query get_clocks $p {*}$args]} {continue}
            if {[dict exists $::pinClocks $p]} {lappend result {*}[dict get $::pinClocks $p]}
        }
        return [lsort -unique $result]
    }
    set name [lindex $args end]
    if {[dict exists $::properties $name] && [dict get $::properties $name CLASS] eq {clock}} {return $name}
    return {}
}
proc get_property {key objects} {
    record_query get_property $key $objects
    set result {}
    foreach o $objects {
        fail_query get_property [list $key $o]
        if {![dict exists $::properties $o]} {error "mock unknown object $o"}
        if {[dict exists $::properties $o $key]} {lappend result [dict get $::properties $o $key]} else {lappend result {}}
    }
    if {[llength $objects]==1} {return [lindex $result 0]}
    return $result
}
proc require_full_traversal {command args} {
    assert {[lsearch -exact $args -quiet]<0} "$command must not suppress traversal errors"
    assert {[lsearch -exact $args -flat]>=0} "$command must flatten hierarchy"
    assert {[lsearch -exact $args -startpoints_only]<0} "$command must not hide internal LUT/FF pins"
    assert {[arg_value $args -trace_arcs] eq {all}} "$command must traverse all arcs"
}
proc all_fanin args {
    record_query all_fanin {*}$args
    set p [lindex [arg_value $args -to] 0]
    if {[fail_query all_fanin $p {*}$args]} {return {}}
    require_full_traversal all_fanin {*}$args
    # Native observation: all-arcs fanin at the unconsumed hierarchical PIN
    # yields self only. The lower NET yields the actual primitive driver.
    if {[dict exists $::lowerNets $p]} {return [list $p]}
    if {[dict exists $::fanin $p]} {return [dict get $::fanin $p]}
    return {}
}
proc all_fanout args {
    record_query all_fanout {*}$args
    set p [lindex [arg_value $args -from] 0]
    if {[fail_query all_fanout $p {*}$args]} {return {}}
    require_full_traversal all_fanout {*}$args
    assert {[lsearch -exact $args -endpoints_only]>=0} {fanout must inspect endpoints}
    if {[dict exists $::fanout $p]} {return [dict get $::fanout $p]}
    return {}
}
proc checked_scope {{period 3.333} {expectedLiterals {}}} {
    set scope [common_cdc::mailbox_width m 35 fabric aon]
    set starts {}; set ends {}
    for {set i 0} {$i<27} {incr i} {
        lappend starts [format {m/held_reg[%d]/C} $i]
        lappend ends [format {m/captured_reg[%d]/D} $i]
    }
    assert {[dict get $scope starts] eq $starts} {27 exact launch C pins changed}
    assert {[dict get $scope ends] eq $ends} {27 exact capture D pins changed}
    assert {[dict get $scope label] eq {m/held_payload}} {scope label changed}
    assert {[dict get $scope second] eq {}} {unexpected second-stage state}
    assert {[dict get $scope budget]==$period && [dict get $scope skew]==1} {mailbox budget/skew changed}
    if {$expectedLiterals eq {}} {
        for {set i 27} {$i<35} {incr i} {lappend expectedLiterals [list $i 0]}
    }
    assert {[dict get $scope unconsumed_internal_literals] eq $expectedLiterals} {incorrect internal literal census}
    # No fallback to missing payload FFs may be used to prove high outputs.
    foreach q $::queries {
        if {[lindex $q 0] ne {get_cells} || [lsearch -exact $q -regexp]<0} {continue}
        foreach pattern [list [arg_value $q -regexp]] {
            for {set i 27} {$i<35} {incr i} {
                set absent [format {m/held_reg[%d]} $i]
                assert {![regexp $pattern $absent]} {pruned output tested through missing-held-FF fallback}
            }
        }
    }
    return $scope
}
proc helper_reject {name mutation diagnostic} {
    fixture
    uplevel 1 $mutation
    assert {[catch {common_cdc::mailbox_unconsumed_constant {m/destination_bits[27]}} why]} "$name accepted"
    assert {[string match $diagnostic $why]} "$name wrong rejection: $why"
    pass $name
}
proc integration_reject {name mutation diagnostic} {
    fixture
    uplevel 1 $mutation
    assert {[catch {common_cdc::mailbox_width m 35 fabric aon} why]} "$name accepted"
    assert {[string match $diagnostic $why]} "$name wrong rejection: $why"
    pass $name
}
# The unmodified checker must reach the original precise missing held[27] error.
# Child-process mode keeps its proc definitions isolated from the candidate.
if {$expectOld} {
    fixture
    assert {[catch {common_cdc::mailbox_width m 35 fabric aon} why]} {baseline unexpectedly accepts native-shaped fixture}
    assert {[string first {COMMON_CDC missing exact object m/held_reg[27]} $why]>=0} "unexpected baseline error: $why"
    puts "BASELINE_NATIVE_SHAPED_REJECTED_MISSING_HELD27 $why"
    exit 0
}
fixture
assert {[common_cdc::mailbox_unconsumed_constant {m/destination_bits[27]}] eq {0}} {exact GND rejected}
pass exact_gnd_internal_driver
fixture VCC
assert {[common_cdc::mailbox_unconsumed_constant {m/destination_bits[27]}] eq {1}} {exact VCC rejected}
pass exact_vcc_internal_driver
fixture
assert {[all_fanin -flat -trace_arcs all -to {m/destination_bits[27]}] eq {{m/destination_bits[27]}}} {PIN model must return self only}
assert {[all_fanin -flat -trace_arcs all -to lower_27] eq {m/const0/G}} {NET model must return primitive driver}
pass native_pin_vs_lower_net_traversal
fixture
# Opaque collection handles need not stringify exactly like the pin's NAME.
object gnd_handle pin NAME m/const0/G DIRECTION OUT IS_LEAF 1 IS_INVERTED 0 REF_PIN_NAME G
dict set ::owners gnd_handle m/const0
dict set ::fanin lower_27 {gnd_handle}
assert {[common_cdc::mailbox_unconsumed_constant {m/destination_bits[27]}] eq {0}} {literal object handle rejected}
pass literal_object_handle_differs_from_name
foreach period {3.333 4.0} {
    fixture GND $period; checked_scope $period
    pass native_shaped_27_active_8_gnd_budget_$period
}
fixture VCC
set expected {}; for {set i 27} {$i<35} {incr i} {lappend expected [list $i 1]}
checked_scope 3.333 $expected
pass active_and_eight_vcc_literals
fixture
# Distinct independent bits may legitimately have different literal values.
dict set ::properties lower_28 TYPE POWER
dict set ::netPins lower_28 {m/const1/P}
dict set ::fanin lower_28 {m/const1/P}
set expected {}; for {set i 27} {$i<35} {incr i} {lappend expected [list $i [expr {$i==28}]]}
checked_scope 3.333 $expected
pass independent_gnd_vcc_bits
helper_reject multiple_same_literal_drivers {
    cell m/extra_gnd GND; pin m/extra_gnd/G OUT 1 m/extra_gnd
    dict lappend ::netPins lower_27 m/extra_gnd/G
    dict lappend ::fanin lower_27 m/extra_gnd/G
} {*driver/cone mismatch*}
fixture
checked_scope
pass single_literal_lower_net_cone
fixture
foreach p {{m/destination_bits[27]} m/const0/G} {
    dict set ::properties $p IS_INVERTED FALSE
}
dict set ::properties {m/destination_bits[27]} IS_LEAF false
dict set ::properties m/const0/G IS_LEAF TRUE
dict set ::properties m/const0 IS_PRIMITIVE true
checked_scope
pass documented_boolean_spellings
fixture
net external_literal GROUND [list {m/destination_bits[27]} m/const0/G]
set expected {}; for {set i 28} {$i<35} {incr i} {lappend expected [list $i 0]}
checked_scope 3.333 $expected
pass existing_external_literal_branch_preserved
# Missing, ambiguous, and nonliteral lower nets must never be inferred safe.
helper_reject lower_missing {dict set ::lowerNets {m/destination_bits[27]} {}} {*ambiguous internal constant lower net*}
helper_reject lower_multiple {dict set ::lowerNets {m/destination_bits[27]} {lower_27 lower_28}} {*ambiguous internal constant lower net*}
helper_reject lower_segments_missing {dict set ::lowerSegments {m/destination_bits[27]} {}} {*ambiguous internal constant lower net*}
helper_reject lower_extra_segment {dict set ::lowerSegments {m/destination_bits[27]} {lower_27 lower_28}} {*ambiguous internal constant lower net*}
helper_reject lower_different_segment {dict set ::lowerSegments {m/destination_bits[27]} {lower_28}} {*ambiguous internal constant lower net*}
helper_reject lower_wrong_class {dict set ::properties lower_27 CLASS pin} {*ambiguous internal constant lower net*}
helper_reject lower_unnamed {dict unset ::properties lower_27 NAME} {*ambiguous internal constant lower net*}
foreach type {SIGNAL UNKNOWN {}} {
    helper_reject lower_nonliteral_type_$type {dict set ::properties lower_27 TYPE $type} {*nonliteral internal lower net*}
}
helper_reject lower_unknown_type {dict unset ::properties lower_27 TYPE} {*nonliteral internal lower net*}
helper_reject lower_type_driver_polarity_mismatch {dict set ::properties lower_27 TYPE POWER} {*type/driver literal mismatch*}
helper_reject lower_driver_missing {dict set ::netPins lower_27 {}} {*driver/cone mismatch*}
helper_reject lower_extra_direct_driver {dict lappend ::netPins lower_27 m/const1/P} {*driver/cone mismatch*}
helper_reject lower_driver_cone_disagree {dict set ::netPins lower_27 {m/const1/P}} {*driver/cone mismatch*}
helper_reject empty_cone {dict set ::fanin lower_27 {}} {*driver/cone mismatch*}
helper_reject self_only_cone {dict set ::fanin lower_27 {{m/destination_bits[27]}}} {*driver/cone mismatch*}
foreach property {CLASS DIRECTION IS_LEAF IS_INVERTED} {
    set wrong [dict get {CLASS cell DIRECTION IN IS_LEAF 1 IS_INVERTED 1} $property]
    helper_reject output_wrong_$property {dict set ::properties {m/destination_bits[27]} $property $wrong} {*internal-constant output*}
    helper_reject output_unknown_$property {dict unset ::properties {m/destination_bits[27]} $property} {*internal-constant output*}
}
helper_reject output_clock_present {dict set ::pinClocks {m/destination_bits[27]} aon} {*has clock/consumer*}
helper_reject output_fanout_endpoint {dict set ::fanout {m/destination_bits[27]} {elsewhere/D}} {*has clock/consumer*}
foreach property {CLASS DIRECTION IS_LEAF IS_INVERTED} {
    set wrong [dict get {CLASS net DIRECTION IN IS_LEAF 0 IS_INVERTED 1} $property]
    helper_reject driver_wrong_$property {dict set ::properties m/const0/G $property $wrong} {*internal*}
    helper_reject driver_unknown_$property {dict unset ::properties m/const0/G $property} {*internal*}
}
helper_reject cone_nonpin_port {
    object other_port port NAME top_input
    dict lappend ::fanin lower_27 other_port
} {*driver/cone mismatch*}
helper_reject cone_unnamed_driver {dict unset ::properties m/const0/G NAME} {*unnamed internal constant cone*}
helper_reject self_unknown_class {
    object self_handle pin NAME {m/destination_bits[27]}
    dict unset ::properties self_handle CLASS
    dict set ::fanin lower_27 {self_handle m/const0/G}
} {*driver/cone mismatch*}
helper_reject driver_clock_present {dict set ::pinClocks m/const0/G fabric} {*internal*}
helper_reject nonprimitive_constant_owner {dict set ::properties m/const0 IS_PRIMITIVE 0} {*invalid internal constant owner*}
helper_reject unknown_primitive_owner {dict unset ::properties m/const0 IS_PRIMITIVE} {*invalid internal constant owner*}
helper_reject unknown_primitive_token {dict set ::properties m/const0 IS_PRIMITIVE UNKNOWN} {*invalid internal constant owner*}
helper_reject owner_wrong_class {dict set ::properties m/const0 CLASS pin} {*invalid internal constant owner*}
helper_reject owner_unknown_class {dict unset ::properties m/const0 CLASS} {*invalid internal constant owner*}
helper_reject no_owner {dict unset ::owners m/const0/G} {*invalid internal constant owner*}
helper_reject multiple_owners {dict set ::owners m/const0/G {m/const0 m/const1}} {*invalid internal constant owner*}
helper_reject wrong_gnd_pin {dict set ::properties m/const0/G REF_PIN_NAME P} {*unreviewed internal constant driver*}
helper_reject wrong_vcc_pin {dict set ::properties m/const0 REF_NAME VCC} {*unreviewed internal constant driver*}
helper_reject unknown_literal_ref {dict unset ::properties m/const0 REF_NAME} {*unreviewed internal constant driver*}
helper_reject unknown_literal_pin {dict unset ::properties m/const0/G REF_PIN_NAME} {*unreviewed internal constant driver*}
helper_reject mixed_constants_same_bit {dict lappend ::fanin lower_27 m/const1/P} {*driver/cone mismatch*}
helper_reject other_hierarchical_port {
    pin m/another_boundary OUT 0 m
    dict lappend ::fanin lower_27 m/another_boundary
} {*internal*}
foreach ref {LUT1 LUT6 FDRE FDCE} {
    helper_reject hidden_internal_$ref {
        cell m/hidden $ref; pin m/hidden/O OUT 1 m/hidden
        dict lappend ::fanin lower_27 m/hidden/O
    } {*driver/cone mismatch*}
}
# Tool failures must propagate with their original error, not turn into absence.
foreach command {all_fanout get_nets get_clocks} {
    helper_reject propagate_${command}_output_error {
        dict set ::queryErrors [list $command {m/destination_bits[27]}] TOOL_FAILURE_$command
    } TOOL_FAILURE_$command
}
helper_reject propagate_all_fanin_lower_error {
    dict set ::queryErrors {all_fanin lower_27} TOOL_FAILURE_all_fanin
} TOOL_FAILURE_all_fanin
helper_reject propagate_driver_clock_error {dict set ::queryErrors {get_clocks m/const0/G} TOOL_FAILURE_DRIVER_CLOCK} TOOL_FAILURE_DRIVER_CLOCK
helper_reject propagate_owner_lookup_error {dict set ::queryErrors {get_cells m/const0/G} TOOL_FAILURE_OWNER_LOOKUP} TOOL_FAILURE_OWNER_LOOKUP
helper_reject propagate_property_error {dict set ::queryErrors {get_property {IS_PRIMITIVE m/const0}} TOOL_FAILURE_PROPERTY} TOOL_FAILURE_PROPERTY
fixture
net external_not_literal SIGNAL [list {m/destination_bits[27]}]
assert {[common_cdc::mailbox_unconsumed_constant {m/destination_bits[27]}] eq {}} {external net must use active branch}
pass external_nonliteral_returns_active_branch
integration_reject external_net_missing_ff {
    net external_not_literal SIGNAL [list {m/destination_bits[27]}]
} {*missing exact object*held_reg*27*}
integration_reject external_net_ignores_internal_literal_when_missing_capture {
    ff_cell {m/held_reg[27]} fabric
    net external_not_literal SIGNAL [list {m/destination_bits[27]}]
} {*missing exact object*captured_reg*27*}
integration_reject native_shape_bad_internal_cone {
    cell m/hidden LUT1; pin m/hidden/O OUT 1 m/hidden
    dict lappend ::fanin lower_27 m/hidden/O
} {*driver/cone mismatch*}
integration_reject active_missing_held {remove_cell {m/held_reg[2]}} {*missing exact object*held_reg*2*}
integration_reject active_missing_capture {remove_cell {m/captured_reg[2]}} {*missing exact object*captured_reg*2*}
integration_reject active_wrong_source_clock {dict set ::pinClocks {m/held_reg[2]/C} aon} {*non-FF/wrong clock*}
integration_reject active_wrong_capture_clock {dict set ::pinClocks {m/captured_reg[2]/C} fabric} {*non-FF/wrong clock*}
integration_reject wrong_source_boundary_clock {dict set ::pinClocks m/sourceClock aon} {*incorrect clock*}
integration_reject wrong_destination_boundary_clock {dict set ::pinClocks m/destinationClock fabric} {*incorrect clock*}
integration_reject active_inverted_launch_clock {dict set ::properties {m/held_reg[2]/C} IS_INVERTED 1} {*inverted clock*}
integration_reject active_capture_bypass {
    dict set ::netPins held_2 {{m/held_reg[3]/Q} {m/captured_reg[2]/D}}
} {*mailbox payload mapping changed*}
integration_reject active_output_bypass {
    dict set ::netPins output_2 {{m/held_reg[2]/Q} {m/destination_bits[2]}}
} {*mailbox payload mapping changed*}
integration_reject all_bits_internal_literals_no_dynamic_payload {
    for {set i 0} {$i<27} {incr i} {
        set p [format {m/destination_bits[%d]} $i]
        dict unset ::pinNets $p
        net lower_$i GROUND {m/const0/G}
        dict set ::lowerNets $p [list lower_$i]
        dict set ::lowerSegments $p [list lower_$i]
        dict set ::fanin lower_$i {m/const0/G}
    }
} {*mailbox has no proved dynamic payload*}
integration_reject surplus_unaccounted_capture {
    ff_cell {m/captured_reg[40]} aon
    net extra_dynamic SIGNAL [list {m/held_reg[0]/Q} {m/captured_reg[40]/D}]
} {*unaccounted mailbox capture*}
integration_reject surplus_wrong_clock_constant_capture {
    ff_cell {m/captured_reg[40]} fabric
    net extra_constant GROUND [list m/const0/G {m/captured_reg[40]/D}]
} {*non-FF/wrong clock*}
fixture
ff_cell {m/captured_reg[40]} aon
net extra_constant GROUND [list m/const0/G {m/captured_reg[40]/D}]
checked_scope
pass surplus_proved_local_constant_capture
integration_reject pruned_bit_retained_dynamic_capture {
    ff_cell {m/captured_reg[27]} aon
    net extra_dynamic SIGNAL [list {m/held_reg[0]/Q} {m/captured_reg[27]/D}]
} {*unaccounted mailbox capture*}
if {$baseline ne {}} {
    set output [exec [info nameofexecutable] [info script] --candidate $baseline --expect-old-rejection]
    puts $output
    assert {[string match {*BASELINE_NATIVE_SHAPED_REJECTED_MISSING_HELD27*} $output]} {baseline negative control missing}
    pass immutable_old_checker_negative_control
}
puts "MAILBOX_INTERNAL_CONSTANT_PASS cases=$::caseCount MODELED_STRUCTURE_ONLY_NOT_NATIVE_VIVADO_QUALIFIED candidate=[file normalize $candidate]"
