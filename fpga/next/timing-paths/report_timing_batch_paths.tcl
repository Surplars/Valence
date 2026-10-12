# Read-only checkpoint collector. Does not create/change constraints or design.
# vivado -mode batch -source report_timing_batch_paths.tcl -tclargs \
#   CHECKPOINT FRESH_OUTPUT SOC_ROOT BSCAN_ENGINE_ROOT RGMII_ROOT ?TOP_N?
# Roots must be literal, verified hierarchy names, not wildcards.
# This collects evidence; even complete collection is not timing/CDC signoff.
namespace eval valence_timing_batch {
    variable facts
    variable issues 0
    variable topn 20
}

proc valence_timing_batch::record {args} {
    variable facts
    puts $facts $args
    puts $args
}
proc valence_timing_batch::quote {value} {
    return [regsub -all {[][{}().+*?^$|\\]} $value {\\&}]
}
proc valence_timing_batch::problem {args} {
    variable issues
    incr issues
    record {*}$args
}
proc valence_timing_batch::property {object key} {
    if {[lsearch -exact [list_property $object] $key] < 0} {
        problem PROPERTY_UNAVAILABLE $object $key REVIEW_REQUIRED
        return UNAVAILABLE
    }
    return [get_property $key $object]
}
proc valence_timing_batch::root {name} {
    if {$name eq "" || [regexp {[\*\?\[\]]} $name]} {
        problem INVALID_LITERAL_ROOT $name
        return {}
    }
    set found [get_cells -quiet $name]
    record ROOT_QUERY $name COUNT [llength $found] OBJECTS $found
    if {[llength $found] == 0} {
        problem MISSING_OR_CHANGED_ROOT $name
        return {}
    }
    if {[llength $found] != 1 || [get_property NAME $found] ne $name} {
        problem AMBIGUOUS_OR_CHANGED_ROOT $name OBJECTS $found
        return {}
    }
    return $name
}
proc valence_timing_batch::family {out label root suffix pin_patterns} {
    variable topn
    if {$root eq ""} {
        problem MISSING_FAMILY_ROOT $label
        return
    }
    set pattern "^[quote $root]/${suffix}$"
    set cells [get_cells -quiet -hierarchical -regexp $pattern -filter {IS_PRIMITIVE == 1}]
    record FAMILY $label PATTERN $pattern CELL_COUNT [llength $cells]
    if {[llength $cells] == 0} {
        problem MISSING_OR_CHANGED_CELLS $label
        return
    }
    if {[llength $cells] > 1} {
        record MULTIPLE_FAMILY_CELLS_REVIEW $label COUNT [llength $cells]
    }
    foreach cell $cells {
        record CELL $label [get_property NAME $cell] REF_NAME [property $cell REF_NAME]
    }
    set pins {}
    foreach pin [get_pins -quiet -of_objects $cells] {
        if {[get_property DIRECTION $pin] ne "IN"} {continue}
        set ref [get_property REF_PIN_NAME $pin]
        foreach requested $pin_patterns {
            if {[string match $requested $ref]} {lappend pins $pin; break}
        }
    }
    set pins [lsort -unique $pins]
    record PIN_SELECTION $label PATTERNS $pin_patterns PIN_COUNT [llength $pins]
    foreach pin $pins {record PIN $label [get_property NAME $pin] REF_PIN_NAME [get_property REF_PIN_NAME $pin]}
    if {[llength $pins] == 0} {
        problem MISSING_OR_CHANGED_ENDPOINT_PINS $label
        return
    }
    # Each family and each delay type receives its own independent top-N budget.
    # Async reset pins yield recovery/removal checks where the loaded model
    # defines them. Inspect the actual check type in the expanded report.
    foreach delay {max min} {
        set query [list -to $pins -delay_type $delay -max_paths $topn -nworst 5]
        if {[catch {get_timing_paths {*}$query} paths]} {
            problem PATH_QUERY_ERROR $label $delay $paths
            continue
        }
        record TIMED_PATHS $label $delay COUNT [llength $paths] TOP_N $topn
        if {[llength $paths] == 0} {problem MISSING_TIMED_PATH $label $delay REVIEW_CONSTRAINTS_OR_MAPPING}
        set index 0
        foreach path $paths {
            incr index
            set row [list PATH $label $delay $index]
            foreach key {STARTPOINT_PIN ENDPOINT_PIN STARTPOINT_CLOCK ENDPOINT_CLOCK SLACK REQUIREMENT DATAPATH_DELAY LOGIC_LEVELS} {
                lappend row $key [property $path $key]
            }
            record {*}$row
        }
        set filename [file join $out ${label}_${delay}.rpt]
        # A list is a valid Tcl script here; it preserves spaces/indexed pin
        # names and does not accidentally evaluate report_timing first.
        set command [list report_timing {*}$query -path_type full_clock_expanded -input_pins -nets]
        if {[catch {redirect -file $filename $command} detail]} {
            problem REPORT_ERROR $label $delay $detail
        } else {
            record REPORT $label $delay $filename
        }
    }
}
proc valence_timing_batch::collect {checkpoint out soc_name bscan_name mac_name budget} {
    variable facts
    variable issues
    variable topn
    set issues 0
    set topn $budget
    if {![string is integer -strict $topn] || $topn < 1 || $topn > 1000} {error "TOP_N must be 1..1000"}
    set checkpoint [file normalize $checkpoint]
    set out [file normalize $out]
    if {![file isfile $checkpoint]} {error "Missing checkpoint: $checkpoint"}
    if {[file exists $out]} {error "Preserve existing evidence; choose a fresh output directory"}
    file mkdir $out
    set facts [open [file join $out coverage.txt] w]
    set opened 0
    set code [catch {
        record CHECKPOINT $checkpoint SIZE [file size $checkpoint] MTIME [file mtime $checkpoint]
        record SCOPE READ_ONLY_REPORTS NOT_PHYSICAL_SIGNOFF TOP_N_PER_FAMILY_PER_DELAY $topn
        open_checkpoint $checkpoint
        set opened 1
        record TOOL [version -short] PART [get_property PART [current_design]]
        set soc [root $soc_name]
        set bscan [root $bscan_name]
        set mac [root $mac_name]
        set data_pins {D CE SR R S}
        family $out proof $soc {.*pendingStoreProof/.*} $data_pins
        family $out address $soc {.*backend/stagedMemoryAddress_reg.*} $data_pins
        family $out execution $soc {.*backend/executionStages_?[0-9]+/.*} $data_pins
        family $out rank51_payload30 $soc {.*backend/executionStages_?0/payload_reg\[30\].*} {D CE}
        family $out canonical_tracker $soc {.*canonicalStoreTracker/.*} $data_pins
        family $out canonical_event $soc {.*adapter/certificate(Valid|Bits).*} $data_pins
        family $out manager_we $soc {.*manager/bridge/slots_?[0-9]+/.*payloadBanks_?[0-7].*} {WE* WEN*}
        family $out rank64_slot1_bank5 $soc {.*manager/bridge/slots_?1/.*payloadBanks_?5.*} {WE* WEN*}
        family $out manager_data_address $soc {.*manager/bridge/slots_?[0-9]+/.*payloadBanks_?[0-7].*} {D* A*}
        family $out fetch_packet $soc {.*fetchPacket/.*} $data_pins
        family $out fetch_window $soc {.*suppliedPackets_window/.*} $data_pins
        family $out bscan_data_control $bscan {.*} $data_pins
        family $out bscan_reset $bscan {.*} {CLR PRE RST}
        family $out mac_data_control $mac {.*} $data_pins
        family $out mac_reset $mac {.*} {CLR PRE RST}
        family $out ref500_reset $mac {delay_control.*} {RST}
        # Existing report APIs only: no constraint application or ECO helpers.
        foreach {label command} {
            timing_summary {report_timing_summary -report_unconstrained}
            clock_interaction {report_clock_interaction}
            exceptions {report_exceptions -coverage}
            cdc {report_cdc -details}
        } {
            if {[catch {redirect -file [file join $out ${label}.rpt] $command} detail]} {
                problem GLOBAL_REPORT_ERROR $label $detail
            }
        }
        if {$issues} {
            record STATUS INCOMPLETE_OR_CHANGED_REVIEW_REQUIRED ISSUES $issues
        } else {
            record STATUS COLLECTED_REVIEW_REQUIRED NOT_TIMING_OR_CDC_PASS
        }
    } result options]
    if {$code} {record COLLECTOR_ERROR $result}
    if {$opened} {close_design}
    close $facts
    if {$code} {return -options $options $result}
    return $issues
}
if {![info exists ::valence_timing_batch_library_only]} {
    if {$argc ni {5 6}} {error "Expected CHECKPOINT FRESH_OUTPUT SOC_ROOT BSCAN_ENGINE_ROOT RGMII_ROOT ?TOP_N?"}
    lassign $argv checkpoint out soc bscan mac budget
    if {$budget eq ""} {set budget 20}
    set missing [valence_timing_batch::collect $checkpoint $out $soc $bscan $mac $budget]
    if {$missing} {error "Timing evidence incomplete/changed; inspect coverage.txt ($missing findings)"}
}
