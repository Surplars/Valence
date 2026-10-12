# Executable selector/topology/exception-scope mocks. Never Vivado/netlist/STA proof.
source [file join [file dirname [info script]] ../../fpga/next/bscan_timing.tcl]
set primitive chip/bscan/enabled.user_scan
set engine chip/bscan/enabled.transport
set props {};set pins {};set nets {};set pin_net {};set cells {};set clocks {};set clock_pins {}
set calls {};set bad_cone {};set bad_reset 0;set cases 0
set bad_handoff {};set bad_functional_reset 0;set bad_hard_feedback 0
proc addcell {name ref {inverted 0} {clock valence_bscan_tck}} {
    global props cells pins clock_pins
    lappend cells $name
    dict set props $name [dict create NAME $name REF_NAME $ref ASYNC_REG TRUE]
    foreach {pin direction} {C IN D IN CLR IN CE IN Q OUT} {dict set pins $name/$pin $direction}
    dict set props $name/C [dict create IS_INVERTED $inverted]
    dict set clock_pins $name/C $clock
}
proc connect {driver receivers} {
    global pin_net nets
    set net net:$driver
    dict set nets $net [concat [list $driver] $receivers]
    foreach pin [concat [list $driver] $receivers] {dict set pin_net $pin $net}
}
addcell $primitive BSCANE2;dict set props $primitive JTAG_CHAIN 2
addcell $engine ValenceBscanUserTransport
addcell vcc VCC;dict set pins vcc/P OUT
addcell raw_reset LUT1;dict set pins raw_reset/O OUT
addcell tckbuf BUFG;dict set pins tckbuf/O OUT
addcell fabricbuf BUFG;dict set pins fabricbuf/O OUT
foreach pin {INTERNAL_TCK TCK DRCK UPDATE SEL INTERNAL_TDI INTERNAL_TMS} {dict set pins $primitive/$pin OUT}
dict set props design [dict create PART xczu15eg-ffvb1156-2-i]
dict set props fabric [dict create NAME fabric PERIOD 10.0 WAVEFORM {0 5}]
set clocks {fabric}
foreach {tail count invert} {source_release 3 1 update_release 3 0 hard_release 3 0 handoff_frame 64 0 handoff_length_ok 1 0 handoff_toggle 1 0 shift_frame 64 0 shift_count 7 0 scan_captured 1 0 hard_reset 1 1 bridge/source_release 3 1 bridge/dest_release 3 0 update_sync 2 1 bridge/request_sync 2 0 bridge/response_sync 2 1 update_frame 64 0 update_length_ok 1 0 update_toggle 1 0 update_overrun 1 0 update_selected 1 0 update_ack 1 0 bridge/request_toggle 1 1 bridge/response_toggle 1 0 bridge/request_held 41 1 bridge/dest_request 41 0 bridge/response_held 34 0 bridge/s_rsp_payload 34 1} {
    for {set i 0} {$i<$count} {incr i} {
        set cell [expr {$count==1?"${engine}/${tail}_reg":[format {%s/%s_reg[%d]} $engine $tail $i]}]
        set clock [expr {$tail in {update_frame update_length_ok update_toggle update_overrun}?"valence_bscan_update":"valence_bscan_tck"}]
        if {$tail in {shift_frame shift_count scan_captured}} {set clock valence_bscan_drck}
        if {$tail eq "bridge/dest_release"} {set clock fabric}
        addcell $cell FDCE $invert $clock
    }
}
set clocks_tck {};set clocks_fabric {};set reset_pins {};set first_pins {}
foreach tail {source_release update_release hard_release bridge/source_release bridge/dest_release} {
    for {set i 0} {$i<3} {incr i} {
        set c [format {%s/%s_reg[%d]} $engine $tail $i]
        if {$tail eq "bridge/dest_release"} {lappend clocks_fabric $c/C} else {lappend clocks_tck $c/C}
        lappend reset_pins $c/CLR
        if {$i==0} {lappend first_pins $c/D} else {
            set previous [format {%s/%s_reg[%d]} $engine $tail [expr {$i-1}]]
            connect $previous/Q [list $c/D]
        }
    }
}
connect tckbuf/O $clocks_tck;connect fabricbuf/O $clocks_fabric
connect raw_reset/O $reset_pins;connect vcc/P $first_pins
foreach {tail source count} {handoff_frame update_frame 64 handoff_length_ok update_length_ok 1 handoff_toggle update_toggle 1} {
    for {set i 0} {$i<$count} {incr i} {
        set from [expr {$count==1 ? "${engine}/${source}_reg" : [format {%s/%s_reg[%d]} $engine $source $i]}]
        set to [expr {$count==1 ? "${engine}/${tail}_reg" : [format {%s/%s_reg[%d]} $engine $tail $i]}]
        connect $from/Q [list $to/D]
    }
}
connect $engine/handoff_toggle_reg/Q [list [format {%s/update_sync_reg[0]/D} $engine]]
proc current_design {} {return design}
proc get_cells {args} {
    global props cells
    if {[lsearch -exact $args -filter]>=0} {
        set result {};foreach c $cells {if {[dict get $props $c REF_NAME] eq "BSCANE2"} {lappend result $c}};return $result
    }
    if {[lsearch -exact $args -of_objects]>=0} {return [list [file dirname [lindex $args end]]]}
    set pattern [lindex $args end]
    if {[lsearch -exact $args -regexp]>=0} {
        set result {};foreach c $cells {if {[regexp $pattern $c]} {lappend result $c}};return $result
    }
    set result {}
    foreach name $pattern {if {[lsearch -exact $cells $name]>=0} {lappend result $name}}
    return $result
}
proc get_pins {args} {
    global pins nets
    set index [lsearch -exact $args -of_objects]
    if {$index>=0} {
        set objects [lindex $args [expr {$index+1}]];set result {}
        foreach object $objects {
            if {[dict exists $nets $object]} {lappend result {*}[dict get $nets $object]} else {
                foreach pin [dict keys $pins] {if {[file dirname $pin] eq $object} {lappend result $pin}}
            }
        }
        set filter_index [lsearch -exact $args -filter]
        if {$filter_index>=0} {
            set filter [lindex $args [expr {$filter_index+1}]];set filtered {}
            foreach p $result {
                if {[regexp {DIRECTION == (\w+)} $filter -> d]} {
                    if {[dict get $pins $p] eq $d} {lappend filtered $p}
                } elseif {[regexp {REF_PIN_NAME == D \|\| REF_PIN_NAME == CE} $filter]} {
                    if {[file tail $p] in {D CE}} {lappend filtered $p}
                } elseif {[regexp {REF_PIN_NAME == (\w+)} $filter -> name]} {
                    if {[file tail $p] eq $name} {lappend filtered $p}
                } else {error "unhandled pin filter: $filter"}
            }
            set result $filtered
        }
        return $result
    }
    set name [lindex $args end]
    if {[dict exists $pins $name]} {return [list $name]};return {}
}
proc get_nets {args} {
    global pin_net
    if {[lsearch -exact $args -segments]>=0} {return [lindex $args end]}
    set pin [lindex $args end]
    if {[dict exists $pin_net $pin]} {return [list [dict get $pin_net $pin]]};return {}
}
proc get_clocks {args} {
    global clocks clock_pins primitive
    if {[lsearch -exact $args -of_objects]>=0} {
        set pin [lindex $args end]
        if {[dict exists $clock_pins $pin]} {return [list [dict get $clock_pins $pin]]}
        foreach {p c} {TCK valence_bscan_tck DRCK valence_bscan_drck UPDATE valence_bscan_update} {
            if {$pin eq "$primitive/$p" && [lsearch -exact $clocks $c]>=0} {return [list $c]}
        }
        return {}
    }
    set result {};foreach n [lindex $args end] {if {[lsearch -exact $clocks $n]>=0} {lappend result $n}};return $result
}
proc get_debug_cores {args} {return {}}
proc list_property {obj} {global props;return [dict keys [dict get $props $obj]]}
proc get_property {name obj} {global props;return [dict get $props $obj $name]}
proc all_fanin {args} {
    global engine bad_cone bad_reset bad_handoff bad_functional_reset bad_hard_feedback
    set targets [lindex $args end]
    if {[lsearch -exact $args -startpoints_only]>=0} {
        if {$bad_reset} {return raw_reset/O}
        set release update_release
        if {[regexp {/(handoff_frame|handoff_length_ok|handoff_toggle|shift_frame|shift_count|scan_captured)_reg} $targets]} {
            set release source_release
            if {$bad_functional_reset} {return raw_reset/O}
        }
        if {$targets eq "$engine/hard_reset_reg/CLR"} {set release hard_release}
        return [list [format {%s/%s_reg[2]/C} $engine $release]]
    }
    if {$targets eq [format {%s/hard_release_reg[0]/CLR} $engine]} {
        if {$bad_hard_feedback} {return "$engine/hard_reset_reg/Q"}
        return raw_reset/O
    }
    if {[string first /bridge/request_held_reg $targets]>=0} {
        return [concat [list [format {%s/handoff_frame_reg[0]/Q} $engine]] $bad_handoff]
    }
    return [concat [list $engine/update_selected_reg/Q $engine/update_ack_reg/Q] $bad_cone]
}
proc create_clock {args} {
    global clocks props calls
    set n [lindex $args [expr {[lsearch -exact $args -name]+1}]]
    set period [lindex $args [expr {[lsearch -exact $args -period]+1}]]
    set waveform [lindex $args [expr {[lsearch -exact $args -waveform]+1}]]
    lappend clocks $n;dict set props $n [dict create NAME $n PERIOD $period WAVEFORM $waveform]
    lappend calls [list create_clock {*}$args]
}
proc create_generated_clock {args} {
    global clocks props calls primitive
    set n [lindex $args [expr {[lsearch -exact $args -name]+1}]]
    set source [lindex $args [expr {[lsearch -exact $args -source]+1}]]
    if {$source ne "$primitive/INTERNAL_TCK"} {error "generated clock source mismatch"}
    set period [dict get $props valence_bscan_tck PERIOD]
    set wave [dict get $props valence_bscan_tck WAVEFORM]
    if {[lsearch -exact $args -edges]>=0} {
        if {[lindex $args [expr {[lsearch -exact $args -edges]+1}]] ne {2 3 4}} {error "generated UPDATE edge envelope changed"}
        set wave [list [lindex $wave 1] [expr {[lindex $wave 0]+$period}]]
    } elseif {[lindex $args [expr {[lsearch -exact $args -divide_by]+1}]] != 1} {error "DRCK divide changed"}
    lappend clocks $n;dict set props $n [dict create NAME $n PERIOD $period WAVEFORM $wave]
    lappend calls [list create_generated_clock {*}$args]
}
foreach command {set_false_path set_max_delay set_bus_skew set_clock_uncertainty set_input_delay} {
    proc $command {args} {global calls;lappend calls [list [lindex [info level 0] 0] {*}$args]}
}
proc reject {body anchor} {
    global cases
    if {![catch {uplevel 1 $body} value] || [string first $anchor $value]<0} {error "Expected rejection '$anchor', got '$value'"}
    incr cases
}
valence_apply_bscan_timing $primitive $engine fabric zu15eg-user2-tck50-positive-v1
incr cases
set false_pins {};set maxes 0;set skews 0;set uncertainty 0
foreach call $calls {
    switch -- [lindex $call 0] {
        set_false_path {lappend false_pins {*}[lindex $call 2]}
        set_max_delay {
            incr maxes
            if {[lindex $call 1] ne "-datapath_only" || [lindex $call 2] != 8.0} {error "mailbox max-delay changed"}
        }
        set_bus_skew {
            incr skews
            if {[lindex $call 1] != 8.0} {error "held-bundle skew changed"}
        }
        set_input_delay {
            if {[lsearch -exact $call -clock_fall]<0 || [lindex $call 2] ne "valence_bscan_tck"} {error "adapter reference changed"}
            set expected [expr {[lsearch -exact $call -max]>=0 ? 15.0 : 0.0}]
            if {[lindex $call end-1] != $expected} {error "adapter delay changed"}
        }
        set_clock_uncertainty {
            incr uncertainty
            if {[lindex $call 2] != 0.100} {error "related clock uncertainty changed"}
            if {[llength [lindex $call 4]]!=3 || [llength [lindex $call 6]]!=3} {error "uncertainty misses related pairs"}
        }
    }
}
if {[llength $false_pins]!=15 || [llength [lsort -unique $false_pins]]!=15 || $maxes!=4 || $skews!=2 || $uncertainty!=2} {error "exception scope/count mismatch"}
foreach pin $false_pins {if {![regexp {/(source_release|update_release|hard_release|dest_release)_reg\[[0-2]\]/CLR$} $pin]} {error "functional exception leaked: $pin"}}
incr cases
reject {valence_apply_bscan_timing $primitive $engine fabric zu15eg-user2-tck50-positive-v1} "already exists"
reject {valence_apply_bscan_timing $primitive $engine fabric arbitrary} "profile required"
dict set props design PART xczu9eg
reject {valence_apply_bscan_timing $primitive $engine fabric zu15eg-user2-tck50-positive-v1} "part/profile"
dict set props design PART xczu15eg-ffvb1156-2-i
# Full released industrial part is accepted. A historical report's short label
# is not proof that get_property PART normalizes away temperature grade.
foreach wrong_part {xczu15eg-ffvb1156-2 xczu15eg-ffvb1156-2-e xczu15eg-ffvb1156-1-i xczu15eg-ffvc1760-2-i} {
    dict set props design PART $wrong_part
    reject {valence_apply_bscan_timing $primitive $engine fabric zu15eg-user2-tck50-positive-v1} "part/profile"
}
dict set props design PART xczu15eg-ffvb1156-2-i
foreach pin [list "$primitive/SEL" [format {%s/source_release_reg[2]/Q} $engine] "$engine/update_seen_reg/Q"] {
    set bad_cone [list $pin]
    reject {valence_reapply_bscan_cdc $primitive $engine fabric} "Live same-edge"
}
set bad_cone {};set bad_reset 1
reject {valence_reapply_bscan_cdc $primitive $engine fabric} "reset bypasses"
set bad_reset 0
set selected $engine/update_selected_reg
set saved [dict get $props $selected/C IS_INVERTED];dict set props $selected/C IS_INVERTED 1
reject {valence_reapply_bscan_cdc $primitive $engine fabric} "positive-TCK"
dict set props $selected/C IS_INVERTED $saved
dict set clock_pins $selected/C valence_bscan_update
reject {valence_reapply_bscan_cdc $primitive $engine fabric} "qualifier clock"
dict set clock_pins $selected/C valence_bscan_tck
set release [format {%s/update_release_reg[0]} $engine]
dict set props $release ASYNC_REG FALSE
reject {valence_reapply_bscan_cdc $primitive $engine fabric} "ASYNC_REG"
dict set props $release ASYNC_REG TRUE
dict set props $release/C IS_INVERTED 1
reject {valence_reapply_bscan_cdc $primitive $engine fabric} "type/edge"
dict set props $release/C IS_INVERTED 0
dict set clock_pins $release/C fabric
reject {valence_reapply_bscan_cdc $primitive $engine fabric} "release clock domain"
dict set clock_pins $release/C valence_bscan_tck
set first_net [dict get $pin_net $release/D];dict set pin_net $release/D net:raw_reset/O
reject {valence_reapply_bscan_cdc $primitive $engine fabric} "constant one"
dict set pin_net $release/D $first_net
set second [format {%s/update_release_reg[1]} $engine]
set oldnet [dict get $pin_net $second/D];dict set pin_net $second/D net:vcc/P
reject {valence_reapply_bscan_cdc $primitive $engine fabric} "chain broken"
dict set pin_net $second/D $oldnet
set qnet [dict get $pin_net $release/Q];set saved [dict get $nets $qnet]
dict set nets $qnet [concat $saved [list $selected/D]]
reject {valence_reapply_bscan_cdc $primitive $engine fabric} "functional fanout"
dict set nets $qnet $saved
set saved $cells;set cells [lreplace $cells [lsearch -exact $cells $release] [lsearch -exact $cells $release]]
reject {valence_reapply_bscan_cdc $primitive $engine fabric} "shape requires"
set cells $saved
reject {valence_bscan_bank chip/* update_release 3} "Exact"
# Reapplication checks everything again, then emits only the same narrow CDC
# constraints; it must not create clocks or silently broaden any exception.
set handoff $engine/handoff_toggle_reg
set saved [dict get $props $handoff/C IS_INVERTED];dict set props $handoff/C IS_INVERTED 1
reject {valence_reapply_bscan_cdc $primitive $engine fabric} "handoff must remain positive"
dict set props $handoff/C IS_INVERTED $saved
set saved [dict get $pin_net $handoff/D];dict set pin_net $handoff/D net:raw_reset/O
reject {valence_reapply_bscan_cdc $primitive $engine fabric} "handoff input bypass"
dict set pin_net $handoff/D $saved
set first [format {%s/update_sync_reg[0]/D} $engine]
set saved [dict get $pin_net $first];dict set pin_net $first net:$engine/update_toggle_reg/Q
reject {valence_reapply_bscan_cdc $primitive $engine fabric} "notification bypasses"
dict set pin_net $first $saved
set bad_handoff [list [format {%s/update_frame_reg[27]/Q} $engine]]
reject {valence_reapply_bscan_cdc $primitive $engine fabric} "request bypasses"
set bad_handoff {};set bad_functional_reset 1
reject {valence_reapply_bscan_cdc $primitive $engine fabric} "functional reset bypasses"
set bad_functional_reset 0;set bad_hard_feedback 1
reject {valence_reapply_bscan_cdc $primitive $engine fabric} "work-reset feedback"
set bad_hard_feedback 0
set calls {};valence_reapply_bscan_cdc $primitive $engine fabric
foreach call $calls {if {[lindex $call 0] in {create_clock create_generated_clock}} {error "CDC reapplication recreated clock"}}
incr cases
puts "BSCAN_TIMING_MOCK_PASS cases=$cases reset_clr_pins=15 mailbox_maxes=4 held_skews=2 physical_signoff=0"
