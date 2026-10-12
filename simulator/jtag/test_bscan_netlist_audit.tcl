# Read-only-query mocks; no Vivado, DCP, FPGA or timing proof.
source [file join [file dirname [info script]] ../../fpga/next/audit_bscan_netlist.tcl]
set primitive chip/bscan/enabled/user_scan
set engine chip/bscan/enabled/transport
set cells [list $primitive $engine]
set props [dict create $primitive [dict create NAME $primitive REF_NAME BSCANE2 JTAG_CHAIN 2] \
    $engine [dict create NAME $engine REF_NAME ValenceBscanUserTransport] \
    dbg_hub [dict create C_USER_SCAN_CHAIN 1]]
foreach {bank count} {source_release 3 update_release 3 hard_release 3 update_sync 2 bridge/source_release 3 bridge/dest_release 3 \
                     bridge/request_sync 2 bridge/response_sync 2} {
    for {set i 0} {$i<$count} {incr i} {
        set cell [format {%s/%s_reg[%d]} $engine $bank $i]
        lappend cells $cell
        dict set props $cell [dict create NAME $cell REF_NAME FDCE ASYNC_REG TRUE]
    }
}
foreach name {fabric tck drck update} {
    dict set props $name [dict create NAME $name PERIOD 20.0 WAVEFORM {0.0 10.0}]
}
foreach {tail edge clock} {fault_sample 0 valence_bscan_tck update_overrun 0 valence_bscan_update \
                         protocol_error 1 valence_bscan_tck unlisted_controller_state 1 valence_bscan_tck \
                         bridge/unlisted_state 1 valence_bscan_tck} {
    set cell $engine/${tail}_reg
    lappend cells $cell
    dict set props $cell [dict create NAME $cell REF_NAME FDCE ASYNC_REG FALSE]
}
lappend cells vcc
dict set props vcc [dict create NAME vcc REF_NAME VCC]
set pins [list $primitive/TCK $primitive/DRCK $primitive/UPDATE vcc/P]
set clock_pins {};set pin_direction [dict create vcc/P OUT]
foreach cell $cells {
    if {[dict get $props $cell REF_NAME] ne "FDCE"} {continue}
    set inverted [expr {[regexp {/(source_release|update_sync|response_sync|protocol_error|unlisted_controller_state|unlisted_state)_reg} $cell]}]
    set clock [expr {$cell eq "$engine/update_overrun_reg" ? "valence_bscan_update" : "valence_bscan_tck"}]
    foreach {pin direction} {C IN D IN CE IN CLR IN Q OUT} {
        lappend pins $cell/$pin
        dict set pin_direction $cell/$pin $direction
    }
    dict set props $cell/C [dict create IS_INVERTED $inverted]
    dict set clock_pins $cell/C $clock
}
set nets [dict create fault_data [list $engine/update_overrun_reg/Q $engine/fault_sample_reg/D] \
                     fault_enable [list vcc/P $engine/fault_sample_reg/CE]]
set pin_net [dict create $engine/fault_sample_reg/D fault_data $engine/fault_sample_reg/CE fault_enable]
set bad_fault_target {};set bad_fault_reset {};set missing_fault_merge 0
set constraint_calls 0
# Sourcing the shared query definitions must never apply a timing exception.
foreach command {set_false_path set_max_delay set_bus_skew create_clock create_generated_clock} {
    proc $command {args} {global constraint_calls;incr constraint_calls;error "Read-only collector applied timing"}
}
set missing_clock 0
proc get_cells {args} {
    global cells props primitive
    if {[lsearch -exact $args -filter]>=0} {return [list $primitive]}
    if {[lsearch -exact $args -of_objects]>=0} {return [list [file dirname [lindex $args end]]]}
    set pattern [lindex $args end]
    if {[lsearch -exact $args -regexp]>=0} {
        set result {};foreach c $cells {if {[regexp $pattern $c]} {lappend result $c}};return $result
    }
    set result {};foreach name $pattern {if {[lsearch -exact $cells $name]>=0} {lappend result $name}};return $result
}
proc get_pins {args} {
    global pins nets pin_direction
    set index [lsearch -exact $args -of_objects]
    if {$index>=0} {
        set result {}
        foreach object [lindex $args [expr {$index+1}]] {
            if {[dict exists $nets $object]} {lappend result {*}[dict get $nets $object]} else {
                foreach pin $pins {if {[file dirname $pin] eq $object} {lappend result $pin}}
            }
        }
        set index [lsearch -exact $args -filter]
        if {$index>=0} {
            set filter [lindex $args [expr {$index+1}]];set selected {}
            foreach pin $result {
                if {[regexp {DIRECTION == (\w+)} $filter -> direction]} {
                    if {[dict get $pin_direction $pin] eq $direction} {lappend selected $pin}
                } elseif {$filter eq {REF_PIN_NAME == D || REF_PIN_NAME == CE}} {
                    if {[file tail $pin] in {D CE}} {lappend selected $pin}
                } elseif {$filter eq {REF_PIN_NAME == C}} {
                    if {[file tail $pin] eq "C"} {lappend selected $pin}
                } else {error "Unexpected pin filter: $filter"}
            }
            set result $selected
        }
        return $result
    }
    set name [lindex $args end]
    if {[lsearch -exact $pins $name]>=0} {return [list $name]};return {}
}
proc get_clocks {args} {
    global missing_clock clock_pins
    if {[lsearch -exact $args -of_objects]>=0} {
        if {$missing_clock} {return {}}
        if {[dict exists $clock_pins [lindex $args end]]} {return [list [dict get $clock_pins [lindex $args end]]]}
        return [list [string tolower [file tail [lindex $args end]]]]
    }
    if {[lindex $args end] eq "fabric"} {return fabric};return {}
}
proc get_nets {args} {
    global pin_net
    if {[lsearch -exact $args -segments]>=0} {return [lindex $args end]}
    set pin [lindex $args end]
    if {[dict exists $pin_net $pin]} {return [list [dict get $pin_net $pin]]};return {}
}
proc all_fanin {args} {
    global engine bad_fault_target bad_fault_reset missing_fault_merge
    set targets [lindex $args end]
    if {[lsearch -exact $args -startpoints_only]>=0} {
        if {$bad_fault_reset ne ""} {return [list $bad_fault_reset]}
        return [list [format {%s/source_release_reg[2]/C} $engine]]
    }
    if {$bad_fault_target ne "" && [lsearch -exact $targets $bad_fault_target]>=0} {
        return [list $engine/update_overrun_reg/Q]
    }
    if {$missing_fault_merge} {return {}}
    return [list $engine/fault_sample_reg/Q]
}
proc get_debug_cores {args} {return dbg_hub}
proc list_property {object} {global props;return [dict keys [dict get $props $object]]}
proc get_property {name object} {global props;return [dict get $props $object $name]}
set reports {}
foreach name {report_cdc report_clock_interaction report_exceptions report_timing_summary} {
    proc $name {args} {global reports;lappend reports [lindex [info level 0] 0]}
}
proc reject {body anchor} {
    if {![catch {uplevel 1 $body} value] || [string first $anchor $value]<0} {
        error "Expected rejection '$anchor', got '$value'"
    }
}
set out [file join [pwd] build/jtag/netlist-audit-mock-[pid]-[clock clicks]]
valence_collect_bscan_netlist $primitive $engine fabric $out
if {[llength $reports]!=4} {error "report collection incomplete"}
if {$constraint_calls!=0} {error "collector changed timing"}
reject {valence_collect_bscan_netlist $primitive $engine fabric $out} "fresh"
set fresh $out-next
set missing_clock 1
reject {valence_collect_bscan_netlist $primitive $engine fabric $fresh} "Unconstrained"
set missing_clock 0
dict set props dbg_hub C_USER_SCAN_CHAIN 2
reject {valence_collect_bscan_netlist $primitive $engine fabric $fresh} "collision"
dict set props dbg_hub C_USER_SCAN_CHAIN 1
set sync [format {%s/update_sync_reg[0]} $engine]
dict set props $sync ASYNC_REG FALSE
reject {valence_collect_bscan_netlist $primitive $engine fabric $fresh} "ASYNC_REG"
dict set props $sync ASYNC_REG TRUE
set old $cells;set cells [lreplace $cells [lsearch -exact $cells $sync] [lsearch -exact $cells $sync]]
reject {valence_collect_bscan_netlist $primitive $engine fabric $fresh} "shape mismatch"
set cells $old
reject {valence_bscan_exact get_cells chip/*} "Exact"
reject {valence_bscan_sync_bank {chip/a[0]} update_sync 2} "Exact"
# Report collection must independently run the full cone and phase audit.
set fault_cases 0
foreach cell [list $engine/protocol_error_reg $engine/unlisted_controller_state_reg $engine/bridge/unlisted_state_reg] {
    foreach pin {D CE} {
        set bad_fault_target $cell/$pin
        reject {valence_collect_bscan_netlist $primitive $engine fabric $fresh} "Raw UPDATE overrun feeds negative-TCK D/CE"
        incr fault_cases
    }
}
set bad_fault_target {}
set sample $engine/fault_sample_reg
dict set props $sample/C IS_INVERTED 1
reject {valence_collect_bscan_netlist $primitive $engine fabric $fresh} "fault sample must remain positive"
dict set props $sample/C IS_INVERTED 0
dict set clock_pins $sample/C valence_bscan_update
reject {valence_collect_bscan_netlist $primitive $engine fabric $fresh} "fault sample must remain positive"
dict set clock_pins $sample/C valence_bscan_tck
set saved [dict get $pin_net $sample/D];dict set pin_net $sample/D fault_enable
reject {valence_collect_bscan_netlist $primitive $engine fabric $fresh} "fault sample input"
dict set pin_net $sample/D $saved
set saved [dict get $pin_net $sample/CE];dict set pin_net $sample/CE fault_data
reject {valence_collect_bscan_netlist $primitive $engine fabric $fresh} "capture every positive"
dict set pin_net $sample/CE $saved
foreach wrong_origin [list raw_reset/O [format {%s/update_release_reg[2]/C} $engine] \
                          [format {%s/source_release_reg[2]/Q} $engine]] {
    set bad_fault_reset $wrong_origin
    reject {valence_collect_bscan_netlist $primitive $engine fabric $fresh} "fault sample reset bypasses"
    incr fault_cases
}
set bad_fault_reset {};set missing_fault_merge 1
reject {valence_collect_bscan_netlist $primitive $engine fabric $fresh} "does not feed sticky error"
set missing_fault_merge 0
incr fault_cases 5
file delete -force $out
# Repeat the actual collection with Vivado's dotted generate-block spelling.
set rename [list /enabled/ /enabled.]
set new_props {};foreach {key value} $props {
    if {[dict exists $value NAME]} {dict set value NAME [string map $rename [dict get $value NAME]]}
    dict set new_props [string map $rename $key] $value
}
set props $new_props
set cells [lmap c $cells {string map $rename $c}]
set pins [lmap p $pins {string map $rename $p}]
foreach variable {clock_pins pin_direction pin_net} {
    set updated {};foreach {key value} [set $variable] {dict set updated [string map $rename $key] $value}
    set $variable $updated
}
set updated {};foreach {key values} $nets {dict set updated $key [lmap value $values {string map $rename $value}]}
set nets $updated
set primitive [string map $rename $primitive];set engine [string map $rename $engine]
set out $out-dotted
valence_collect_bscan_netlist $primitive $engine fabric $out
file delete -force $out
set wrong chip/different/transport
lappend cells $wrong;dict set props $wrong [dict create NAME $wrong REF_NAME ValenceBscanUserTransport]
reject {valence_collect_bscan_netlist $primitive $wrong fabric $out} "siblings"
# A literal dot cannot accidentally match a different hierarchy character.
set saved $cells;set cells [lmap c $cells {string map {.transport Xtransport} $c}]
reject {valence_bscan_sync_bank $engine update_sync 2} "shape mismatch"
set cells $saved
if {$constraint_calls!=0} {error "collector changed timing"}
puts "BSCAN_NETLIST_AUDIT_MOCK_PASS cases=[expr {11+$fault_cases}] fault_controls=$fault_cases constraint_calls=$constraint_calls physical_signoff=0"
