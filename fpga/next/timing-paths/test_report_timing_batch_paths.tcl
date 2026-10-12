# tclsh-only API contract mock. No Vivado or netlist qualification.
if {$argc != 2} {error "Expected COLLECTOR_TCL FRESH_TEST_ROOT"}
lassign $argv collector testroot
set ::valence_timing_batch_library_only 1
source $collector
file mkdir $testroot
set checkpoint [file join $testroot {checkpoint with spaces.dcp}]
close [open $checkpoint w]
set soc u_soc
set bscan u_debug/enabled.transport
set mac u_rgmii
set roots [list $soc $bscan $mac]
set rows [list \
    [list {u_soc/platform/core/core/core/backend/pendingStoreProof/descriptor_reg[0]} {D CE CLR}] \
    [list {u_soc/platform/core/core/core/backend/pendingStoreProof/translatedValid_reg} {D CE CLR}] \
    [list {u_soc/platform/core/core/core/backend/stagedMemoryAddress_reg[63]} {D CE}] \
    [list {u_soc/platform/core/core/core/backend/executionStages0/payload_reg[30]} {D CE CLR}] \
    [list {u_soc/platform/core/core/core/backend/canonicalStoreTracker/certified_reg} {D CLR}] \
    [list {u_soc/platform/core/adapter/certificateValid_reg} {D CLR}] \
    [list {u_soc/platform/manager/bridge/slots1/payloadBanks5/ram/RAMA} {WE D A0}] \
    [list {u_soc/platform/core/core/core/fetchPacket/rawCursor_reg[3]} {D CE}] \
    [list {u_soc/platform/frontend/suppliedPackets_window/payload_reg[0]} {D CE}] \
    [list {u_debug/enabled.transport/handoff_frame_reg[0]} {D CE CLR}] \
    [list {u_debug/enabled.transport/bridge/request_held_reg[0]} {D CE CLR}] \
    [list {u_rgmii/low_symbol_reg[2]} {D CE CLR}] \
    [list {u_rgmii/pad_release.pad_release_reset_reg} {D PRE}] \
    [list {u_rgmii/delay_control_REPLICATED_0} {RST}]]
proc require {condition message} {if {![uplevel 1 [list expr $condition]]} {error $message}}
proc readfile {path} {set f [open $path];set data [read $f];close $f;return $data}
proc reset_mock {} {
    set ::cells [dict create]
    foreach row $::rows {lassign $row cell refs;dict set ::cells $cell $refs}
    set ::duplicate_root 0
    set ::empty_paths 0
    set ::missing_clock_property 0
    set ::reject_redirect 0
    set ::timing_calls {}
    set ::query_calls {}
    set ::open_calls 0
    set ::close_calls 0
}
proc get_cells {args} {
    if {[lsearch -exact $args -regexp] >= 0} {
        set i [lsearch -exact $args -regexp]
        set regex [lindex $args [expr {$i+1}]]
        require {[lrange $args 0 2] eq {-quiet -hierarchical -regexp}} "Unexpected cell-query syntax"
        require {[lrange $args end-1 end] eq {-filter {IS_PRIMITIVE == 1}}} "Expected leaf-only query"
        set found {}
        dict for {cell refs} $::cells {if {[regexp $regex $cell]} {lappend found $cell}}
        return $found
    }
    require {[llength $args] == 2 && [lindex $args 0] eq "-quiet"} "Unexpected exact-root query"
    set name [lindex $args 1]
    if {$::duplicate_root && $name eq $::bscan} {return [list $name ${name}_unexpected]}
    if {[lsearch -exact $::roots $name] >= 0} {return [list $name]}
    return {}
}
proc get_pins {args} {
    require {[llength $args] == 3 && [lrange $args 0 1] eq {-quiet -of_objects}} "Bad pin-query syntax"
    set result {}
    foreach cell [lindex $args 2] {foreach ref [dict get $::cells $cell] {lappend result $cell/$ref}}
    return $result
}
proc list_property {object} {
    if {[string match mock_path_* $object]} {
        set fields {STARTPOINT_PIN ENDPOINT_PIN STARTPOINT_CLOCK ENDPOINT_CLOCK SLACK REQUIREMENT DATAPATH_DELAY LOGIC_LEVELS}
        if {$::missing_clock_property} {return [lsearch -all -inline -not -exact $fields ENDPOINT_CLOCK]}
        return $fields
    }
    return {NAME REF_NAME DIRECTION REF_PIN_NAME PART}
}
proc get_property {key object} {
    if {[llength $object] == 1} {set object [lindex $object 0]}
    switch -- $key {
        NAME {return $object}
        REF_NAME {return FDRE}
        DIRECTION {return IN}
        REF_PIN_NAME {return [lindex [split $object /] end]}
        PART {return mock_part}
        STARTPOINT_PIN {return mock_launch/Q}
        ENDPOINT_PIN {return $::path_endpoint}
        STARTPOINT_CLOCK {return mock_start_clock}
        ENDPOINT_CLOCK {return mock_end_clock}
        SLACK {return -0.123}
        REQUIREMENT {return 10.0}
        DATAPATH_DELAY {return 10.123}
        LOGIC_LEVELS {return 4}
        default {error "Unknown property: $key"}
    }
}
proc open_checkpoint {path} {require {[file isfile $path]} "Checkpoint split at spaces";incr ::open_calls}
proc close_design {} {incr ::close_calls}
proc version {arg} {require {$arg eq "-short"} "Bad version call";return MOCK_ONLY}
proc current_design {} {return mock_design}
proc get_timing_paths {args} {
    require {[llength $args] == 8} "Bad timing query arity"
    require {[lindex $args 0] eq "-to" && [lindex $args 2] eq "-delay_type"} "Bad timing query flags"
    require {[lindex $args 3] in {max min}} "Missing max/min"
    require {[lrange $args 4 end] eq {-max_paths 7 -nworst 5}} "Family budget changed"
    lappend ::query_calls $args
    set ::path_endpoint [lindex [lindex $args 1] 0]
    if {$::empty_paths} {return {}}
    return [list mock_path_[llength $::query_calls]]
}
proc report_timing {args} {
    require {[llength $args] == 12} "Bad detailed timing report arity"
    require {[lrange $args end-3 end] eq {-path_type full_clock_expanded -input_pins -nets}} "Missing clock/cell/net detail"
    require {[llength [lindex $args 1]] > 0} "Lost endpoint collection"
    lappend ::timing_calls $args
    return [list MOCK_DETAILED_TIMING {*}$args]
}
foreach command {report_timing_summary report_clock_interaction report_exceptions report_cdc} {
    proc $command {args} {return [list MOCK_GLOBAL_REPORT {*}$args]}
}
proc redirect {args} {
    require {[llength $args] == 3 && [lindex $args 0] eq "-file"} "Invalid redirect syntax"
    lassign $args flag destination script
    require {[llength $script] > 0} "Empty redirect command"
    if {$::reject_redirect} {error MOCK_REDIRECT_REJECTION}
    set result [uplevel 1 $script]
    set f [open $destination w];puts $f $result;close $f
}
proc run_case {name} {
    set out [file join $::testroot $name]
    set issues [valence_timing_batch::collect $::checkpoint $out $::soc $::bscan $::mac 7]
    require {$::open_calls == 1 && $::close_calls == 1} "Checkpoint lifecycle mismatch"
    return [list $issues $out [readfile [file join $out coverage.txt]]]
}
set passed {}
reset_mock
lassign [run_case {hit and spaces}] issues out facts
require {$issues == 0} "Positive collection has issues"
require {[llength $::timing_calls] == 32 && [llength $::query_calls] == 32} "Not all 16 independent family max/min reports executed"
require {[string first MULTIPLE_FAMILY_CELLS_REVIEW $facts] >= 0} "Multiple family matches silent"
require {[string first mock_start_clock $facts] >= 0 && [string first mock_end_clock $facts] >= 0} "Missing start/end clocks"
require {[string first full_clock_expanded [readfile [file join $out proof_max.rpt]]] >= 0} "Redirect did not execute detailed report command"
require {[string first NOT_TIMING_OR_CDC_PASS $facts] >= 0} "Collector overclaimed signoff"
lappend passed hit_multiple_family_spaces_and_real_tcl_redirect
require {[catch {valence_timing_batch::collect $checkpoint $out $soc $bscan $mac 7}]} "Overwrote existing evidence"
lappend passed existing_output_rejected
reset_mock
dict unset ::cells {u_soc/platform/core/core/core/backend/executionStages0/payload_reg[30]}
lassign [run_case missing_endpoint] issues out facts
require {$issues > 0 && [string first {MISSING_OR_CHANGED_CELLS rank51_payload30} $facts] >= 0} "Missing endpoint not recorded"
lappend passed missing_endpoint
reset_mock
dict set ::cells {u_soc/platform/manager/bridge/slots1/payloadBanks5/ram/RAMA} {D A0}
lassign [run_case changed_pin] issues out facts
require {$issues > 0 && [string first {MISSING_OR_CHANGED_ENDPOINT_PINS manager_we} $facts] >= 0} "Changed pin not recorded"
lappend passed changed_pin
reset_mock
set ::duplicate_root 1
lassign [run_case ambiguous_root] issues out facts
require {$issues > 0 && [string first AMBIGUOUS_OR_CHANGED_ROOT $facts] >= 0} "Ambiguous root silent"
lappend passed ambiguous_root
reset_mock
set ::roots [list $soc $mac]
lassign [run_case missing_root] issues out facts
require {$issues > 0 && [string first MISSING_OR_CHANGED_ROOT $facts] >= 0} "Missing root silent"
set ::roots [list $soc $bscan $mac]
lappend passed missing_root
reset_mock
set ::empty_paths 1
lassign [run_case missing_timed_path] issues out facts
require {$issues == 32 && [string first MISSING_TIMED_PATH $facts] >= 0} "Missing timing paths silent"
lappend passed missing_timed_path
reset_mock
set ::missing_clock_property 1
lassign [run_case missing_clock_property] issues out facts
require {$issues == 32 && [string first PROPERTY_UNAVAILABLE $facts] >= 0} "Unsupported path property silent"
lappend passed missing_clock_property
reset_mock
set ::reject_redirect 1
lassign [run_case redirect_error] issues out facts
require {$issues == 36 && [string first REPORT_ERROR $facts] >= 0} "Redirect failures silent"
lappend passed redirect_error
puts [list MOCK_CONTRACT_PASS TESTS [llength $passed] CASES $passed NOT_VIVADO_OR_NETLIST_QUALIFICATION]
