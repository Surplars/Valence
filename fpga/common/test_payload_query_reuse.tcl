# Query-reuse contract against a frozen oracle. Pure Tcl graph fixtures, not
# synthesized-netlist, Vivado, timing, or hardware qualification.
# Usage: tclsh test_payload_query_reuse.tcl ?baseline.tcl? ?candidate.tcl?
set here [file dirname [file normalize [info script]]]
set root [file normalize [file join $here .. ..]]
set baseline [file join $root common_cdc.baseline.tcl]
set candidate [file join $here common_cdc.tcl]
if {[llength $argv] > 0} {set baseline [lindex $argv 0]}
if {[llength $argv] > 1} {set candidate [lindex $argv 1]}
set ::valence(root) $root
source $baseline
set baseline_helpers {}
foreach name [info procs ::common_cdc::*] {
    if {$name ne {::common_cdc::payload}} {
        dict set baseline_helpers $name [list [info args $name] [info body $name]]
    }
}
rename ::common_cdc::payload ::common_cdc::payload_baseline
source $candidate
rename ::common_cdc::payload ::common_cdc::payload_candidate
foreach name [dict keys $baseline_helpers] {
    if {[dict get $baseline_helpers $name] ne [list [info args $name] [info body $name]]} {
        error "Non-payload production helper changed: $name"
    }
}

proc assert {condition description} {
    if {![uplevel 1 [list expr $condition]]} {error $description}
}
namespace eval graph {
    variable h test/fifo
    variable props {}; variable cells {}; variable pins {}; variable nets {}
    variable owner {}; variable pin_nets {}; variable net_pins {}; variable clocks {}
    variable fanin {}; variable counts {}; variable endpoints {}; variable segment_pins {}
    variable clock_pins {}; variable owner_pins {}; variable cases 0
}
proc graph::bump {key} {variable counts; dict incr counts $key}
proc graph::property {object key value} {variable props; dict set props $object $key $value}
proc graph::cell {name ref} {
    variable cells; variable props
    if {$name ni $cells} {lappend cells $name}
    dict set props $name [dict create NAME $name CLASS cell REF_NAME $ref]
    return $name
}
proc graph::pin {name cell direction {ref {}}} {
    variable pins; variable owner; variable props; variable h
    if {$name ni $pins} {lappend pins $name}
    if {$ref eq {}} {set ref [file tail $name]}
    dict set owner $name $cell
    dict set props $name [dict create NAME $name CLASS pin REF_PIN_NAME $ref DIRECTION $direction IS_LEAF [expr {$cell ne $h}] IS_INVERTED 0]
    return $name
}
proc graph::net {name type members} {
    variable nets; variable props; variable net_pins; variable pin_nets
    if {$name ni $nets} {lappend nets $name}
    dict set props $name [dict create NAME $name TYPE $type]
    dict set net_pins $name $members
    foreach p $members {dict lappend pin_nets $p $name}
}
proc graph::disconnect {p} {
    variable pin_nets; variable net_pins
    if {[dict exists $pin_nets $p]} {
        foreach n [dict get $pin_nets $p] {
            set kept {}; foreach old [dict get $net_pins $n] {if {$old ne $p} {lappend kept $old}}
            dict set net_pins $n $kept
        }
        dict unset pin_nets $p
    }
}
proc graph::replace_nets {p types {drivers {}}} {
    disconnect $p
    set i 0
    foreach type $types {net replace:$p:[incr i] $type [concat [list $p] $drivers]}
}
proc graph::ff {name clock} {
    variable clocks
    cell $name FDRE
    foreach p {C D CE Q} {pin $name/$p $name [expr {$p eq {Q} ? {OUT} : {IN}}]}
    dict set clocks $name/C [list $clock]
}
proc graph::ram {name ref {port CLK}} {
    variable clocks
    cell $name $ref; pin $name/$port $name IN $port
    dict set clocks $name/$port src
    return $name/$port
}
proc graph::capture {i} {variable h; return [format {%s/output_0_reg[%d]} $h $i]}
proc graph::bit {i} {variable h; return [format {%s/destination_bits[%d]} $h $i]}
proc graph::address {i} {variable h; return [format {%s/storage_ext/_R0_addr_d0_reg[%d]} $h $i]}
proc graph::fixture {{width 8}} {
    variable h; variable props; variable cells; variable pins; variable nets
    variable owner; variable pin_nets; variable net_pins; variable clocks; variable fanin
    foreach v {props cells pins nets owner pin_nets net_pins clocks fanin} {set $v {}}
    foreach {clock period} {src 8.0 dst 20.0 other 5.0} {
        dict set props $clock [dict create NAME $clock PERIOD $period]
    }
    cell $h HeldResponse
    foreach {p clock} {sourceClock src destinationClock dst} {
        pin $h/$p $h IN; dict set clocks $h/$p $clock
    }
    set ordinary {}
    for {set i 0} {$i < 4} {incr i} {
        set c [address $i]; ff $c dst
        set ap [format {%s/storage_ext/R0_addr[%d]} $h $i]
        pin $ap $h IN
        net readaddr:$i SIGNAL [list $c/D $ap]
        lappend ordinary $c/C
        set held [format {%s/heldAddress_reg[%d]} $h $i]
        ff $held dst; lappend ordinary $held/C
    }
    ff $h/pending_reg dst; lappend ordinary $h/pending_reg/C
    set r0 [ram $h/storage_ext/mem0 RAMD32 CLK]
    set r1 [ram $h/storage_ext/mem1 RAMS64E WCLK]
    set enables {}
    for {set i 0} {$i < $width} {incr i} {
        set c [capture $i]; set b [bit $i]
        ff $c dst; pin $b $h OUT
        net output:$i SIGNAL [list $b $c/Q]
        net data:$i SIGNAL [list $c/D]
        lappend enables $c/CE
        # Distinct per-end RAM sets plus shared registered control/address cones.
        if {$i % 3 == 0} {set starts [list $r0 $r1]
        } elseif {$i % 3 == 1} {set starts [list $r0]
        } else {set starts [list $r1]}
        dict set fanin $c/D [concat $starts $ordinary]
    }
    net capture_enable SIGNAL $enables
}
proc graph::reset_counts {} {
    variable counts; variable endpoints; variable segment_pins; variable clock_pins; variable owner_pins
    set counts {}; set endpoints {}; set segment_pins {}; set clock_pins {}; set owner_pins {}
}
proc graph::option {args flag {default {}}} {
    set i [lsearch -exact $args $flag]
    if {$i < 0} {return $default}
    return [lindex $args [expr {$i+1}]]
}
proc graph::query {kind args} {
    variable cells; variable pins; variable owner; variable props; variable net_pins
    bump $kind
    if {[lsearch -exact $args -of_objects] >= 0} {
        set objects [option $args -of_objects]; set result {}
        if {$kind eq {get_cells}} {
            bump get_cells_owner
            variable owner_pins
            foreach p $objects {
                dict incr owner_pins $p
                if {[dict exists $owner $p]} {lappend result {*}[dict get $owner $p]}
            }
        } else {
            foreach obj $objects {
                if {$obj in $cells} {
                    foreach p $pins {if {[dict get $owner $p] eq $obj} {lappend result $p}}
                } elseif {[dict exists $net_pins $obj]} {
                    lappend result {*}[dict get $net_pins $obj]
                } else {error "Mock unsupported get_pins -of_objects $obj"}
            }
            set result [lsort -unique $result]
            if {[lsearch -exact $args -leaf] >= 0} {
                set leaves {}
                foreach p $result {
                    if {[dict get $props $p IS_LEAF] in {1 TRUE true}} {lappend leaves $p}
                }
                set result $leaves
            }
            set filter [option $args -filter]
            if {$filter ne {}} {
                set selected {}
                foreach p $result {
                    switch -- $filter {
                        {DIRECTION == OUT} {set keep [expr {[dict get $props $p DIRECTION] eq {OUT}}]}
                        {DIRECTION == IN} {set keep [expr {[dict get $props $p DIRECTION] eq {IN}}]}
                        {REF_PIN_NAME =~ destination_bits*} {set keep [string match destination_bits* [dict get $props $p REF_PIN_NAME]]}
                        default {error "Mock unsupported filter: $filter"}
                    }
                    if {$keep} {lappend selected $p}
                }
                set result $selected
            }
        }
        return [lsort -unique $result]
    }
    if {[lsearch -exact $args -regexp] < 0} {error "Mock requires exact/regexp $kind $args"}
    set patterns [list [lindex $args end]]; set result {}
    set objects [expr {$kind eq {get_cells} ? $cells : $pins}]
    foreach object $objects {
        foreach pattern $patterns {
            if {[regexp -- $pattern $object]} {lappend result $object; break}
        }
    }
    return [lsort -unique $result]
}
proc get_cells {args} {return [graph::query get_cells {*}$args]}
proc get_pins {args} {return [graph::query get_pins {*}$args]}
proc get_property {key objects} {
    graph::bump get_property; graph::bump property:$key
    set result {}
    foreach object $objects {
        if {![dict exists $::graph::props $object $key]} {error "Mock property unavailable: $key $object"}
        lappend result [dict get $::graph::props $object $key]
    }
    if {[llength $result] == 1} {return [lindex $result 0]}
    return $result
}
proc get_nets {args} {
    graph::bump get_nets
    if {[lsearch -exact $args -segments] < 0} {error {Mock requires segmented net lookup}}
    graph::bump get_nets_segments
    set result {}
    foreach p [graph::option $args -of_objects] {
        dict incr ::graph::segment_pins $p
        if {[dict exists $::graph::pin_nets $p]} {lappend result {*}[dict get $::graph::pin_nets $p]}
    }
    return [lsort -unique $result]
}
proc get_clocks {args} {
    graph::bump get_clocks
    if {[lsearch -exact $args -of_objects] < 0} {
        set c [lindex $args end]
        if {![dict exists $::graph::props $c PERIOD]} {error "Unknown mock clock $c"}
        return $c
    }
    set result {}
    foreach p [graph::option $args -of_objects] {
        dict incr ::graph::clock_pins $p
        if {[dict exists $::graph::clocks $p]} {lappend result {*}[dict get $::graph::clocks $p]}
    }
    return [lsort -unique $result]
}
proc all_fanin {args} {
    graph::bump all_fanin
    foreach flag {-flat -startpoints_only -to} {
        if {[lsearch -exact $args $flag] < 0} {error "Mock missing fanin proof flag: $flag"}
    }
    set end [lindex [graph::option $args -to] 0]
    dict incr ::graph::endpoints $end
    if {![dict exists $::graph::fanin $end]} {error "Mock missing fanin graph $end"}
    return [dict get $::graph::fanin $end]
}
# Fail if the scope-only routine ever performs a timing or netlist mutation.
foreach command {set_max_delay set_bus_skew set_false_path set_clock_groups set_property} {
    proc $command {args} {error {Unexpected timing/netlist mutation}}
}
proc graph::run {implementation} {
    variable h; variable counts; variable endpoints; variable segment_pins; variable clock_pins; variable owner_pins
    reset_counts
    set code [catch {::common_cdc::payload_$implementation $h} result options]
    return [dict create code $code result $result counts $counts endpoints $endpoints segment_pins $segment_pins clock_pins $clock_pins owner_pins $owner_pins]
}
proc graph::count {record counter} {
    if {[dict exists $record counts $counter]} {return [dict get $record counts $counter]}
    return 0
}
proc graph::equivalent {name success {message_pattern *}} {
    variable cases
    set old [run baseline]; set new [run candidate]
    assert {[dict get $old code] == [dict get $new code]} "$name: status mismatch: $old / $new"
    assert {([dict get $old code] == 0) == $success} "$name: unexpected baseline outcome: [dict get $old result]"
    if {$success} {
        # Exact full dictionary equality includes order, labels, budget, starts,
        # ends, by_end, ordinary_by_end, literal/unused bits and local constants.
        assert {[dict get $old result] eq [dict get $new result]} "$name: full scope changed"
        foreach key {label starts ends second budget skew by_end ordinary_by_end constant_bits unused_bits local_constants} {
            assert {[dict exists $new result $key]} "$name: omitted scope field $key"
        }
    } else {
        assert {[string match $message_pattern [dict get $old result]]} "$name: unexpected baseline diagnostic: [dict get $old result]"
        assert {[string match $message_pattern [dict get $new result]]} "$name: unexpected candidate diagnostic: [dict get $new result]"
    }
    assert {[dict get $old endpoints] eq [dict get $new endpoints]} "$name: per-end all_fanin proofs changed"
    incr cases
    puts "PAYLOAD_QUERY_CASE_PASS $name outcome=[expr {$success ? {accept} : {reject}}] all_fanin=[count $new all_fanin]"
    return [list $old $new]
}

# Wide data bank with repeated RAM/control/address launches.
graph::fixture 520
lassign [graph::equivalent wide520 1] wide_old wide_new
assert {[graph::count $wide_new all_fanin] == 520} {Wide fixture lost endpoint proofs}
foreach endpoint [dict keys [dict get $wide_new endpoints]] {
    assert {[dict get $wide_new endpoints $endpoint] == 1} "Wide endpoint visited more than once: $endpoint"
}
for {set i 0} {$i < 520} {incr i} {
    assert {[dict get $wide_new segment_pins [graph::bit $i]] == 1} {Output segments not resolved exactly once}
}
foreach launch [dict keys [dict get $wide_new owner_pins]] {
    assert {[dict get $wide_new owner_pins $launch] == 1} "Shared launch owner not reused: $launch"
}
set wide_scope [dict get $wide_new result]
assert {[llength [dict get $wide_scope starts]] == 2} {Lost distinct RAM starts}
assert {[dict size [dict get $wide_scope by_end]] == 520} {Lost per-end RAM mapping}
assert {[llength [dict get $wide_scope by_end [graph::capture 0]/D]] == 2} {Lost second RAM for endpoint}
assert {[llength [dict get $wide_scope by_end [graph::capture 1]/D]] == 1} {Combined unrelated RAM cones}
assert {[llength [dict get $wide_scope ordinary_by_end [graph::capture 0]/D]] == 9} {Lost ordinary launch mapping}

# Defensive repeated-startpoint handling is tested separately so the wide
# performance fixture uses the usual unique all_fanin startpoint collection.
graph::fixture
foreach end [dict keys $::graph::fanin] {
    set first [lindex [dict get $::graph::fanin $end] 0]
    dict lappend ::graph::fanin $end $first
    dict lappend ::graph::fanin $end $::graph::h/pending_reg/C
}
graph::equivalent repeated_startpoints 1

# Separate unique RAM and capture-feedback launches must never be conflated.
# The nine control/address FFs remain shared, but each output has its own RAM
# and its own destination-clock capture/C feedback timing startpoint.
graph::fixture 16
set shared {}
for {set i 0} {$i < 4} {incr i} {
    lappend shared [graph::address $i]/C [format {%s/heldAddress_reg[%d]/C} $::graph::h $i]
}
lappend shared $::graph::h/pending_reg/C
set expected_unique {}
for {set i 0} {$i < 16} {incr i} {
    set launch [graph::ram $::graph::h/storage_ext/unique_mem_$i RAMD64E WCLK]
    set c [graph::capture $i]
    dict set expected_unique $c/D $launch
    dict set ::graph::fanin $c/D [concat [list $launch] $shared [list $c/C]]
}
lassign [graph::equivalent unique16_with_capture_feedback 1] unique_old unique_new
assert {[dict size [dict get $unique_new owner_pins]] == 41} {Distinct launch owners were conflated}
assert {[llength [dict get $unique_new result starts]] == 16} {Distinct RAM launches were conflated}
foreach end [dict keys $expected_unique] {
    assert {[dict get $unique_new result by_end $end] eq [list [dict get $expected_unique $end]]} "Wrong unique RAM cone: $end"
    set feedback [file dirname $end]/C
    assert {$feedback in [dict get $unique_new result ordinary_by_end $end]} "Own capture/C feedback disappeared: $end"
    assert {[llength [dict get $unique_new result ordinary_by_end $end]] == 10} "Ordinary cones were combined: $end"
}
puts {PAYLOAD_QUERY_FIXTURE unique16 unique_ram_launches=16 unique_capture_feedback_launches=16 shared_ordinary_ff_launches=9}
foreach key {get_nets_segments get_cells_owner get_property get_clocks all_fanin} {
    puts "PAYLOAD_QUERY_COUNTS unique16 $key baseline=[graph::count $unique_old $key] candidate=[graph::count $unique_new $key]"
}

# Constants require every connected segment to agree; no net remains unused.
graph::fixture
foreach {i types} {0 GROUND 1 POWER 2 {} 3 {GROUND GROUND} 4 {POWER POWER}} {
    graph::replace_nets [graph::bit $i] $types
}
lassign [graph::equivalent literal_and_unused 1] ignored literals
assert {[dict get $literals result constant_bits] eq {0 1 3 4}} {Literal classification changed}
assert {[dict get $literals result unused_bits] eq {2}} {Unused classification changed}
foreach types {{GROUND SIGNAL} {POWER SIGNAL} {GROUND POWER} {SIGNAL SIGNAL}} {
    graph::fixture
    graph::replace_nets [graph::bit 0] $types [list [graph::capture 0]/Q]
    lassign [graph::equivalent mixed_segments_[join $types _] 1] ignored mixed
    assert {0 ni [dict get $mixed result constant_bits]} {Mixed segments misclassified constant}
}

# Mixed segments without an actual FF driver must not be mistaken for literals.
foreach types {{GROUND SIGNAL} {POWER SIGNAL} {GROUND POWER}} {
    graph::fixture
    graph::replace_nets [graph::bit 0] $types
    graph::equivalent mixed_segments_no_driver_[join $types _] 0 {*missing owned output FF driver*}
}

# Cover every explicitly accepted mapped primitive spelling.
graph::fixture
graph::property $::graph::h/storage_ext/mem0 REF_NAME RAMS32
graph::property $::graph::h/storage_ext/mem1 REF_NAME RAMD64E
graph::property $::graph::h/pending_reg REF_NAME FDPE
graph::property [graph::address 0] REF_NAME FDCE
graph::property [graph::address 1] REF_NAME FDSE
graph::equivalent all_allowed_launch_primitives 1

# A non-cell port with the same NAME as an already cached pin is still rejected.
# Object handles and NAME are deliberately distinct for this collision fixture.
graph::fixture
set alias mock_port_handle
set cached_name $::graph::h/storage_ext/mem0/CLK
dict set ::graph::props $alias [dict create NAME $cached_name CLASS port]
dict set ::graph::owner $alias {}
dict lappend ::graph::fanin [graph::capture 1]/D $alias
graph::equivalent port_same_name_as_cached_pin 0 {*non-cell launch*}

# Local literals must retain actual capture FF clock, D and matching CE proof.
foreach literal {GROUND POWER} {
    graph::fixture
    set c [graph::capture 7]
    dict set ::graph::fanin $c/D [list $::graph::h/pending_reg/C]
    graph::replace_nets $c/D [list $literal]
    lassign [graph::equivalent local_constant_$literal 1] ignored local
    assert {[dict get $local result local_constants] eq [list [list 7 $c]]} {Local constant mapping changed}
    assert {[llength [dict get $local result ends]] == 7} {Local constant gained exception endpoint}
}
graph::fixture
set c [graph::capture 7]
dict set ::graph::fanin $c/D [list $::graph::h/pending_reg/C]
graph::equivalent no_ram_nonconstant_d 0 {*unproved non-RAM data source*}
graph::replace_nets $c/D GROUND
graph::replace_nets $c/CE SIGNAL
graph::equivalent local_constant_wrong_ce 0 {*nets differ*}

# Independent runs must not retain successful net/ref/clock classification.
# Start with success, mutate a common object, compare the two implementations,
# restore it, and compare again without sourcing/redefining either procedure.
graph::fixture
graph::equivalent cold_valid_before_mutations 1
dict set ::graph::clocks $::graph::h/pending_reg/C src
graph::equivalent warm_wrong_ordinary_clock 0 {*asynchronous FF/data bypass*}
dict set ::graph::clocks $::graph::h/pending_reg/C dst
graph::property $::graph::h/storage_ext/mem0 REF_NAME RAMB18E1
graph::equivalent warm_unsupported_ram_ref 0 {*unsupported mapped RAM/launch*}
graph::property $::graph::h/storage_ext/mem0 REF_NAME RAMD32
graph::replace_nets [graph::bit 0] GROUND
graph::equivalent warm_output_now_constant 1
graph::replace_nets [graph::bit 0] SIGNAL [list [graph::capture 0]/Q]
graph::equivalent warm_restored_valid 1

foreach case {
    missing_driver ambiguous_driver nonowned_output wrong_output_clock inverted_output_clock
    foreign_ram unsupported_ram_ref nonleaf_ram wrong_ram_clock bad_ram_clock_pin
    ordinary_q ordinary_wrong_clock noncell_launch ambiguous_owner
    wrong_read_address wrong_read_address_clock wrong_read_address_ref inverted_read_address_clock
    missing_destination missing_pending missing_held_address missing_read_address
    malformed_bit_name ambiguous_destination_clock ambiguous_source_clock
} {
    graph::fixture
    set h $::graph::h; set c [graph::capture 0]; set p [graph::bit 0]
    set r $h/storage_ext/mem0; set end $c/D
    switch -- $case {
        missing_driver {graph::replace_nets $p SIGNAL; set pattern {*missing owned output FF driver*}}
        ambiguous_driver {
            graph::replace_nets $p SIGNAL [list $c/Q [graph::capture 1]/Q]
            set pattern {*missing owned output FF driver*}
        }
        nonowned_output {
            graph::ff elsewhere/output_0_reg dst
            graph::replace_nets $p SIGNAL {elsewhere/output_0_reg/Q}
            set pattern {*missing owned output FF driver*}
        }
        wrong_output_clock {dict set ::graph::clocks $c/C src; set pattern {*non-FF/wrong clock*}}
        inverted_output_clock {graph::property $c/C IS_INVERTED 1; set pattern {*inverted clock*}}
        foreign_ram {
            set external [graph::ram elsewhere/mem RAMD32]
            dict set ::graph::fanin $end [linsert [dict get $::graph::fanin $end] 0 $external]
            set pattern {*unreviewed RAM launch*}
        }
        unsupported_ram_ref {graph::property $r REF_NAME RAM32M16; set pattern {*unsupported mapped RAM/launch*}}
        nonleaf_ram {graph::property $r/CLK IS_LEAF 0; set pattern {*unreviewed RAM launch*}}
        wrong_ram_clock {dict set ::graph::clocks $r/CLK dst; set pattern {*unreviewed RAM launch*}}
        bad_ram_clock_pin {graph::property $r/CLK REF_PIN_NAME O; set pattern {*unreviewed RAM launch*}}
        ordinary_q {dict set ::graph::fanin $end [list $h/pending_reg/Q]; set pattern {*asynchronous FF/data bypass*}}
        ordinary_wrong_clock {dict set ::graph::clocks $h/pending_reg/C src; set pattern {*asynchronous FF/data bypass*}}
        noncell_launch {dict set ::graph::owner $r/CLK {}; set pattern {*non-cell launch*}}
        ambiguous_owner {dict set ::graph::owner $r/CLK [list $r $h/storage_ext/mem1]; set pattern {*non-cell launch*}}
        wrong_read_address {graph::replace_nets [graph::address 0]/D SIGNAL; set pattern {*nets differ*}}
        wrong_read_address_clock {dict set ::graph::clocks [graph::address 0]/C src; set pattern {*non-FF/wrong clock*}}
        wrong_read_address_ref {graph::property [graph::address 0] REF_NAME LUT1; set pattern {*non-FF/wrong clock*}}
        inverted_read_address_clock {graph::property [graph::address 0]/C IS_INVERTED 1; set pattern {*inverted clock*}}
        missing_destination {
            foreach bit $::graph::pins {
                if {[string match destination_bits* [dict get $::graph::props $bit REF_PIN_NAME]]} {
                    graph::property $bit REF_PIN_NAME unrelated
                }
            }
            set pattern {*missing destination port*}
        }
        missing_pending {
            set ::graph::cells [lsearch -all -inline -not -exact $::graph::cells $h/pending_reg]
            set pattern {*missing exact object*}
        }
        missing_held_address {
            set held [format {%s/heldAddress_reg[0]} $h]
            set ::graph::cells [lsearch -all -inline -not -exact $::graph::cells $held]
            set pattern {*bank shape changed*}
        }
        missing_read_address {
            set ::graph::cells [lsearch -all -inline -not -exact $::graph::cells [graph::address 0]]
            set pattern {*bank shape changed*}
        }
        malformed_bit_name {graph::property $p REF_PIN_NAME destination_bits_oops; set pattern {*unsupported bit name*}}
        ambiguous_destination_clock {dict set ::graph::clocks $h/destinationClock {src dst}; set pattern {*missing/ambiguous clock*}}
        ambiguous_source_clock {dict set ::graph::clocks $h/sourceClock {src dst}; set pattern {*missing/ambiguous clock*}}
    }
    graph::equivalent $case 0 $pattern
}

# Active FIFO cannot collapse to local literal captures or literal output ports.
graph::fixture
foreach i {0 1 2 3 4 5 6 7} {graph::replace_nets [graph::bit $i] GROUND}
graph::equivalent no_dynamic_literal_outputs 0 {*no proved nonconstant storage*}
graph::fixture
foreach i {0 1 2 3 4 5 6 7} {
    set c [graph::capture $i]
    dict set ::graph::fanin $c/D [list $::graph::h/pending_reg/C]
    graph::replace_nets $c/D POWER
}
graph::equivalent no_dynamic_local_constants 0 {*no proved nonconstant storage*}

# Scalar destination port remains supported by the unchanged mapped ABI.
graph::fixture 1
graph::property [graph::bit 0] REF_PIN_NAME destination_bits
graph::equivalent scalar_destination 1

# Print counts independently of wall-clock noise. These reductions describe
# this graph fixture, not a native netlist or an elapsed-time speedup estimate.
puts {PAYLOAD_QUERY_FIXTURE wide520 shared_ram_launches=2 shared_ordinary_ff_launches=9}
foreach key {get_nets_segments get_cells_owner get_property get_clocks all_fanin} {
    set before [graph::count $wide_old $key]; set after [graph::count $wide_new $key]
    puts "PAYLOAD_QUERY_COUNTS wide520 $key baseline=$before candidate=$after"
    if {$key eq {all_fanin}} {
        assert {$after == $before} {Endpoint fanin proof count changed}
    } else {
        assert {$after < $before} "Wide repeated queries were not reduced: $key ($before -> $after)"
    }
}
puts "PAYLOAD_QUERY_EQUIVALENCE_PASS cases=$::graph::cases NOT_NATIVE_QUALIFIED"
