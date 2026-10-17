# Source-controlled candidate recipe, NOT physical qualification or a board claim.
# Only the explicitly selected ZU15EG USER2/50 ns profile is supported. Source
# this file after synthesis. Apply once before opt_design; reapply the scoped
# CDC procedure after opt_design. Keep all related event-clock paths timed.
set i1_bscan_chain_recipe [file join [file dirname [info script]] check_jtag_chain.tcl]
if {![file exists $i1_bscan_chain_recipe]} {
    set i1_bscan_chain_recipe [file join [file dirname [info script]] ../next/check_jtag_chain.tcl]
}
source $i1_bscan_chain_recipe
unset i1_bscan_chain_recipe

proc valence_bscan_one {kind name} {
    if {$name eq "" || [regexp {[\*\?]} $name]} {error "Exact BSCAN object required"}
    set objects [${kind} -quiet $name]
    if {[llength $objects] != 1} {error "Missing/ambiguous BSCAN object: $name"}
    return [lindex $objects 0]
}

# Vivado object handles may be stringified by clock queries; re-resolve exact
# cells for each property lookup. Cell IS_C_INVERTED can be empty after netlist
# normalization: verify the actual clock pin's explicit IS_INVERTED instead.
proc valence_bscan_property {cell property} {
    return [get_property $property [valence_bscan_one get_cells $cell]]
}
proc valence_bscan_clock_inverted {cell} {
    set value [get_property IS_INVERTED [valence_bscan_pin $cell C]]
    if {$value ni {0 1}} { error "Unverified BSCAN actual clock inversion: $cell $value" }
    return $value
}

proc valence_bscan_bank {engine tail count {sync 0}} {
    if {$engine eq "" || [regexp {[\*\?\[\]]} $engine]} {error "Exact BSCAN engine required"}
    set root [regsub -all {[][{}().+*?^$\|\\]} "$engine/$tail" {\\&}]
    set cells [get_cells -quiet -hierarchical -regexp [format {^%s_reg(\[[0-9]+\])?$} $root]]
    if {[llength $cells] != $count} {error "BSCAN bank shape requires review: $tail"}
    for {set i 0} {$i < $count} {incr i} {
        set name [expr {$count == 1 ? "${engine}/${tail}_reg" : [format {%s/%s_reg[%d]} $engine $tail $i]}]
        set cell [valence_bscan_one get_cells $name]
        if {[lsearch -exact $cells $cell] < 0} {error "BSCAN bank index mismatch: $name"}
        if {$sync && [valence_bscan_property $cell ASYNC_REG] ni {TRUE true 1}} {error "Missing ASYNC_REG: $cell"}
    }
    return $cells
}
proc valence_bscan_pin {cell pin} {return [valence_bscan_one get_pins $cell/$pin]}
proc valence_bscan_net_pins {pin direction} {
    set nets [get_nets -quiet -of_objects [valence_bscan_one get_pins $pin]]
    if {[llength $nets] != 1} {error "Missing/ambiguous BSCAN net: $pin"}
    set segments [get_nets -quiet -segments $nets]
    return [lsort -unique [get_pins -quiet -leaf -of_objects $segments -filter "DIRECTION == $direction"]]
}
proc valence_bscan_driver {pin {ooc_clock 0}} {
    set drivers [valence_bscan_net_pins $pin OUT]
    if {$ooc_clock && [llength $drivers] == 0} {
        # The independent shell exposes the fabric clock as an OOC input;
        # only this exact port may replace an on-chip clock-buffer driver.
        # Data/reset/constant nets never enter this branch.
        set nets [get_nets -quiet -of_objects [valence_bscan_one get_pins $pin]]
        set ports [get_ports -quiet -of_objects [get_nets -quiet -segments $nets] -filter {DIRECTION == IN}]
        if {$ports ne {io_clockIn}} { error "Missing/ambiguous BSCAN driver: $pin" }
        return PORT:io_clockIn
    }
    if {[llength $drivers] != 1} {error "Missing/ambiguous BSCAN driver: $pin"}
    return [lindex $drivers 0]
}
proc valence_bscan_release {engine tail inverted expected_clock} {
    set cells [valence_bscan_bank $engine $tail 3 1]
    set clock {}; set assertion {}; set previous {}; set async_pins {}
    for {set i 0} {$i < 3} {incr i} {
        set cell [valence_bscan_one get_cells [format {%s/%s_reg[%d]} $engine $tail $i]]
        if {[valence_bscan_property $cell REF_NAME] ne "FDCE" ||
            [valence_bscan_clock_inverted $cell] != $inverted} {error "BSCAN release type/edge mismatch: $cell"}
        set clock_pin [valence_bscan_pin $cell C]
        if {[get_clocks -quiet -of_objects $clock_pin] ne [list $expected_clock]} {
            error "BSCAN release clock domain mismatch: $cell"
        }
        set c [valence_bscan_driver $clock_pin [expr {$tail eq "bridge/dest_release"}]]
        set r [valence_bscan_driver [valence_bscan_pin $cell CLR]]
        if {$i == 0} {set clock $c; set assertion $r}
        if {$c ne $clock || $r ne $assertion} {error "BSCAN release clock/assertion mismatch: $cell"}
        set d [valence_bscan_driver [valence_bscan_pin $cell D]]
        if {$i == 0} {
            set constant [get_cells -quiet -of_objects [valence_bscan_one get_pins $d]]
            if {[llength $constant] != 1 || [valence_bscan_property $constant REF_NAME] ne "VCC"} {
                error "BSCAN release must start with constant one: $cell"
            }
        } else {
            if {$d ne "$previous/Q"} {error "BSCAN release chain broken: $cell"}
            if {[valence_bscan_net_pins [valence_bscan_pin $previous Q] IN] ne [list "$cell/D"]} {
                error "BSCAN release intermediate functional fanout: $previous"
            }
        }
        set previous $cell
        lappend async_pins [valence_bscan_pin $cell CLR]
    }
    # Only the 3 checked synchronizer CLR pins; never functional reset sinks,
    # D/Q paths, update_seen, qualifier data, or the UPDATE bank's D/CE pins.
    set_false_path -to $async_pins
    puts "BSCAN_RESET_RELEASE tail=$tail edge_inverted=$inverted clr=$async_pins"
}
proc valence_bscan_qualifiers {primitive engine} {
    set update_cells {}
    foreach {tail count} {update_frame 64 update_length_ok 1 update_toggle 1 update_overrun 1} {
        lappend update_cells {*}[valence_bscan_bank $engine $tail $count]
    }
    set qualifiers {}
    foreach tail {update_selected update_ack} {lappend qualifiers {*}[valence_bscan_bank $engine $tail 1]}
    foreach cell $update_cells {
        if {[get_clocks -quiet -of_objects [valence_bscan_pin $cell C]] ne {valence_bscan_update}} {
            error "BSCAN UPDATE bank clock domain mismatch: $cell"
        }
    }
    foreach cell $qualifiers {
        if {[get_clocks -quiet -of_objects [valence_bscan_pin $cell C]] ne {valence_bscan_tck}} {
            error "BSCAN qualifier clock domain mismatch: $cell"
        }
        if {[valence_bscan_property $cell REF_NAME] ne "FDCE" || [valence_bscan_clock_inverted $cell] != 0} {
            error "BSCAN qualifier must remain a positive-TCK resettable register: $cell"
        }
    }
    # Related-clock combinational cones must stop at the positive-TCK bank.
    # all_fanin (not just startpoints) also detects an accidentally live SEL arc.
    set targets [get_pins -quiet -of_objects [get_cells -quiet $update_cells] -filter {REF_PIN_NAME == D || REF_PIN_NAME == CE}]
    if {[llength $targets] == 0} { error "BSCAN UPDATE data/enable pins missing" }
    set cone [all_fanin -flat -to $targets]
    foreach forbidden [list "$primitive/SEL" [format {%s/source_release_reg[2]/Q} $engine] "$engine/update_seen_reg/Q"] {
        if {[lsearch -exact $cone $forbidden] >= 0} {error "Live same-edge BSCAN control feeds UPDATE: $forbidden"}
    }
    foreach cell $qualifiers {
        if {[lsearch -exact $cone "$cell/Q"] < 0} {error "BSCAN qualifier not driving UPDATE bank: $cell"}
    }
    # Both the UPDATE bank and qualifier flops release only through stage 2 of
    # the new positive-TCK fence. Functional CLR paths remain normally timed.
    set expected [format {%s/update_release_reg[2]/Q} $engine]
    set expected_start [format {%s/update_release_reg[2]/C} $engine]
    foreach cell [concat $update_cells $qualifiers] {
        set pin [valence_bscan_pin $cell CLR]
        set starts [lsort -unique [all_fanin -flat -startpoints_only -to $pin]]
        # Vivado's timing startpoint is the launching register C pin, not Q.
        # Also require its actual Q in the complete cone; never accept an
        # arbitrary same-clock register or a direct raw-reset bypass.
        set reset_cone [all_fanin -flat -to [valence_bscan_pin $cell CLR]]
        if {$starts ne [list $expected_start] || [lsearch -exact $reset_cone $expected] < 0} {
            error "BSCAN UPDATE reset bypasses positive release: $cell $starts"
        }
    }
    puts "BSCAN_POSITIVE_QUALIFICATION present=2 update_bits=67 raw_control_cones=0"
}
proc valence_bscan_bundle {engine source destination count} {
    set src [valence_bscan_bank $engine $source $count]
    set dst [valence_bscan_bank $engine $destination $count]
    set launch [get_pins -quiet -of_objects [get_cells -quiet $src] -filter {REF_PIN_NAME == C}]
    set capture [get_pins -quiet -of_objects [get_cells -quiet $dst] -filter {REF_PIN_NAME == D}]
    if {[llength $launch] != $count || [llength $capture] != $count} {error "BSCAN bundle pin count mismatch"}
    set_max_delay -datapath_only 8.000 -from $launch -to $capture
    set_bus_skew 8.000 -from $launch -to $capture
    puts "BSCAN_HELD_BUNDLE source=$source destination=$destination bits=$count max_ns=8 skew_ns=8"
}
proc valence_reapply_bscan_cdc {primitive engine fabric_clock} {
    valence_bscan_qualifiers $primitive $engine
    foreach {tail count} {update_sync 2 bridge/request_sync 2 bridge/response_sync 2} {
        valence_bscan_bank $engine $tail $count 1
    }
    foreach {tail inverted} {source_release 1 update_release 0 bridge/source_release 1 bridge/dest_release 0} {
        set clock [expr {$tail eq "bridge/dest_release" ? $fabric_clock : "valence_bscan_tck"}]
        valence_bscan_release $engine $tail $inverted $clock
    }
    foreach {source destination} {bridge/request_toggle bridge/request_sync bridge/response_toggle bridge/response_sync} {
        set src [valence_bscan_bank $engine $source 1]
        set dst [valence_bscan_one get_cells [format {%s/%s_reg[0]} $engine $destination]]
        set_max_delay -datapath_only 8.000 -from [valence_bscan_pin $src C] -to [valence_bscan_pin $dst D]
    }
    valence_bscan_bundle $engine bridge/request_held bridge/dest_request 41
    valence_bscan_bundle $engine bridge/response_held bridge/s_rsp_payload 34
    puts "BSCAN_EVENT_CLOCK_PATHS_FULLY_TIMED NO_MULTICYCLE NO_ASYNC_CLOCK_GROUP"
}
proc valence_apply_bscan_timing {primitive engine fabric_clock profile} {
    if {$profile ne "zu15eg-user2-tck50-positive-v1"} {error "Explicit reviewed BSCAN candidate profile required"}
    if {[string tolower [get_property PART [current_design]]] ne "xczu15eg-ffvb1156-2-i"} {
        error "BSCAN candidate part/profile mismatch"
    }
    valence_assert_jtag_chain 2 $primitive
    valence_bscan_one get_cells $engine
    valence_bscan_one get_clocks $fabric_clock
    if {![regsub {([/.])transport$} $engine {\1user_scan} expected] || $primitive ne $expected} {
        error "BSCAN primitive and transport are not matching siblings"
    }
    foreach name {valence_bscan_tck valence_bscan_drck valence_bscan_update} {
        if {[llength [get_clocks -quiet $name]] != 0} {error "BSCAN clock already exists; do not apply clocks twice"}
    }
    set master [valence_bscan_one get_pins $primitive/INTERNAL_TCK]
    create_clock -name valence_bscan_tck -period 50.000 -waveform {0 25} $master
    create_generated_clock -name valence_bscan_drck -source $master -divide_by 1 \
        [valence_bscan_one get_pins $primitive/DRCK]
    # Event envelope, not a scan-length divider. The primitive's clock arc is
    # propagated by STA; never add its 5.1 ns a second time as a phase offset.
    create_generated_clock -name valence_bscan_update -source $master -edges {2 3 4} \
        [valence_bscan_one get_pins $primitive/UPDATE]
    set clocks [get_clocks {valence_bscan_tck valence_bscan_drck valence_bscan_update}]
    # Explicitly cover all related pairs, unlike the historical TCK-only model.
    set_clock_uncertainty -setup 0.100 -from $clocks -to $clocks
    set_clock_uncertainty -hold 0.100 -from $clocks -to $clocks
    foreach name {INTERNAL_TDI INTERNAL_TMS} {
        set pin [valence_bscan_one get_pins $primitive/$name]
        set_input_delay -clock valence_bscan_tck -clock_fall -max 15.000 $pin
        set_input_delay -clock valence_bscan_tck -clock_fall -min 0.000 $pin
    }
    foreach {pin name waveform} {TCK valence_bscan_tck {0 25} DRCK valence_bscan_drck {0 25} UPDATE valence_bscan_update {25 50}} {
        set actual [get_clocks -quiet -of_objects [valence_bscan_one get_pins $primitive/$pin]]
        if {[llength $actual] != 1 || [get_property NAME $actual] ne $name ||
            abs([get_property PERIOD $actual] - 50.0) > 0.001} {error "BSCAN actual clock contract failed: $pin"}
        set edges [get_property WAVEFORM $actual]
        if {[llength $edges] != 2} {error "BSCAN clock waveform missing: $pin"}
        foreach edge $edges expected $waveform {
            if {abs($edge - $expected) > 0.001} {error "BSCAN actual clock phase failed: $pin"}
        }
    }
    valence_reapply_bscan_cdc $primitive $engine $fabric_clock
    puts "BSCAN_SOURCE_CONTROLLED_CANDIDATE_NOT_PHYSICAL_SIGNOFF profile=$profile"
}
