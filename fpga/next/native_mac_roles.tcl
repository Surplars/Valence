# Source-bound semantic gate for a FRESH mapped design. Read-only; no exceptions.
# Query object types afresh at every property/-of_objects boundary. Names are
# observations, never admitted old cell-count/CE/checkpoint certificates.
namespace eval valence_mac_roles {}
proc valence_mac_roles::property {command name key} {
    if {[llength [$command -quiet $name]] != 1 || [get_property NAME [$command -quiet $name]] ne $name} {
        error "MAC role object missing/ambiguous: $name"
    }
    return [get_property $key [$command -quiet $name]]
}
proc valence_mac_roles::bit {value expected} {
    if {$expected} {return [expr {$value in {1 TRUE true 1'b1}}]}
    return [expr {$value in {0 FALSE false 1'b0}}]
}
proc valence_mac_roles::net {pin} {
    property get_pins $pin NAME
    if {![llength [get_nets -quiet -segments -of_objects [get_pins -quiet $pin]]]} {error "Disconnected role pin: $pin"}
    return [lindex [lsort [get_property NAME [get_nets -quiet -segments -of_objects [get_pins -quiet $pin]]]] 0]
}
proc valence_mac_roles::same {left right} {return [expr {[net $left] eq [net $right]}]}
proc valence_mac_roles::driver {pin} {
    property get_pins $pin NAME
    if {[llength [get_pins -quiet -leaf -of_objects [get_nets -quiet -segments -of_objects [get_pins -quiet $pin]] -filter {DIRECTION == OUT}]] != 1} {
        error "Missing/multiple direct drivers: $pin"
    }
    return [get_property NAME [get_pins -quiet -leaf -of_objects [get_nets -quiet -segments -of_objects [get_pins -quiet $pin]] -filter {DIRECTION == OUT}]]
}
proc valence_mac_roles::pins {cell} {
    property get_cells $cell NAME
    return [get_property NAME [get_pins -quiet -of_objects [get_cells -quiet $cell]]]
}
proc valence_mac_roles::data {cell index} {
    set found {}
    foreach pin [pins $cell] {
        if {[property get_pins $pin REF_PIN_NAME] eq [format {D[%d]} $index]} {lappend found $pin}
    }
    if {[llength $found]!=1} {error "Missing ODDR D$index pin"}
    return [lindex $found 0]
}
proc valence_mac_roles::constant {pin value} {
    set n [net $pin]
    return [expr {[property get_nets $n TYPE] eq ($value ? "POWER" : "GROUND")}]
}
# Bounded combinational truth evaluation from actual INIT and ordered pin arcs.
# Unrecognized primitives, hidden sequential leaves, cycles and oversized cones
# fail closed. This is a small serializer equation checker, not a general proof.
proc valence_mac_roles::value {pin assignment {seen {}}} {
    variable coneFacts
    set n [net $pin]
    if {[dict exists $assignment $n]} {return [dict get $assignment $n]}
    if {[constant $pin 0]} {return 0}
    if {[constant $pin 1]} {return 1}
    if {[llength $seen]>=12 || $n in $seen} {error "Unbounded/cyclic mapped serializer cone"}
    lappend seen $n
    set output [driver $pin]; set c [file dirname $output]
    set ref [property get_cells $c REF_NAME]
    dict set coneFacts $c [list ref $ref init [property get_cells $c INIT]]
    foreach arc [pins $c] {dict lappend coneFacts $c arcs [list $arc [net $arc]]}
    if {$ref eq "INV"} {return [expr {1-[value $c/I $assignment $seen]}]}
    if {$ref in {MUXF7 MUXF8 MUXF9}} {
        set select [value $c/S $assignment $seen]
        return [value $c/I$select $assignment $seen]
    }
    if {![regexp {^LUT([1-6])$} $ref -> width]} {error "Unproved sequential/primitive leaf $output ($ref)"}
    set init [property get_cells $c INIT]
    if {![regexp {^([0-9]+)'([hHbB])([0-9a-fA-F]+)$} $init -> bits radix digits] || $bits != (1<<$width)} {error "Unsupported LUT INIT: $c $init"}
    if {[string tolower $radix] eq "h"} {set table [expr 0x$digits]} else {
        if {![regexp {^[01]+$} $digits]} {error "Nonbinary LUT INIT"}
        set table [expr 0b$digits]
    }
    if {$table >= (1<<$bits)} {error "Oversized LUT INIT"}
    set index 0
    for {set i 0} {$i<$width} {incr i} {set index [expr {$index | ([value $c/I$i $assignment $seen]<<$i)}]}
    return [expr {($table>>$index)&1}]
}
proc valence_mac_roles::ff {c falling preset clock reset} {
    set ref [expr {$preset ? "FDPE" : "FDCE"}]; set rp [expr {$preset ? "PRE" : "CLR"}]
    if {[property get_cells $c REF_NAME] ne $ref || ![bit [property get_cells $c INIT] $preset] ||
        ![bit [property get_pins $c/C IS_INVERTED] $falling] || ![bit [property get_pins $c/$rp IS_INVERTED] 0] ||
        [net $c/C] ne $clock || [net $c/$rp] ne $reset} {error "Unproved FF clock/reset/INIT: $c"}
}
proc valence_mac_roles::qff {pin falling preset clock reset} {
    set q [driver $pin]
    if {[property get_pins $q REF_PIN_NAME] ne "Q"} {error "Final ODDR input is not direct FF Q: $pin"}
    set c [file dirname $q]; ff $c $falling $preset $clock $reset
    return $c
}
proc valence_mac_roles::next {c assignment} {
    if {[value $c/CE $assignment]} {return [value $c/D $assignment]}
    return [dict get $assignment [net $c/Q]]
}
proc valence_mac_roles::prove {c phase rise high kind} {
    # Unique net variables preserve actual merged/aliased roles. Constants stay
    # constants. This permits a merged bank only if its exact equation proves.
    set variables [lsort -unique [list [net $phase/Q] [net $rise] [net $high] [net $c/Q]]]
    set independent {}
    foreach n $variables {if {[property get_nets $n TYPE] ni {POWER GROUND}} {lappend independent $n}}
    for {set v 0} {$v<(1<<[llength $independent])} {incr v} {
        set a {}; set i 0
        foreach n $independent {dict set a $n [expr {($v>>$i)&1}]; incr i}
        set p [value $phase/Q $a]; set r [value $rise $a]; set h [value $high $a]
        set expected [expr {$p ? $h : $r}]
        if {[next $c $a] != $expected} {error "Mapped $kind transition equation differs: $c vector=$v"}
    }
}
proc valence_mac_roles::clocks {hier} {
    foreach {pin period} [list $hier/tx_pad_clock 4.0 $hier/tx_clock 8.0] {
        if {[llength [get_clocks -quiet -of_objects [get_pins -quiet $pin]]] != 1 ||
            abs([get_property PERIOD [get_clocks -quiet -of_objects [get_pins -quiet $pin]]]-$period)>0.001} {
            error "Unconstrained/wrong actual PAD/RAW clock: $pin"
        }
    }
    if {[llength [get_clocks -quiet -of_objects [get_pins -quiet [file dirname [driver $hier/tx_pad_clock]]/I]]]!=1 ||
        abs([get_property PERIOD [get_clocks -quiet -of_objects [get_pins -quiet [file dirname [driver $hier/tx_pad_clock]]/I]]]-2.0)>0.001} {error "PAD/RAW source is not the common REF500 clock"}
    set pad [file dirname [driver $hier/tx_pad_clock]]; set raw [file dirname [driver $hier/tx_clock]]
    foreach {c ratio} [list $pad 2 $raw 4] {
        if {[property get_cells $c REF_NAME] ne "BUFGCE_DIV" || [property get_cells $c BUFGCE_DIVIDE]!=$ratio || ![constant $c/CE 1]} {error "Unproved actual PAD/RAW divider"}
    }
    if {![same $pad/I $raw/I] || ![same $pad/CLR $raw/CLR]} {error "PAD/RAW do not share source and reset epoch"}
    foreach {c period fall} [list $pad 4.0 2.0 $raw 8.0 4.0] {
        if {[llength [get_clocks -quiet -of_objects [get_pins -quiet $c/O]]]!=1} {error "Ambiguous divider clock"}
        lassign [get_property WAVEFORM [get_clocks -quiet -of_objects [get_pins -quiet $c/O]]] r f
        if {abs($r)>0.001 || abs($f-$fall)>0.001} {error "PAD/RAW epoch waveform mismatch"}
    }
}
# Classify only the exact retained hierarchical control input. Failed queries
# are not disconnection evidence. A shared global GND may have unrelated loads;
# only actual primitive loads inside this literal hierarchy invalidate deadness.
proc valence_mac_roles::control_fall {hier rise fall} {
    if {$fall ne [format {%s/tx_fall[4]} $hier]} {error "Wrong control-fall role"}
    if {[property get_pins $fall DIRECTION] ne "IN" || ![bit [property get_pins $fall IS_LEAF] 0]} {
        error "Control fall must be the retained non-leaf hierarchical input"
    }
    set direct [llength [get_nets -quiet -of_objects [get_pins -quiet $fall]]]
    set segments [llength [get_nets -quiet -segments -of_objects [get_pins -quiet $fall]]]
    if {$direct==0 && $segments==0} {return disconnected}
    if {$direct!=1 || $segments<1} {error "Control-fall direct/segment connectivity is malformed"}
    if {[same $fall $rise]} {return same_net}
    if {[get_property TYPE [get_nets -quiet -of_objects [get_pins -quiet $fall]]] ne "GROUND"} {error "Unreviewed distinct live control-fall source"}
    # Do not call -of_objects with an empty collection: Vivado can broaden it.
    set count [llength [get_pins -quiet -leaf -of_objects [get_nets -quiet -segments -of_objects [get_pins -quiet $fall]] -filter {DIRECTION == IN}]]
    if {$count} {
        foreach pin [get_property NAME [get_pins -quiet -leaf -of_objects [get_nets -quiet -segments -of_objects [get_pins -quiet $fall]] -filter {DIRECTION == IN}]] {
            if {[string first "$hier/" $pin]==0} {error "Dead control-fall GND still has an in-hierarchy leaf consumer: $pin"}
        }
    }
    return ground
}

proc valence_mac_roles::audit {hier t1 selected} {
    variable coneFacts
    set coneFacts {}
    if {$t1 ni {0 1} || $selected ni {0 1}} {error "Explicit bound two-Boolean mode required"}
    clocks $hier
    set clock [net $hier/tx_pad_clock]
    # Boundary output roles are source-bound. Internal mapped names are observed.
    set outputs [list {*}[lmap i {0 1 2 3} {format {%s/rgmii_tx_data[%d]} $hier $i}] $hier/rgmii_tx_control $hier/rgmii_tx_clock]
    set oddrs {}; foreach output $outputs {
        set q [driver $output]; set c [file dirname $q]
        if {[property get_cells $c REF_NAME] ne "OSERDESE3" || [property get_pins $q REF_PIN_NAME] ne "OQ"} {error "Output lacks direct actual ODDR role: $output"}
        lappend oddrs $c
    }
    if {[llength [lsort -unique $oddrs]]!=6} {error "Require six distinct actual ODDRs"}
    set reset [net [lindex $oddrs 0]/RST]
    foreach c $oddrs {
        if {![bit [property get_cells $c ODDR_MODE] 1] || ![bit [property get_cells $c OSERDES_D_BYPASS] 0] ||
            ![bit [property get_cells $c IS_CLK_INVERTED] 0] || ![bit [property get_pins $c/RST IS_INVERTED] 0] ||
            [net $c/CLK] ne $clock || [net $c/RST] ne $reset} {error "ODDR mode/C/SR mismatch: $c"}
    }
    set candidates [get_property NAME [get_cells -quiet -hier -filter {REF_NAME == FDCE || REF_NAME == FDPE}]]
    set phase {}; set falling {}
    foreach c $candidates {
        if {![string match $hier/* $c]} {continue}
        if {![catch {ff $c 1 0 $clock $reset}]} {lappend falling $c}
        if {![catch {ff $c 0 1 $clock $reset}]} {
            if {![constant $c/CE 1]} {continue}
            set valid 1
            foreach p {0 1} {if {[catch {value $c/D [dict create [net $c/Q] $p]} result] || $result != 1-$p} {set valid 0}}
            if {$valid} {lappend phase $c}
        }
    }
    if {[llength $phase]!=1} {error "Require one actual preset-high inversion-feedback phase role"}
    set phase [lindex $phase 0]
    set txc [lindex $oddrs 5]
    set previous [qff [data $txc 0] 0 0 $clock $reset]
    if {![constant $previous/CE 1] || ![same $previous/D [data $txc 4]]} {error "Previous-clock is not the exact selected TXC sample"}
    if {$t1} {
        set release [qff [lindex $oddrs 0]/RST 1 1 $clock [net $hier/tx_pad_reset]]
        if {![constant $release/D 0] || ![constant $release/CE 1] || $reset eq [net $hier/tx_pad_reset]} {error "T1 local release mode mismatch"}
    } elseif {$reset ne [net $hier/tx_pad_reset]} {error "OFF must use direct RAW reset"}
    set used {}; set roles {}; set lanes [lrange $oddrs 0 4]
    for {set i 0} {$i<6} {incr i} {
        set c [lindex $oddrs $i]
        if {$i<5} {
            set d [data $c 0]
            if {![same $d [data $c 4]]} {error "Actual data/control D0/D4 differ"}
            set rise [format {%s/tx_rise[%d]} $hier $i]; set fall [format {%s/tx_fall[%d]} $hier $i]
        } else {set d [data $c 4]; set rise $hier/txc_rise; set fall $hier/txc_fall}
        set sourceAlias 0
        if {$i==4 && [info exists ::valence_native_mac_mode::control_lemma] && $::valence_native_mac_mode::control_lemma} {
            # The dead fall port is not evidence of equality. Only the freshly
            # rechecked complete encoder/parent + selected RTL source lemma
            # permits this quotient; require the live upstream mapped chain.
            set encoder u_soc/board/nativeBank/gmac/encode
            if {![same $rise [format {%s/io_rise[4]} $encoder]] || ![same $encoder/clock $hier/tx_clock]} {error "Source control lemma mapped encoder chain mismatch"}
            set upstream [qff $rise 0 0 [net $encoder/clock] [net $encoder/reset]]
            set fallShape [control_fall $hier $rise $fall]
            if {$fallShape ni {same_net ground disconnected}} {error "Unproved control-fall shape"}
            set fall $rise
            set sourceAlias 1
        }
        set pairs {}
        foreach high $falling {
            if {[catch {prove $high $phase $fall $high/Q saved_high}]} {continue}
            foreach low $falling {
                if {$selected} {
                    if {[catch {set actual [qff $d 1 0 $clock $reset]}] || $actual ne $low || [catch {prove $low $phase $rise $high/Q selected_final}]} {continue}
                } else {
                    if {[catch {prove $low $phase $rise $low/Q source_low}]} {continue}
                    set variables [lsort -unique [list [net $phase/Q] [net $low/Q] [net $high/Q]]]
                    set valid 1
                    for {set v 0} {$v<(1<<[llength $variables])} {incr v} {
                        set a {}; set j 0; foreach n $variables {dict set a $n [expr {($v>>$j)&1}]; incr j}
                        set expected [expr {[value $phase/Q $a] ? [value $high/Q $a] : [value $low/Q $a]}]
                        if {[catch {value $d $a} observed] || $observed!=$expected} {set valid 0; break}
                    }
                    if {!$valid} {continue}
                }
                lappend pairs [list $low $high]
            }
        }
        if {[llength $pairs]!=1} {error "Role $i lacks a unique source-bound low/high equation proof; fresh merged-role review required"}
        lassign [lindex $pairs 0] low high
        lappend used $low $high
        lappend roles [list role $i oddr $c final $low saved_high $high source_rise [net $rise] source_fall [net $fall] merged [expr {$low eq $high}] source_control_lemma $sourceAlias]
    }
    if {[lsort -unique $used] ne [lsort -unique $falling]} {error "Unaccounted falling-PAD serializer FF role"}
    # Names and all D/CE/C/reset arcs are observations for both synth/postopt.
    set arcs {}
    foreach c [lsort -unique [list {*}$used $phase $previous {*}[expr {$t1 ? [list $release] : {}}]]] {
        set record [list cell $c ref [property get_cells $c REF_NAME] init [property get_cells $c INIT]]
        foreach pin [pins $c] {set n [net $pin]; lappend record [list pin $pin net $n net_type [property get_nets $n TYPE] inverted [property get_pins $pin IS_INVERTED]]}
        lappend arcs $record
    }
    set ::valence_mac_roles::last_clock $txc
    set ::valence_mac_roles::last_lanes $lanes
    return "PASS_MAC_ROLE_SEMANTICS t1=$t1 selected_half=$selected roles={$roles} phase={$phase} previous={$previous} arcs={$arcs} combinational_cones={$coneFacts} timing_qualified=0 exception_coverage=not_checked exception_permission=0"
}
