# Inductive constant-state proof for synthesized, unused HeldResponse lanes.
# Unknown external inputs and reset-release outputs remain arbitrary. No timing
# exception is applied here. Unsupported primitives or inconclusive cones fail.
namespace eval common_zero {variable memo {}; variable state {}; variable root {}}
proc common_zero::reject {fifo reason} {puts "COMMON_ZERO_NOT_PROVED fifo=$fifo reason=$reason";return 0}
proc common_zero::lut {init inputs} {
    if {![regexp {^[0-9]+'[hH]([0-9a-fA-F]+)$} $init -> hex]} {error "Unsupported LUT INIT $init"}
    set value [expr 0x$hex];set answer X
    set seen {}
    for {set row 0} {$row<(1<<[llength $inputs])} {incr row} {
        set possible 1;set bit 0
        foreach input $inputs {
            if {$input ne {X} && (($row>>$bit)&1)!=$input} {set possible 0;break}
            incr bit
        }
        if {$possible} {dict set seen [expr {($value>>$row)&1}] 1}
    }
    if {[dict size $seen]==1} {set answer [lindex [dict keys $seen] 0]}
    return $answer
}
proc common_zero::input {pin} {
    set p [common_cdc::one get_pins $pin]
    set nets [get_nets -quiet -segments -of_objects $p]
    if {![llength $nets]} {error "Floating proof input $pin"}
    set types [lsort -unique [get_property TYPE $nets]]
    if {$types eq {GROUND}} {return 0}
    if {$types eq {POWER}} {return 1}
    set drivers [common_cdc::names [get_pins -quiet -leaf -of_objects $nets -filter {DIRECTION == OUT}]]
    if {[llength $drivers]!=1} {error "Nonunique proof input driver $pin: $drivers"}
    return [output [lindex $drivers 0]]
}
proc common_zero::output {pin} {
    variable memo;variable state;variable root
    if {[dict exists $memo $pin]} {return [dict get $memo $pin]}
    # Mark recursion inconclusive, never assume a combinational loop is zero.
    dict set memo $pin X
    set p [common_cdc::one get_pins $pin]
    set c [get_cells -quiet -of_objects $p]
    if {[llength $c]!=1} {error "Missing driver cell $pin"}
    set n [get_property NAME $c];set ref [get_property REF_NAME $c]
    if {[dict exists $state $n]} {set result 0
    } elseif {[string first $root/ $n]!=0 || [regexp {/(sourceRelease|destinationRelease)/release_0_reg\[[0-2]\]$} $n]} {
        set result X
    } elseif {$ref eq {GND}} {set result 0
    } elseif {$ref eq {VCC}} {set result 1
    } elseif {[regexp {^LUT([1-6])$} $ref -> count] && [get_property REF_PIN_NAME $p] eq {O}} {
        set inputs {};for {set i 0} {$i<$count} {incr i} {lappend inputs [input $n/I$i]}
        set result [lut [get_property INIT $c] $inputs]
    } else {error "Unsupported zero-state driver $n $ref"}
    dict set memo $pin $result
    return $result
}
proc common_zero::prove {fifo} {
    variable memo;variable state;variable root
    set memo {};set state {};set root $fifo
    set cell [common_cdc::one get_cells $fifo]
    set src [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME == source_valid}]
    if {[llength $src]>1 || ([llength $src] && [catch {common_cdc::constant [get_property NAME $src] 0}])} {return [reject $fifo source_not_literal_zero]}
    set valid [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME == destination_valid}]
    if {[llength $valid]>1} {return [reject $fifo ambiguous_valid]}
    set bits [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME =~ destination_bits*}]
    # An optimized-away payload port has no consumer. Absence alone proves
    # nothing: the RAM exclusion, full state induction and valid proof below
    # remain mandatory, including for these specialized zero-payload modules.
    foreach p $bits {
        # Disconnected outputs have no observable payload. Connected ones must
        # be literal zero; arbitrary data with valid=0 is not silently accepted.
        set nets [get_nets -quiet -segments -of_objects $p]
        if {[llength $nets] && [catch {common_cdc::constant [get_property NAME $p] 0}]} {return [reject $fifo observable_nonzero_payload]}
    }
    set clocks [list [common_cdc::clock $fifo/sourceClock] [common_cdc::clock $fifo/destinationClock]]
    foreach c [get_cells -quiet -hier -filter "IS_PRIMITIVE == TRUE && NAME =~ $fifo/*"] {
        set n [get_property NAME $c];set ref [get_property REF_NAME $c]
        if {[regexp {/(sourceRelease|destinationRelease)/release_0_reg\[[0-2]\]$} $n]} {
            if {$ref ne {FDPE}} {return [reject $fifo unsupported_release_state]}
            continue
        }
        if {$ref eq {FDCE}} {
            if {[get_property INIT $c] ne {1'b0} || [common_cdc::clock $n/C] ni $clocks} {return [reject $fifo nonzero_init_or_wrong_clock]}
            dict set state $n 0
        } elseif {$ref ni {GND VCC} && ![regexp {^LUT[1-6]$} $ref]} {return [reject $fifo unsupported_primitive_$ref]}
    }
    if {![dict size $state]} {return [reject $fifo no_functional_state]}
    # Base: every functional state bit INIT=0. Step for arbitrary clock order:
    # FDCE holds zero when CE=0, and loads zero whenever CE may be asserted.
    # Its async clear only writes zero. Release states are arbitrary throughout.
    dict for {n unused} $state {
        set ce [input $n/CE]
        if {$ce ne {0} && [input $n/D] ne {0}} {return [reject $fifo noninvariant_state_$n]}
    }
    # A fully optimized-away valid output is unobservable, but is never an
    # inactivity certificate alone: every functional state bit was proved above.
    set valid_unconnected 1
    if {[llength $valid]} {set valid_unconnected [expr {![llength [get_nets -quiet -segments -of_objects $valid]]}]}
    if {!$valid_unconnected && [input [get_property NAME $valid]] ne {0}} {return [reject $fifo valid_not_invariant_zero]}
    puts "COMMON_CDC_INDUCTIVE_ZERO_STATE fifo=$fifo functional_ff=[dict size $state] external_inputs_arbitrary=1 release_state_arbitrary=1 destination_valid_unconnected=$valid_unconnected payload_ports=[llength $bits]"
    return 1
}
