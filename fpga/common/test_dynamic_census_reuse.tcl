# Independent query-reuse oracle for the dynamic exact-module census.
# Pure Tcl graph fixtures only: not Vivado, native-netlist, CDC, timing, or
# hardware qualification. The candidate is never used to derive expectations.
# Usage: tclsh test_dynamic_census_reuse.tcl ?frozen-baseline.tcl? ?candidate.tcl?
set here [file dirname [file normalize [info script]]]
set root [file normalize [file join $here .. ..]]
set baseline [file join $root common_cdc.census-baseline.tcl]
set candidate [file join $here common_cdc.tcl]
if {[llength $argv] > 0} {set baseline [lindex $argv 0]}
if {[llength $argv] > 1} {set candidate [lindex $argv 1]}
if {[llength $argv] > 2} {error {Usage: test_dynamic_census_reuse.tcl ?baseline? ?candidate?}}
set frozen_sha 75cb49a48404ede21d46f9714427efcafbe129d66208e776e843274970fc7edc
set observed_sha [lindex [exec sha256sum $baseline] 0]
if {$observed_sha ne $frozen_sha} {error "Frozen census oracle changed: $observed_sha"}

proc assert {condition description} {
    if {![uplevel 1 [list expr $condition]]} {error $description}
}
namespace eval fixture {
    variable rows {}; variable order {}; variable next_id 0
    variable counts {}; variable trace {}; variable cases 0; variable batch_fault {}
    variable roots {
        u_soc/ddrCrossing u_soc/fixedTimer u_soc/ddrQualification
        u_soc/timerQualification u_soc/runtime u_soc/debugSequence
        u_soc/peripherals/rateCmu u_soc/peripherals/crossing
        u_soc/peripherals/guard u_soc/fabricDdrReady_ddrReadySync u_soc/debugFaultSync
    }
    variable patterns {
        HeldResponseCdcDataFifo* CdcMailbox* RegisterClockDomainBridge* CdcLevel* CdcDataFifo*
    }
    # Explicit source ABI, independent of the candidate and its group builder.
    variable fifo_names {
        u_soc/ddrCrossing/empty_fifo u_soc/ddrCrossing/empty_fifo_1
        u_soc/ddrCrossing/empty_fifo_2 u_soc/ddrCrossing/empty_fifo_3
        u_soc/ddrCrossing/empty_fifo_4 u_soc/peripherals/crossing/txData
        u_soc/peripherals/crossing/txControl u_soc/peripherals/crossing/rxData
        u_soc/peripherals/crossing/rxStatus
    }
    variable mailbox_names {
        u_soc/fixedTimer/snapshots
        u_soc/debugSequence/boundary/crossing/requests
        u_soc/debugSequence/boundary/crossing/responses
        u_soc/peripherals/rateCmu/receipt
        u_soc/peripherals/crossing/commands u_soc/peripherals/crossing/receipts
        u_soc/peripherals/crossing/observations
        u_soc/peripherals/guard/requests u_soc/peripherals/guard/replies
        u_soc/ddrQualification/command u_soc/ddrQualification/observation
        u_soc/ddrQualification/terminal u_soc/ddrQualification/retirement
        u_soc/timerQualification/command u_soc/timerQualification/observation
        u_soc/timerQualification/terminal u_soc/timerQualification/retirement
        u_soc/runtime/command u_soc/runtime/cpuArm u_soc/runtime/cpuObservation
        u_soc/runtime/fabricObservation u_soc/runtime/terminal u_soc/runtime/retirement
        u_soc/debugSequence/prepare u_soc/debugSequence/proof
        u_soc/debugSequence/decision u_soc/debugSequence/terminal
        u_soc/debugSequence/retirement u_soc/debugSequence/boundary/probe
        u_soc/debugSequence/boundary/proof u_soc/debugSequence/boundary/release_0
        u_soc/debugSequence/boundary/releaseAck
    }
    variable register_names {
        u_soc/fixedTimer/mmio u_soc/peripherals/rateCmu/bridge
        u_soc/peripherals/crossing/csr
    }
    variable level_names {
        u_soc/ddrCrossing/fabricLinkReady_sync u_soc/ddrCrossing/ddrLinkReady_sync
        u_soc/fixedTimer/interrupt u_soc/fabricDdrReady_ddrReadySync u_soc/debugFaultSync
        u_soc/peripherals/crossing/fatalRxStop_sync u_soc/peripherals/crossing/sync
        u_soc/peripherals/guard/faultSync
        u_soc/ddrQualification/fixedFaultSync u_soc/ddrQualification/fabricFaultSync
        u_soc/timerQualification/fixedFaultSync u_soc/timerQualification/fabricFaultSync
        u_soc/runtime/retirementFaultInAon_sync u_soc/runtime/localCloseFault_sync
        u_soc/runtime/localCloseFault_sync_1 u_soc/debugSequence/fatalStop_sync
        u_soc/debugSequence/debugFaultSync u_soc/debugSequence/fabricFaultSync
    }
    foreach h $register_names {
        lappend level_names $h/requestSync $h/responseSync
    }
    foreach h $mailbox_names {
        lappend level_names $h/requestSync $h/ackSync
    }
    variable expected_by_pattern [list \
        HeldResponseCdcDataFifo* $fifo_names CdcMailbox* $mailbox_names \
        RegisterClockDomainBridge* $register_names CdcLevel* $level_names CdcDataFifo* {}]
}
proc fixture::add {name ref} {
    variable rows; variable order; variable next_id
    # Handles deliberately differ from NAME and can represent duplicate NAMEs.
    set id object#[incr next_id]
    lappend order $id
    dict set rows $id [dict create query_name $name NAME $name REF_NAME $ref]
    return $id
}
proc fixture::find {name} {
    variable rows; variable order
    foreach id $order {
        if {[dict get $rows $id query_name] eq $name} {return $id}
    }
    error "Fixture object not found: $name"
}
proc fixture::drop {id} {
    variable rows; variable order
    set order [lsearch -all -inline -not -exact $order $id]
    dict unset rows $id
}
proc fixture::rename_cell {id name} {
    variable rows
    dict set rows $id query_name $name
    dict set rows $id NAME $name
}
proc fixture::groups {root} {
    variable expected_by_pattern
    set groups {}
    foreach {pattern names} $expected_by_pattern {
        set expected {}
        foreach name $names {
            if {[string first "$root/" $name] == 0} {lappend expected $name}
        }
        lappend groups $pattern $expected
    }
    return $groups
}
proc fixture::build {{ordering insertion}} {
    variable rows; variable order; variable next_id; variable roots
    variable fifo_names; variable mailbox_names; variable register_names; variable level_names
    set rows {}; set order {}; set next_id 0
    foreach root $roots {
        add $root BoundaryRoot
        add $root/logic FDCE
        add $root/nested/inert LUT6
        # A name resembling a relevant module is still irrelevant with this REF.
        add $root/CdcMailbox_decoy NotAMailbox
        # Sibling prefix must not leak into the descendant-only query.
        add ${root}_sibling/foreign CdcDataFifo_legacy
    }
    foreach name $fifo_names {add $name HeldResponseCdcDataFifo_64}
    foreach name $mailbox_names {add $name CdcMailbox_35}
    foreach name $register_names {add $name RegisterClockDomainBridge_64}
    foreach name $level_names {
        if {[catch {set id [find $name]}]} {add $name CdcLevel_2} else {
            dict set rows $id REF_NAME CdcLevel_2
        }
        # Deep primitive descendants must be classified, not filtered away.
        add $name/stages_reg0 FDCE
    }
    add outside/forbidden CdcDataFifo_legacy
    if {$ordering eq {reverse}} {
        set order [lreverse $order]
    } elseif {$ordering eq {sorted}} {
        set pairs {}; foreach id $order {lappend pairs [list [dict get $rows $id query_name] $id]}
        set order [lmap pair [lsort -index 0 $pairs] {lindex $pair 1}]
    } elseif {$ordering ne {insertion}} {error "Unknown ordering $ordering"}
}
proc fixture::clear_log {side} {
    variable counts; variable trace
    dict set counts $side [dict create get_cells 0 REF_NAME 0 NAME 0]
    dict set trace $side [dict create queries {} REF_NAME {} NAME {}]
}
proc fixture::bump {side key value} {
    variable counts; variable trace
    dict set counts $side $key [expr {[dict get $counts $side $key] + 1}]
    dict set trace $side $key [concat [dict get $trace $side $key] [list $value]]
}
proc fixture::get_cells {side args} {
    variable rows; variable order; variable counts; variable trace
    # Refuse altered selectors, primitive-only filtering, queries, or broad scans.
    if {[llength $args] != 4 || [lrange $args 0 2] ne {-quiet -hier -filter} ||
        ![regexp {^NAME =~ (.+)/\*$} [lindex $args 3] -> root]} {
        error "Unexpected native get_cells query: $args"
    }
    dict set counts $side get_cells [expr {[dict get $counts $side get_cells] + 1}]
    dict set trace $side queries [concat [dict get $trace $side queries] [list $args]]
    set found {}
    foreach id $order {
        if {[string match "$root/*" [dict get $rows $id query_name]]} {lappend found $id}
    }
    return $found
}
proc fixture::get_property {side property objects} {
    variable rows; variable counts; variable trace; variable batch_fault
    if {$property ni {REF_NAME NAME}} {error "Unexpected property request: $property"}
    if {$side ne {candidate} || $property ne {REF_NAME}} {
        # The immutable baseline and matching NAME reads remain scalar.
        set id $objects
        bump $side $property $id
        if {![dict exists $rows $id $property]} {error "MOCK missing $property on $id"}
        return [dict get $rows $id $property]
    }
    # Native collection property values preserve each object's input position,
    # including an empty property value. Count one API call, every visited row.
    dict set counts $side $property [expr {[dict get $counts $side $property] + 1}]
    set values {}
    foreach id $objects {
        dict set trace $side $property [concat [dict get $trace $side $property] [list $id]]
        if {![dict exists $rows $id $property]} {error "MOCK missing $property on $id"}
        lappend values [dict get $rows $id $property]
    }
    # Negative controls corrupt observations, never directly inject a failure.
    switch -- $batch_fault {
        truncate {set values [lrange $values 0 end-1]}
        prepend {set values [linsert $values 0 ExtraReference]}
        empty {set values {}}
        reverse {set values [lreverse $values]}
        replacement {lset values 0 UnknownReference}
        blank {lset values 0 {}}
        {} {}
        default {error "Unsupported fixture mutation $batch_fault"}
    }
    return $values
}

# Immutable production procedures live in separate interpreters, with the same
# read-only mock graph. No rewritten oracle algorithm or candidate-fed verdict.
foreach {side path} [list baseline $baseline candidate $candidate] {
    interp create $side
    interp eval $side [list set ::valence(root) $root]
    interp eval $side [list source $path]
    interp alias $side get_cells {} fixture::get_cells $side
    interp alias $side get_property {} fixture::get_property $side
}
assert {[interp eval baseline {info args common_cdc::exact_modules}] eq \
        [interp eval candidate {info args common_cdc::exact_modules}]} {Original exact_modules arguments changed}
assert {[interp eval baseline {info body common_cdc::exact_modules}] eq \
        [interp eval candidate {info body common_cdc::exact_modules}]} {Original exact_modules body changed}
assert {[interp eval candidate {info args common_cdc::exact_module_groups}] eq {root groups}} \
    {Candidate exact_module_groups contract changed}
interp eval baseline {
    proc run_census {root groups} {
        foreach {ref expected} $groups {common_cdc::exact_modules $root $ref $expected}
    }
}
interp eval candidate {
    proc run_census {root groups} {common_cdc::exact_module_groups $root $groups}
}
proc fixture::invoke {side root groups} {
    clear_log $side
    set code [catch {interp eval $side [list run_census $root $groups]} message options]
    return [list $code $message]
}
proc fixture::compare {label root groups expected_code} {
    variable cases; variable counts; variable trace; variable rows; variable order
    set old [invoke baseline $root $groups]
    set new [invoke candidate $root $groups]
    assert {$old eq $new} "$label: baseline=$old candidate=$new"
    assert {[lindex $old 0] == $expected_code} "$label: unexpected baseline verdict $old"
    assert {[dict get $counts candidate get_cells] == 1} "$label: candidate must query once per invocation"
    assert {[dict get $trace baseline NAME] eq [dict get $trace candidate NAME]} \
        "$label: NAME access trace changed"
    # Every returned cell must have its REF read, including irrelevant cells.
    # A missing REF naturally stops at that failed read, with no skipped prefix.
    set members {}
    foreach id $order {
        if {![string match "$root/*" [dict get $rows $id query_name]]} {continue}
        lappend members $id
        if {![dict exists $rows $id REF_NAME]} {break}
    }
    assert {[dict get $trace candidate REF_NAME] eq $members} \
        "$label: candidate skipped, repeated, reordered, or persisted cell classification"
    incr cases
    return $new
}
proc fixture::accepted_workload {label} {
    variable roots; variable counts; variable trace
    set old_queries 0; set new_queries 0; set old_refs 0; set new_refs 0; set old_names 0; set new_names 0
    foreach root $roots {
        compare "$label $root" $root [groups $root] 0
        assert {[dict get $counts baseline get_cells] == 5} "$label: baseline must query five times per root"
        assert {[dict get $counts baseline REF_NAME] == 5 * [llength [dict get $trace candidate REF_NAME]]} \
            "$label: every cell must retain all five census comparisons"
        assert {[dict get $counts candidate REF_NAME] == 1} \
            "$label: expected one bulk REF_NAME query per nonempty root"
        incr old_queries [dict get $counts baseline get_cells]
        incr new_queries [dict get $counts candidate get_cells]
        incr old_refs [dict get $counts baseline REF_NAME]
        incr new_refs [dict get $counts candidate REF_NAME]
        incr old_names [dict get $counts baseline NAME]
        incr new_names [dict get $counts candidate NAME]
    }
    assert {$old_queries == 55 && $new_queries == 11} "$label: census native calls are not 55 versus 11"
    assert {$old_names == $new_names} "$label: NAME accesses changed"
    assert {$old_refs == 1255 && $new_refs == 11} "$label: REF_NAME API calls are not 1255 versus 11"
    puts "CENSUS_QUERY_REUSE $label roots=11 get_cells=$old_queries->$new_queries REF_NAME=$old_refs->$new_refs NAME=$old_names->$new_names"
}

# Accepted census and exact NAME/error ordering under native insertion, sorted,
# and reversed enumeration. Expected lists deliberately retain source ABI order.
foreach ordering {insertion sorted reverse} {
    fixture::build $ordering
    fixture::accepted_workload $ordering
}

# Exercise every group at every root, including empty expected groups and the
# forbidden legacy FIFO group. Fixture expectations are never learned from code.
foreach root $fixture::roots {
    foreach {pattern expected} [fixture::groups $root] {
        fixture::build
        set ref [string trimright $pattern *]
        fixture::add $root/new_unexpected ${ref}_new
        fixture::compare "new module $root $pattern" $root [fixture::groups $root] 1
        if {![llength $expected]} {continue}
        set name [lindex $expected 0]
        fixture::build
        fixture::drop [fixture::find $name]
        fixture::compare "missing module $name" $root [fixture::groups $root] 1
        fixture::build
        dict set fixture::rows [fixture::find $name] REF_NAME WrongModule
        fixture::compare "wrong reference $name" $root [fixture::groups $root] 1
        fixture::build
        fixture::add $name ${ref}_duplicate
        fixture::compare "duplicate relevant NAME $name" $root [fixture::groups $root] 1
        fixture::build reverse
        fixture::rename_cell [fixture::find $name] $root/renamed_module
        fixture::compare "renamed module $name" $root [fixture::groups $root] 1
    }
}

# Sorted comparison is a multiset comparison, not a unique-name comparison.
fixture::build
set r u_soc/fixedTimer
set name $r/snapshots
fixture::add $name CdcMailbox_duplicate
set groups [fixture::groups $r]
set at [lsearch -exact $groups CdcMailbox*]
set expected [lindex $groups [expr {$at + 1}]]
lappend expected $name
lset groups [expr {$at + 1}] $expected
fixture::compare {explicit duplicate in both actual and expected} $r $groups 0
set reordered_groups {}
foreach {pattern names} $groups {lappend reordered_groups $pattern [lreverse $names]}
fixture::compare {reversed expected lists} $r $reordered_groups 0

# Overlapping globs require reclassification for each group, not first-match
# dispatch. NAME must still be read for each matching group, not globally cached.
set fixture::rows {}; set fixture::order {}; set fixture::next_id 0
set r test/overlap
fixture::add $r/z CdcLevel_2
fixture::add $r/a CdcMailbox_8
fixture::add $r/m Other
set groups [list Cdc* [list $r/z $r/a] CdcLevel* [list $r/z] * [list $r/m $r/z $r/a] CdcDataFifo* {}]
fixture::compare {overlapping REF_NAME patterns} $r $groups 0
assert {[dict get $fixture::counts candidate NAME] == 6} {Overlapping groups lost repeated NAME reads}
fixture::add $r/new CdcLevel_3
fixture::compare {overlapping pattern unexpected module} $r $groups 1

# Empty expected sets preserve strict rejection; a zero-pair invocation is also
# valid on a well-formed graph and still performs the helper's one native query.
set fixture::rows {}; set fixture::order {}; set fixture::next_id 0
set r test/empty
set empty_groups {}; foreach pattern $fixture::patterns {lappend empty_groups $pattern {}}
fixture::compare {empty graph, all five expected groups empty} $r $empty_groups 0
fixture::add $r/inert LUT6
fixture::compare {irrelevant-only graph, all expected groups empty} $r $empty_groups 0
fixture::compare {zero group pairs, well-formed graph} $r {} 0
fixture::add $r/legacy CdcDataFifo
fixture::compare {legacy FIFO cannot hide in an empty expected group} $r $empty_groups 1

# Missing/empty properties follow the frozen procedure, not a blanket exemption.
# A missing NAME is harmless only if the REF is irrelevant; every REF must still
# be queried. A matching missing NAME and an unreadable REF both fail closed.
fixture::build
set r u_soc/fixedTimer
set id [fixture::add $r/malformed_irrelevant LUT6]
dict unset fixture::rows $id NAME
fixture::compare {irrelevant object with unreadable NAME} $r [fixture::groups $r] 0
set id [fixture::add $r/blank_ref {}]
dict unset fixture::rows $id NAME
fixture::compare {empty REF remains irrelevant without a NAME read} $r [fixture::groups $r] 0
fixture::build
set id [fixture::find $r/snapshots]
dict unset fixture::rows $id NAME
fixture::compare {relevant object with unreadable NAME} $r [fixture::groups $r] 1
fixture::build
set id [fixture::find $r/snapshots]
dict set fixture::rows $id NAME {}
fixture::compare {relevant object with blank NAME} $r [fixture::groups $r] 1
fixture::build
set id [fixture::add $r/malformed_new LUT6]
dict unset fixture::rows $id REF_NAME
fixture::compare {new unreadable REF is not skipped} $r [fixture::groups $r] 1
fixture::build
set id [fixture::find $r]
dict unset fixture::rows $id REF_NAME
set id [fixture::add ${r}_sibling/malformed LUT6]
dict unset fixture::rows $id REF_NAME
fixture::compare {root and sibling are not descendants} $r [fixture::groups $r] 0

# Same interpreters, same root, and often the same handles: mutation and repair
# between invocations must be visible. No source reload or cache reset occurs.
fixture::build
set r u_soc/fixedTimer
set groups [fixture::groups $r]
fixture::compare {freshness initial} $r $groups 0
set changed_groups $groups
set at [lsearch -exact $changed_groups CdcMailbox*]
lset changed_groups [expr {$at + 1}] {}
fixture::compare {freshness changed expected list} $r $changed_groups 1
fixture::compare {freshness restored expected list} $r $groups 0
set id [fixture::add $r/new_mailbox CdcMailbox_8]
fixture::compare {freshness new graph member} $r $groups 1
fixture::drop $id
fixture::compare {freshness removed graph member} $r $groups 0
set id [fixture::find $r/snapshots]
fixture::rename_cell $id $r/renamed_snapshot
fixture::compare {freshness changed NAME} $r $groups 1
fixture::rename_cell $id $r/snapshots
fixture::compare {freshness restored NAME} $r $groups 0
dict set fixture::rows $id REF_NAME NotAMailbox
fixture::compare {freshness changed REF_NAME} $r $groups 1
dict set fixture::rows $id REF_NAME CdcMailbox_new_specialization
fixture::compare {freshness restored matching REF_NAME} $r $groups 0
set added [fixture::add $r/new_malformed LUT6]
dict unset fixture::rows $added REF_NAME
fixture::compare {freshness newly unreadable REF} $r $groups 1
dict set fixture::rows $added REF_NAME LUT6
fixture::compare {freshness repaired unreadable REF} $r $groups 0
dict set fixture::rows $added REF_NAME CdcDataFifo_legacy
fixture::compare {freshness irrelevant becomes forbidden legacy FIFO} $r $groups 1
fixture::drop $added
fixture::compare {freshness final repair} $r $groups 0

# Bulk return cardinality is checked before zip/truncation can hide a cell.
# Cross-reference reversal is caught by the same exact module/name oracle.
set fixture::rows {}; set fixture::order {}; set fixture::next_id 0
set r test/bulk
fixture::add $r/a CdcMailbox_8
fixture::add $r/b CdcLevel_2
set groups [list CdcMailbox* [list $r/a] CdcLevel* [list $r/b] CdcDataFifo* {}]
fixture::compare {ordered two-reference bulk mapping} $r $groups 0
set batch_cases 0
foreach mutation {truncate prepend empty reverse replacement blank} {
    set fixture::batch_fault $mutation
    set old [fixture::invoke baseline $r $groups]
    set observed [fixture::invoke candidate $r $groups]
    assert {[lindex $old 0]==0} "$mutation: uncorrupted baseline must pass"
    assert {[lindex $observed 0]==1} "$mutation: corrupted bulk observation was accepted"
    if {$mutation in {truncate prepend empty}} {
        assert {[string match {COMMON_CDC exact module REF_NAME collection cardinality changed*} [lindex $observed 1]]} \
            "$mutation: missing exact cardinality rejection"
    } else {
        assert {[string match {COMMON_CDC exact module census changed*} [lindex $observed 1]]} \
            "$mutation: missing ordinary census/name-association rejection"
    }
    incr batch_cases
    set fixture::batch_fault {}
    fixture::compare "bulk repaired after $mutation" $r $groups 0
}
set fixture::rows {}; set fixture::order {}; set fixture::next_id 0
fixture::add $r/empty_ref {}
fixture::compare {one empty REF preserves its list position} $r [list CdcMailbox* {} CdcLevel* {}] 0
puts "PASS dynamic census query reuse: $fixture::cases independent equivalence cases; bulk_corruption_negatives=$batch_cases; frozen baseline $frozen_sha"
interp delete baseline candidate
