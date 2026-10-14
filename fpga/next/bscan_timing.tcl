# Source-controlled candidate recipe, NOT physical qualification or a board claim.
# Only the explicitly selected ZU15EG USER2/50 ns profile is supported. Source
# this file after synthesis. Apply once before opt_design; reapply the scoped
# CDC procedure after opt_design. Keep all related event-clock paths timed.
source [file join [file dirname [info script]] check_jtag_chain.tcl]

proc valence_bscan_one {kind name} {
    if {$name eq "" || [regexp {[\*\?]} $name]} {error "Exact BSCAN object required"}
    set objects [${kind} -quiet $name]
    if {[llength $objects] != 1} {error "Missing/ambiguous BSCAN object: $name"}
    return [${kind} -quiet $name]
}
# Reconstitute exact object collections after Tcl list assembly.
proc valence_bscan_objects {kind names} {
 set expected [lsort -unique $names]
 if {![llength $expected] || [llength $expected]!=[llength $names]} {error {Empty/duplicate BSCAN exact collection}}
 foreach name $expected {if {$name eq "" || [regexp {[\*\?]} $name]} {error {BSCAN refuses wildcard objects}}}
 set found [$kind -quiet $expected]
 if {[llength $found]!=[llength $expected] || [lsort [get_property NAME $found]] ne $expected} {error {BSCAN exact typed collection differs}}
 return [$kind -quiet $expected]
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
        if {$sync && [get_property ASYNC_REG [valence_bscan_one get_cells $cell]] ni {TRUE true 1}} {error "Missing ASYNC_REG: $cell"}
    }
    return [get_cells -quiet -hierarchical -regexp [format {^%s_reg(\[[0-9]+\])?$} $root]]
}
proc valence_bscan_pin {cell pin} {return [valence_bscan_one get_pins $cell/$pin]}
proc valence_bscan_net_pins {pin direction} {
    set nets [get_nets -quiet -of_objects $pin]
    if {[llength $nets] != 1} {error "Missing/ambiguous BSCAN net: $pin"}
    set segments [get_nets -quiet -segments $nets]
    return [lsort -unique [get_pins -quiet -leaf -of_objects $segments -filter "DIRECTION == $direction"]]
}
proc valence_bscan_driver {pin} {
    set drivers [valence_bscan_net_pins $pin OUT]
    if {[llength $drivers] != 1} {error "Missing/ambiguous BSCAN driver: $pin"}
    return [lindex $drivers 0]
}
proc valence_bscan_release {engine tail inverted expected_clock} {
    set cells [valence_bscan_bank $engine $tail 3 1]
    set clock {}; set assertion {}; set previous {}; set async_pins {}
    for {set i 0} {$i < 3} {incr i} {
        set cell [valence_bscan_one get_cells [format {%s/%s_reg[%d]} $engine $tail $i]]
        if {[get_property REF_NAME [valence_bscan_one get_cells $cell]] ne "FDCE" ||
            [get_property IS_INVERTED [valence_bscan_pin $cell C]] != $inverted} {error "BSCAN release type/edge mismatch: $cell"}
        set clock_pin [valence_bscan_pin $cell C]
        if {[get_clocks -quiet -of_objects $clock_pin] ne [list $expected_clock]} {
            error "BSCAN release clock domain mismatch: $cell"
        }
        set c [valence_bscan_driver $clock_pin]
        set r [valence_bscan_driver [valence_bscan_pin $cell CLR]]
        if {$i == 0} {set clock $c; set assertion $r}
        if {$c ne $clock || $r ne $assertion} {error "BSCAN release clock/assertion mismatch: $cell"}
        set d [valence_bscan_driver [valence_bscan_pin $cell D]]
        if {$i == 0} {
            set constant [get_cells -quiet -of_objects [valence_bscan_one get_pins $d]]
            if {[llength $constant] != 1 || [get_property REF_NAME [valence_bscan_one get_cells $constant]] ne "VCC"} {
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
    set_false_path -to [valence_bscan_objects get_pins $async_pins]
    puts "BSCAN_RESET_RELEASE tail=$tail edge_inverted=$inverted clr=$async_pins"
}
proc valence_bscan_qualifiers {primitive engine} {
    set update_cells {}
    foreach {tail count} {update_frame 64 update_length_ok 1 update_toggle 1 update_overrun 1} {
        lappend update_cells {*}[valence_bscan_bank $engine $tail $count]
    }
    set qualifiers {}
    foreach tail {update_selected update_ack} {lappend qualifiers {*}[valence_bscan_bank $engine $tail 1]}
    # Restore Vivado object collections after assembling exact bank names.
    set update_cells [get_cells -quiet $update_cells]
    set qualifiers [get_cells -quiet $qualifiers]
    foreach cell $update_cells {
        if {[get_clocks -quiet -of_objects [valence_bscan_pin $cell C]] ne {valence_bscan_update}} {
            error "BSCAN UPDATE bank clock domain mismatch: $cell"
        }
    }
    foreach cell $qualifiers {
        if {[get_clocks -quiet -of_objects [valence_bscan_pin $cell C]] ne {valence_bscan_tck}} {
            error "BSCAN qualifier clock domain mismatch: $cell"
        }
        if {[get_property REF_NAME [valence_bscan_one get_cells $cell]] ne "FDCE" || [get_property IS_INVERTED [valence_bscan_pin $cell C]] != 0} {
            error "BSCAN qualifier must remain a positive-TCK resettable register: $cell"
        }
    }
    # Related-clock combinational cones must stop at the positive-TCK bank.
    # all_fanin (not just startpoints) also detects an accidentally live SEL arc.
    set targets [get_pins -quiet -of_objects $update_cells -filter {REF_PIN_NAME == D || REF_PIN_NAME == CE}]
    set cone [all_fanin -flat -to $targets]
    foreach forbidden [list "$primitive/SEL" [format {%s/source_release_reg[2]/Q} $engine] "$engine/update_seen_reg/Q"] {
        if {[lsearch -exact $cone $forbidden] >= 0} {error "Live same-edge BSCAN control feeds UPDATE: $forbidden"}
    }
    foreach cell $qualifiers {
        if {[lsearch -exact $cone "$cell/Q"] < 0} {error "BSCAN qualifier not driving UPDATE bank: $cell"}
    }
    # Both the UPDATE bank and qualifier flops release only through stage 2 of
    # the new positive-TCK fence. Functional CLR paths remain normally timed.
    set expected [format {%s/update_release_reg[2]/C} $engine]
    foreach cell [concat $update_cells $qualifiers] {
        set pin [valence_bscan_pin $cell CLR]
        set starts [lsort -unique [all_fanin -flat -startpoints_only -to $pin]]
        if {$starts ne [list $expected]} {error "BSCAN UPDATE reset bypasses positive release: $cell $starts"}
    }
    puts "BSCAN_POSITIVE_QUALIFICATION present=2 update_bits=67 raw_control_cones=0"
}
# This check adds no exception. The related-clock ingress and functional CLR
# pins remain timed, and any reshaped/optimized bank requires a source review.
proc valence_bscan_phase_handoff {engine} {
    set handoff_cells {}
    foreach {tail source count} {handoff_frame update_frame 64 handoff_length_ok update_length_ok 1 handoff_toggle update_toggle 1} {
        set bank [valence_bscan_bank $engine $tail $count]
        lappend handoff_cells {*}$bank
        foreach cell $bank {
            if {[get_property REF_NAME [valence_bscan_one get_cells $cell]] ne "FDCE" ||
                [get_property IS_INVERTED [valence_bscan_pin $cell C]] != 0 ||
                [get_clocks -quiet -of_objects [valence_bscan_pin $cell C]] ne {valence_bscan_tck}} {
                error "BSCAN handoff must remain positive TCK: $cell"
            }
            set source_cell [string map [list "/${tail}_reg" "/${source}_reg"] $cell]
            if {[valence_bscan_driver [valence_bscan_pin $cell D]] ne "$source_cell/Q"} {
                error "BSCAN handoff input bypass/mismatch: $cell"
            }
        }
    }
    set first [valence_bscan_one get_cells [format {%s/update_sync_reg[0]} $engine]]
    if {[get_property IS_INVERTED [valence_bscan_pin $first C]] != 1 ||
        [get_clocks -quiet -of_objects [valence_bscan_pin $first C]] ne {valence_bscan_tck}} {
        error "BSCAN notification must remain negative TCK"
    }
    if {[valence_bscan_driver [valence_bscan_pin $first D]] ne "$engine/handoff_toggle_reg/Q"} {
        error "BSCAN notification bypasses positive handoff"
    }
    set request [valence_bscan_bank $engine bridge/request_held 41]
    set targets [get_pins -quiet -of_objects $request -filter {REF_PIN_NAME == D || REF_PIN_NAME == CE}]
    set cone [all_fanin -flat -to $targets]
    foreach {tail count} {update_frame 64 update_length_ok 1 update_toggle 1} {
        foreach cell [valence_bscan_bank $engine $tail $count] {
            if {[lsearch -exact $cone "$cell/Q"] >= 0} {error "BSCAN request bypasses positive handoff: $cell"}
        }
    }
    set shift_cells {}
    foreach {tail count} {shift_frame 64 shift_count 7 scan_captured 1} {
        lappend shift_cells {*}[valence_bscan_bank $engine $tail $count]
    }
    foreach cell $shift_cells {
        if {[get_property REF_NAME [valence_bscan_one get_cells $cell]] ne "FDCE" ||
            [get_property IS_INVERTED [valence_bscan_pin $cell C]] != 0 ||
            [get_clocks -quiet -of_objects [valence_bscan_pin $cell C]] ne {valence_bscan_drck}} {
            error "BSCAN shift storage must remain positive DRCK: $cell"
        }
    }
    set hard_reset [valence_bscan_bank $engine hard_reset 1]
    if {[get_property REF_NAME [valence_bscan_one get_cells $hard_reset]] ne "FDCE" ||
        [get_property IS_INVERTED [valence_bscan_pin $hard_reset C]] != 1 ||
        [get_clocks -quiet -of_objects [valence_bscan_pin $hard_reset C]] ne {valence_bscan_tck}} {
        error "BSCAN hard reset must remain negative TCK"
    }
    foreach {bank release} [list [concat $handoff_cells $shift_cells] source_release $hard_reset hard_release] {
        set expected [format {%s/%s_reg[2]/C} $engine $release]
        foreach cell $bank {
            set starts [lsort -unique [all_fanin -flat -startpoints_only -to [valence_bscan_pin $cell CLR]]]
            if {$starts ne [list $expected]} {error "BSCAN functional reset bypasses phase fence: $cell $starts"}
        }
    }
    # hard_reset drives work_reset. Its independent raw-reset release fence may
    # not receive that feedback, even indirectly through another release bank.
    set hard [valence_bscan_one get_cells [format {%s/hard_release_reg[0]} $engine]]
    set reset_cone [all_fanin -flat -to [valence_bscan_pin $hard CLR]]
    foreach forbidden [list "$engine/hard_reset_reg/Q"                        [format {%s/source_release_reg[2]/Q} $engine]                        [format {%s/update_release_reg[2]/Q} $engine]] {
        if {[lsearch -exact $reset_cone $forbidden] >= 0} {error "BSCAN hard-reset release has work-reset feedback: $forbidden"}
    }
    puts "BSCAN_PHASE_HANDOFF payload_bits=64 length_bits=1 toggle_bits=1 functional_reset_fences=verified overrun_remains_timed=1"
}
# Read-only, and also called by the independent report collector. Discover ALL
# negative-TCK D/CE sinks below the exact transport root, including bridge and
# controller state that is not part of the named request-payload bank.
proc valence_bscan_fault_phase {engine} {
    set sample [valence_bscan_bank $engine fault_sample 1]
    set raw [valence_bscan_bank $engine update_overrun 1]
    set sticky [valence_bscan_bank $engine protocol_error 1]
    if {[get_property REF_NAME [valence_bscan_one get_cells $sample]] ne "FDCE" ||
        [get_property IS_INVERTED [valence_bscan_pin $sample C]] != 0 ||
        [get_clocks -quiet -of_objects [valence_bscan_pin $sample C]] ne {valence_bscan_tck}} {
        error "BSCAN fault sample must remain positive TCK"
    }
    if {[valence_bscan_driver [valence_bscan_pin $sample D]] ne "$raw/Q"} {
        error "BSCAN fault sample input must be direct UPDATE overrun"
    }
    set enable_driver [valence_bscan_driver [valence_bscan_pin $sample CE]]
    set enable_cell [get_cells -quiet -of_objects [valence_bscan_one get_pins $enable_driver]]
    if {[llength $enable_cell] != 1 || [get_property REF_NAME [valence_bscan_one get_cells $enable_cell]] ne "VCC"} {
        error "BSCAN fault sample must capture every positive TCK"
    }
    set expected [format {%s/source_release_reg[2]/C} $engine]
    set starts [lsort -unique [all_fanin -flat -startpoints_only -to [valence_bscan_pin $sample CLR]]]
    if {$starts ne [list $expected]} {error "BSCAN fault sample reset bypasses source release: $starts"}
    if {[get_property IS_INVERTED [valence_bscan_pin $sticky C]] != 1 ||
        [get_clocks -quiet -of_objects [valence_bscan_pin $sticky C]] ne {valence_bscan_tck}} {
        error "BSCAN sticky fault must remain negative TCK"
    }
    set root [regsub -all {[][{}().+*?^$|\\]} $engine {\\&}]
    set descendants [get_cells -quiet -hierarchical -regexp [format {^%s/.*$} $root]]
    # Reconstitute object collections before -of_objects. C-pin IS_INVERTED is
    # the mapped edge property; do not query the historical cell-level name.
    set descendants [get_cells -quiet $descendants]
    set negative_cells {}
    foreach pin [get_pins -quiet -of_objects $descendants -filter {REF_PIN_NAME == C}] {
        if {[lsearch -exact [get_clocks -quiet -of_objects $pin] valence_bscan_tck] >= 0 &&
            [get_property IS_INVERTED $pin] == 1} {
            set owner [get_cells -quiet -of_objects $pin]
            if {[llength $owner] != 1} {error "BSCAN negative-TCK clock owner is ambiguous: $pin"}
            lappend negative_cells {*}$owner
        }
    }
    if {[llength $negative_cells] == 0 || [lsearch -exact $negative_cells $sticky] < 0} {
        error "BSCAN negative-TCK fault sink collection is incomplete"
    }
    set negative_cells [get_cells -quiet [lsort -unique $negative_cells]]
    set targets [get_pins -quiet -of_objects $negative_cells -filter {REF_PIN_NAME == D || REF_PIN_NAME == CE}]
    if {[llength $targets] < [llength $negative_cells]} {error "BSCAN negative-TCK D/CE sinks missing"}
    set cone [all_fanin -flat -to $targets]
    if {[lsearch -exact $cone "$raw/Q"] >= 0} {
        error "Raw UPDATE overrun feeds negative-TCK D/CE cone"
    }
    set sticky_targets [get_pins -quiet -of_objects [get_cells -quiet $sticky] -filter {REF_PIN_NAME == D || REF_PIN_NAME == CE}]
    if {[lsearch -exact [all_fanin -flat -to $sticky_targets] "$sample/Q"] < 0} {
        error "BSCAN sampled fault does not feed sticky error"
    }
    set result [dict create fault_sample $sample negative_tck_registers [llength $negative_cells] \
        negative_tck_d_ce_pins [llength $targets] raw_overrun_cones 0]
    puts "BSCAN_PHASED_FAULT $result functional_reset_fence=verified"
    return $result
}
proc valence_bscan_bundle {engine source destination count} {
    set src [valence_bscan_bank $engine $source $count]
    set dst [valence_bscan_bank $engine $destination $count]
    set launch [get_pins -quiet -of_objects $src -filter {REF_PIN_NAME == C}]
    set capture [get_pins -quiet -of_objects $dst -filter {REF_PIN_NAME == D}]
    if {[llength $launch] != $count || [llength $capture] != $count} {error "BSCAN bundle pin count mismatch"}
    set_max_delay -datapath_only 8.000 -from $launch -to $capture
    set_bus_skew 8.000 -from $launch -to $capture
    puts "BSCAN_HELD_BUNDLE source=$source destination=$destination bits=$count max_ns=8 skew_ns=8"
}
proc valence_reapply_bscan_cdc {primitive engine fabric_clock} {
    valence_bscan_qualifiers $primitive $engine
    valence_bscan_phase_handoff $engine
    valence_bscan_fault_phase $engine
    foreach {tail count} {update_sync 2 bridge/request_sync 2 bridge/response_sync 2} {
        valence_bscan_bank $engine $tail $count 1
    }
    foreach {tail inverted} {source_release 1 update_release 0 hard_release 0 bridge/source_release 1 bridge/dest_release 0} {
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
