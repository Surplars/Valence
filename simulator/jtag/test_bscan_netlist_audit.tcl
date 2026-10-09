# Read-only-query mocks; no Vivado, DCP, FPGA or timing proof.
source [file join [file dirname [info script]] ../../fpga/next/audit_bscan_netlist.tcl]
set primitive chip/bscan/enabled/user_scan
set engine chip/bscan/enabled/transport
set cells [list $primitive $engine]
set props [dict create $primitive [dict create NAME $primitive REF_NAME BSCANE2 JTAG_CHAIN 2] \
    $engine [dict create NAME $engine REF_NAME ValenceBscanUserTransport] \
    dbg_hub [dict create C_USER_SCAN_CHAIN 1]]
foreach {bank count} {source_release 3 update_sync 2 bridge/source_release 3 bridge/dest_release 3 \
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
set pins [list $primitive/TCK $primitive/DRCK $primitive/UPDATE]
set missing_clock 0
proc get_cells {args} {
    global cells props primitive
    if {[lsearch -exact $args -filter]>=0} {return [list $primitive]}
    set pattern [lindex $args end]
    if {[lsearch -exact $args -regexp]>=0} {
        set result {};foreach c $cells {if {[regexp $pattern $c]} {lappend result $c}};return $result
    }
    if {[lsearch -exact $cells $pattern]>=0} {return [list $pattern]};return {}
}
proc get_pins {args} {
    global pins
    if {[lsearch -exact $args -of_objects]>=0} {return $pins}
    set name [lindex $args end]
    if {[lsearch -exact $pins $name]>=0} {return [list $name]};return {}
}
proc get_clocks {args} {
    global missing_clock
    if {[lsearch -exact $args -of_objects]>=0} {
        if {$missing_clock} {return {}}
        return [list [string tolower [file tail [lindex $args end]]]]
    }
    if {[lindex $args end] eq "fabric"} {return fabric};return {}
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
puts "BSCAN_NETLIST_AUDIT_MOCK_PASS cases=11 physical_signoff=0"
