# Read-only endpoint families and source-to-sink cuts of one routed board DCP.
# Usage: ROUTED_BOARD_DCP FRESH_OUTPUT_DIRECTORY
# Existing physical clocks/constraints are mandatory. No implementation or
# checkpoint/bitstream write is performed; negative timing is reported, not hidden.

proc tsv_field {value} {
    return [string map [list "\t" " " "\n" " " "\r" " "] $value]
}
proc safe_property {property object {fallback NA}} {
    if {[catch {get_property $property $object} value] || $value eq ""} { return $fallback }
    return $value
}
proc path_fields {path} {
    set fields {}
    foreach property {SLACK DATAPATH_DELAY LOGIC_LEVELS STARTPOINT_PIN ENDPOINT_PIN} {
        lappend fields [tsv_field [safe_property $property $path]]
    }
    return $fields
}
proc under_roots {name roots} {
    foreach root $roots {
        if {[string first "$root/" $name] == 0} { return 1 }
    }
    return 0
}
proc discover_roots {} {
    set references [dict create issue {IssueExecuteStage} raw {RegisteredFetchPacket} \
        ras {RetirementReturnStack} ledger {RenameRob} system {MachineSystemUnit} \
        fetch_adapter {InstructionTranslationAdapter WordInstructionTranslationAdapter} \
        data_adapter {DataTranslationAdapter DataResponseBuffer} \
        frontend {SynchronousFetch InstructionLineCache InstructionLinePrefetch} \
        lsu {ParallelLoadStoreUnit LoadStoreUnit} cache {CoherentLineCache CachedDataMemory} \
        walkers {SvTranslationService}]
    set roots {}
    dict for {kind prefixes} $references { dict set roots $kind {} }
    foreach cell [get_cells -quiet -hier -filter {IS_PRIMITIVE == 0}] {
        set name [get_property NAME $cell]
        dict for {kind prefixes} $references {
            set matched 0
            foreach property {REF_NAME ORIG_REF_NAME} {
                set reference [safe_property $property $cell ""]
                foreach prefix $prefixes {
                    if {[string match "$prefix*" $reference]} {
                        dict lappend roots $kind $name
                        set matched 1
                        break
                    }
                }
                if {$matched} { break }
            }
        }
    }
    dict for {kind values} $roots { dict set roots $kind [lsort -unique $values] }
    return $roots
}
proc family_matches {family name roots} {
    # Rebuilt hierarchy can rename instances or move cells across module roots.
    # Discover original reference roots, then allow audited segment/leaf aliases.
    set leaf [lindex [split $name /] end]
    set backend [expr {[under_roots $name [dict get $roots ledger]] ||
        [regexp -nocase {(^|/)[^/]*backend(/|_)} $name]}]
    set raw [expr {[under_roots $name [dict get $roots raw]] ||
        [regexp -nocase {(^|/)(fetchPacket|RegisteredFetchPacket)[^/]*/} $name]}]
    set issue [expr {[under_roots $name [dict get $roots issue]] ||
        [regexp -nocase {(^|/)(executionStages|execution_stage|IssueExecuteStage)[^/]*/} $name]}]
    set ras [expr {[under_roots $name [dict get $roots ras]] ||
        [regexp -nocase {(^|/)(returnStack|RetirementReturnStack)[^/]*/} $name]}]
    switch -- $family {
        raw_cursor { return [expr {$raw && [regexp -nocase {^supplyPc(_reg|\[|_|$)} $leaf]}] }
        raw_slots { return [expr {$raw && [regexp -nocase {^slots(_reg|\[|_|$)} $leaf]}] }
        raw_hints { return [expr {$raw && [regexp -nocase {^(hint(Valid|Pc|Instruction|NextPc)|count)(_reg|\[|_|$)} $leaf]}] }
        core_pc { return [regexp -nocase {(^|/)pc_reg($|\[|/|_)} $name] }
        frontend_cache {
            return [expr {[under_roots $name [dict get $roots frontend]] ||
                [regexp -nocase {(^|/)(frontend|fetchCache|instructionCache|prefetch|InstructionLineCache|InstructionLinePrefetch)(/|_)} $name]}]
        }
        fetch_adapter {
            return [expr {[under_roots $name [dict get $roots fetch_adapter]] ||
                [regexp -nocase {(^|/)(fetchAdapter|InstructionTranslationAdapter|WordInstructionTranslationAdapter)(/|_)} $name]}]
        }
        pmp_state { return [regexp -nocase {(^|/|_)pmp(Cfg|Addr|State)(_|\[|_reg)} $name] }
        vm_csr {
            return [expr {([under_roots $name [dict get $roots system]] ||
                [regexp -nocase {(^|/)(systemUnit|MachineSystemUnit)(/|_)} $name]) &&
                [regexp -nocase {^(satp|privilege|mprv|mpp|sum|mxr)(_reg|\[|_|$)} $leaf]}]
        }
        irq_state {
            return [expr {([under_roots $name [dict get $roots system]] ||
                [regexp -nocase {(^|/)(systemUnit|MachineSystemUnit)(/|_)} $name]) &&
                [regexp -nocase {^(mie|mtie|meie|seie|ssie|stie|sie|privilege|ssip|stipSoftware|stipHardware|stimecmp|seideleg|ssideleg|stideleg)(_reg|\[|_|$)} $leaf]}]
        }
        head_state {
            return [expr {([under_roots $name [dict get $roots ledger]] ||
                [regexp -nocase {(^|/)(ledger|renameRob|RenameRob)(/|_)} $name]) &&
                [regexp -nocase {^(head|count|keepCount|recovering|entries_?[0-9]+_(done|exception))(_reg|\[|_|$)} $leaf]}]
        }
        rename_ledger {
            return [expr {[under_roots $name [dict get $roots ledger]] ||
                [regexp -nocase {(^|/)(ledger|renameRob|RenameRob)(/|_)} $name]}]
        }
        ras_entries { return [expr {$ras && [regexp -nocase {^entries(_reg|\[|_|$)} $leaf]}] }
        ras_control { return [expr {$ras && [regexp -nocase {^(top|count)(_reg|\[|_|$)} $leaf]}] }
        prf_ready { return [expr {$backend && [regexp -nocase {^ready(_reg|\[|_|$)} $leaf]}] }
        prf_values { return [expr {$backend && [regexp -nocase {^values(_reg|\[|_|$)} $leaf]}] }
        pending { return [expr {$backend && [regexp -nocase {^pending(_reg|\[|_|$)} $leaf]}] }
        issue_operands { return [expr {$issue && [regexp -nocase {^payload(_reg|\[|_|$)} $leaf]}] }
        issue_occupancy { return [expr {$issue && [regexp -nocase {^occupied(_reg|\[|_|$)} $leaf]}] }
        lsu_address {
            return [expr {$backend && [regexp -nocase {^(stagedMemoryAddress|storeAddress|storeEnd|storeSafeRange|loadBeat|loadLanes)} $leaf]}]
        }
        lsu_preparation {
            return [expr {$backend && [regexp -nocase {^(stagedMemory(Index|Candidate|Owner|Grant|Legal|Operands|Physical)|storeData|storePrepared)} $leaf]}]
        }
        lsu_state {
            return [expr {[under_roots $name [dict get $roots lsu]] ||
                [regexp -nocase {(^|/)(lsu|ParallelLoadStoreUnit|LoadStoreUnit)(/|_)} $name]}]
        }
        data_adapter {
            return [expr {[under_roots $name [dict get $roots data_adapter]] ||
                [regexp -nocase {(^|/)(adapter|dataAdapter|DataTranslationAdapter|DataResponseBuffer)(/|_)} $name]}]
        }
        translated_replies {
            return [regexp -nocase {(^|/)(responses|cpuResponses|translatedResponses)[^/]*/} $name]
        }
        coherent_cache {
            return [expr {[under_roots $name [dict get $roots cache]] ||
                [regexp -nocase {(^|/)(coherentCache|dataCache|cache|CoherentLineCache|CachedDataMemory)(/|_)} $name]}]
        }
        page_walkers {
            return [expr {[under_roots $name [dict get $roots walkers]] ||
                [regexp -nocase {(^|/)(physicalData_walkers|walkers|walker|translation|SvTranslationService)(/|_|$)} $name]}]
        }
        fabric {
            return [regexp -nocase {(^|/)(physicalData|coherentHome|bridge|crossbar|router|bankRouter|home|sharedData|checked)[^/]*/} $name]
        }
        default { error "Unknown endpoint family: $family" }
    }
}
proc endpoint_pins {cells {kind data_enable}} {
    if {[llength $cells] == 0} { return {} }
    switch -- $kind {
        ce { return [get_pins -quiet -of_objects $cells -filter {REF_PIN_NAME == CE}] }
        d { return [get_pins -quiet -of_objects $cells -filter {REF_PIN_NAME == D}] }
        data_enable {
            # Include memory address/write/enable endpoints, not only FF D/CE;
            # otherwise fabric/cache groups could silently miss BRAM/UltraRAM.
            set pins [get_pins -quiet -of_objects $cells -filter {DIRECTION == IN &&
                (REF_PIN_NAME == D || REF_PIN_NAME == CE || REF_PIN_NAME =~ ADDR* ||
                 REF_PIN_NAME =~ DI* || REF_PIN_NAME =~ EN* || REF_PIN_NAME =~ REGCE* ||
                 REF_PIN_NAME =~ WE* || REF_PIN_NAME =~ BW* || REF_PIN_NAME =~ OREG_CE* ||
                 REF_PIN_NAME =~ IREG_CE* || REF_PIN_NAME =~ RDB_WR*)}]
            # A registered multiplier can otherwise disappear from the catch-all
            # family: DSP data/control/CE pins are not named FF D or memory DI.
            # Iterate the collection explicitly. Expanding a large Vivado
            # collection with {*} or lsort converts it through the display
            # limit (500 objects by default), truncating the diagnostic scope.
            set names {}
            foreach pin $pins { dict set names [get_property NAME $pin] 1 }
            set dsp_cells [filter $cells {REF_NAME =~ DSP*}]
            if {[llength $dsp_cells] > 0} {
                foreach pin [get_pins -quiet -of_objects $dsp_cells -filter {
                    DIRECTION == IN && REF_PIN_NAME != CLK && REF_PIN_NAME !~ RST*}] {
                    dict set names [get_property NAME $pin] 1
                }
            }
            return [dict keys $names]
        }
        default { error "Unknown endpoint pin kind: $kind" }
    }
}
proc query_paths {clock pins sources} {
    if {[llength $pins] == 0} { return {} }
    set options [list -quiet -group $clock -delay_type max -to $pins -max_paths 5 -nworst 1]
    if {[llength $sources] > 0} { lappend options -from $sources }
    return [get_timing_paths {*}$options]
}
proc emit_group {directory kind category label clock from_family to_family sources sinks pin_kind stream summary negative} {
    set pins [endpoint_pins $sinks $pin_kind]
    set paths {}
    if {$kind eq "family" || [llength $sources] > 0} { set paths [query_paths $clock $pins $sources] }
    set status MATCHED
    if {$kind eq "cut" && [llength $sources] == 0} { set status EMPTY_NO_SOURCE_REGISTERS }
    if {[llength $sinks] == 0} { set status EMPTY_NO_SINK_REGISTERS }
    if {[llength $sinks] > 0 && [llength $pins] == 0} { set status EMPTY_NO_ENDPOINT_PINS }
    if {$status eq "MATCHED" && [llength $paths] == 0} { set status EMPTY_NO_TIMED_PATHS }
    set source_count [expr {$kind eq "family" ? "NA" : [llength $sources]}]
    set counts [list $category $label $from_family $to_family $source_count [llength $sinks] \
        $pin_kind [llength $pins] [llength $paths] $status]
    set report_file [file join $directory "${kind}__${label}_paths.rpt"]
    set worst [list NA NA NA NA NA]
    set negative_count 0
    if {[llength $paths] == 0} {
        puts $stream [join [concat $counts [list 0] $worst] "\t"]
        set report [open $report_file w]
        puts $report "status=$status source_register_count=$source_count sink_register_count=[llength $sinks] endpoint_pin_count=[llength $pins]"
        puts $report {0 matched timing paths; slack/data_delay/logic_levels=NA. No improvement may be inferred from an empty group.}
        close $report
    } else {
        set rank 0
        foreach path $paths {
            set fields [path_fields $path]
            if {$rank == 0} { set worst $fields }
            set slack [lindex $fields 0]
            if {[string is double -strict $slack] && $slack < 0} { incr negative_count }
            puts $stream [join [concat $counts [list [incr rank]] $fields] "\t"]
        }
        set options [list -group $clock -delay_type max -to $pins -max_paths 5 -nworst 1 -input_pins]
        if {$kind eq "cut"} { lappend options -from $sources }
        report_timing {*}$options -file $report_file
    }
    # Count is only among returned paths, capped at five. It is NOT the total
    # failing endpoint count, nor a routed release/signoff decision.
    set summary_row [concat [list $kind] $counts [list $negative_count] $worst]
    puts $summary [join $summary_row "\t"]
    if {$negative_count > 0} { puts $negative [join $summary_row "\t"] }
    puts "BOARD_PATH_GROUP $kind/$label matched_registers=[llength $sinks] matched_pins=[llength $pins] returned_paths=[llength $paths] negative_returned=$negative_count worst_slack=[lindex $worst 0] status=$status"
}

if {$argc != 2} { error {usage: ROUTED_BOARD_DCP FRESH_OUTPUT_DIRECTORY} }
lassign $argv checkpoint out
set checkpoint [file normalize $checkpoint]
set out [file normalize $out]
if {![file isfile $checkpoint]} { error "Checkpoint missing: $checkpoint" }
if {[file exists $out]} { error {Use a fresh output directory; never overwrite timing evidence} }

# Open exactly once. Never create clocks, source an XDC or change exceptions.
open_checkpoint $checkpoint
set part [get_property PART [current_design]]
if {$part ne "xczu15eg-ffvb1156-2-i"} { error "Wrong FPGA part: $part" }
set blackboxes [get_cells -quiet -hier -filter {IS_BLACKBOX}]
if {[llength $blackboxes] != 0} { error "Unresolved black boxes: $blackboxes" }
set cpu [get_clocks -quiet clk_out1_clk_wiz_ddr]
if {[llength $cpu] != 1 || abs([get_property PERIOD $cpu] - 10.0) > 0.001 ||
    ![get_property IS_GENERATED $cpu]} {
    error {Expected the existing real 100 MHz CPU generated clock}
}
set ui_pin [get_pins -quiet u_ddr/c0_ddr4_ui_clk]
if {[llength $ui_pin] != 1} { error {Expected the real MIG UI clock pin} }
set ui [get_clocks -quiet -of_objects $ui_pin]
if {[llength $ui] != 1 || abs([get_property PERIOD $ui] - 4.0) > 0.0001} {
    error {Expected the existing real MIG UI clock at 250 MHz}
}
set registers [all_registers -clock $cpu -cells]
if {[llength $registers] == 0} { error {Real CPU clock reaches no registers} }
file mkdir $out
report_route_status -file [file join $out route_status.rpt]
set route_stream [open [file join $out route_status.rpt] r]
set route [read $route_stream]
close $route_stream
foreach {label variable} {"routable nets" routable "fully routed nets" fully "nets with routing errors" route_errors} {
    if {![regexp [format {%s\.+\s*:\s*([0-9]+)} $label] $route -> $variable]} {
        error "Missing route statistic: $label"
    }
}
if {$routable != $fully || $route_errors != 0} { error {Input must be a fully routed, routing-error-free board checkpoint} }
set inputs [open [file join $out inputs.tsv] w]
puts $inputs "checkpoint\tpart\tcpu_clock\tcpu_period_ns\tcpu_is_generated\tmig_ui_clock\tmig_ui_period_ns\tblackboxes\tcpu_registers\troutable_nets\tfully_routed_nets\tcheckpoint_bytes\tcheckpoint_mtime"
puts $inputs [join [list [tsv_field $checkpoint] $part [tsv_field [get_property NAME $cpu]] \
    [get_property PERIOD $cpu] [get_property IS_GENERATED $cpu] [tsv_field [get_property NAME $ui]] \
    [get_property PERIOD $ui] [llength $blackboxes] [llength $registers] $routable $fully \
    [file size $checkpoint] [file mtime $checkpoint]] "\t"]
close $inputs
report_clocks -file [file join $out clocks.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing_summary.rpt]

set roots [discover_roots]
set roots_stream [open [file join $out discovered_roots.tsv] w]
puts $roots_stream "reference_family\tmatched_root_count\troot"
dict for {kind values} $roots {
    if {[llength $values] == 0} { puts $roots_stream "$kind\t0\tNA" }
    foreach value $values { puts $roots_stream "$kind\t[llength $values]\t[tsv_field $value]" }
}
close $roots_stream
set categories [dict create raw_cursor fetch_cursor core_pc fetch_cursor raw_slots frontend raw_hints frontend \
    frontend_cache frontend fetch_adapter frontend pmp_state pmp_frontend_rename vm_csr pmp_frontend_rename \
    irq_state retirement_ras head_state retirement_ras rename_ledger retirement_ras \
    ras_entries retirement_ras ras_control retirement_ras prf_ready issue_operand prf_values issue_operand \
    pending issue_operand issue_operands issue_operand issue_occupancy issue_operand \
    lsu_address lsu lsu_preparation lsu lsu_state lsu data_adapter fabric_cache translated_replies fabric_cache \
    coherent_cache fabric_cache page_walkers fabric_cache fabric fabric_cache other_registers other]
set family_names [dict keys $categories]
set cells_by_family {}
foreach family $family_names { dict set cells_by_family $family {} }
foreach cell $registers name [get_property NAME $registers] {
    set matched 0
    foreach family $family_names {
        if {$family eq "other_registers"} { continue }
        if {[family_matches $family $name $roots]} {
            dict lappend cells_by_family $family $cell
            set matched 1
        }
    }
    if {!$matched} { dict lappend cells_by_family other_registers $cell }
}
set register_stream [open [file join $out family_registers.tsv] w]
puts $register_stream "category\tfamily\tregister"
foreach family $family_names {
    foreach cell [dict get $cells_by_family $family] {
        puts $register_stream "[dict get $categories $family]\t$family\t[tsv_field [get_property NAME $cell]]"
    }
}
close $register_stream
set family_stream [open [file join $out endpoint_families.tsv] w]
set cut_stream [open [file join $out pipeline_cuts.tsv] w]
set summary_stream [open [file join $out group_summary.tsv] w]
set negative_stream [open [file join $out negative_clusters.tsv] w]
set group_header "category\tlabel\tfrom_family\tto_family\tsource_register_count\tsink_register_count\tendpoint_pin_kind\tendpoint_pin_count\treturned_path_count\tstatus"
set path_header "slack_ns\tdata_delay_ns\tlogic_levels\tstartpoint\tendpoint"
foreach stream [list $family_stream $cut_stream] { puts $stream "$group_header\trank\t$path_header" }
set worst_header "worst_slack_ns\tworst_data_delay_ns\tworst_logic_levels\tworst_startpoint\tworst_endpoint"
foreach stream [list $summary_stream $negative_stream] {
    puts $stream "kind\t$group_header\tnegative_returned_path_count\t$worst_header"
}
foreach family $family_names {
    emit_group $out family [dict get $categories $family] $family $cpu ANY_TIMED_STARTPOINT $family {} \
        [dict get $cells_by_family $family] data_enable $family_stream $summary_stream $negative_stream
}
# Dedicated source restrictions stop repeated IRQ->RAS/PRF bits from hiding
# PMP, cursor, operand-forwarding, LSU preparation and cache/fabric chains.
foreach {category label from_family to_family pin_kind} {
    fetch_cursor cursor_to_cursor raw_cursor raw_cursor data_enable
    fetch_cursor slots_to_cursor raw_slots raw_cursor data_enable
    fetch_cursor hints_to_cursor raw_hints raw_cursor data_enable
    fetch_cursor slots_to_core_pc raw_slots core_pc data_enable
    frontend frontend_to_slots frontend_cache raw_slots data_enable
    frontend adapter_to_frontend fetch_adapter frontend_cache data_enable
    frontend cursor_to_frontend raw_cursor frontend_cache data_enable
    frontend cursor_to_adapter raw_cursor fetch_adapter data_enable
    pmp_frontend_rename pmp_to_frontend pmp_state frontend_cache data_enable
    pmp_frontend_rename pmp_to_adapter pmp_state fetch_adapter data_enable
    pmp_frontend_rename pmp_to_slots pmp_state raw_slots data_enable
    pmp_frontend_rename pmp_to_rename pmp_state rename_ledger data_enable
    pmp_frontend_rename pmp_to_operands pmp_state issue_operands data_enable
    pmp_frontend_rename vm_csr_to_adapter vm_csr fetch_adapter data_enable
    retirement_ras irq_to_ras_ce irq_state ras_entries ce
    retirement_ras head_to_ras_ce head_state ras_entries ce
    retirement_ras ledger_to_ras_ce rename_ledger ras_entries ce
    retirement_ras irq_to_ras_control irq_state ras_control data_enable
    retirement_ras irq_to_prf irq_state prf_values data_enable
    retirement_ras irq_to_cursor irq_state raw_cursor data_enable
    retirement_ras prf_to_ras_data prf_values ras_entries d
    issue_operand ready_to_operands prf_ready issue_operands data_enable
    issue_operand prf_to_operands prf_values issue_operands data_enable
    issue_operand operands_to_prf issue_operands prf_values data_enable
    issue_operand operands_to_pending issue_operands pending data_enable
    issue_operand operands_to_operands issue_operands issue_operands data_enable
    issue_operand irq_to_occupancy irq_state issue_occupancy data_enable
    lsu ready_to_lsu_address prf_ready lsu_address data_enable
    lsu prf_to_lsu_address prf_values lsu_address data_enable
    lsu preparation_to_address lsu_preparation lsu_address data_enable
    lsu lsu_address_to_adapter lsu_address data_adapter data_enable
    lsu lsu_address_to_cache lsu_address coherent_cache data_enable
    lsu lsu_to_preparation lsu_state lsu_preparation data_enable
    lsu pmp_to_data_adapter pmp_state data_adapter data_enable
    fabric_cache adapter_to_cache data_adapter coherent_cache data_enable
    fabric_cache cache_to_adapter coherent_cache data_adapter data_enable
    fabric_cache cache_to_replies coherent_cache translated_replies data_enable
    fabric_cache fabric_to_cache fabric coherent_cache data_enable
    fabric_cache walkers_to_adapter page_walkers data_adapter data_enable
    fabric_cache walkers_to_fetch page_walkers fetch_adapter data_enable
} {
    emit_group $out cut $category $label $cpu $from_family $to_family \
        [dict get $cells_by_family $from_family] [dict get $cells_by_family $to_family] \
        $pin_kind $cut_stream $summary_stream $negative_stream
}
foreach stream [list $family_stream $cut_stream $summary_stream $negative_stream] { close $stream }
set notes [open [file join $out query_scope.txt] w]
puts $notes {Exactly one fully routed board DCP was opened. Correct part, no black boxes, existing generated CPU 100 MHz clock and real MIG UI 250 MHz clock were required.}
puts $notes {No constraint, clock, exception, RTL or physical design was modified. No optimized/placed/routed design, DCP or bitstream was produced.}
puts $notes {All family register sets are restricted to the real CPU clock. Source cuts are CPU register-to-register setup queries; cross-clock/MIG timing remains visible in the unchanged global timing summary.}
puts $notes {Each group reports at most five setup paths with one worst path per endpoint pin. Returned path count and negative-returned count are not total failing endpoint counts.}
puts $notes {Families may overlap. Exact matched register names and discovered roots are archived; other_registers covers CPU registers unmatched by the named families.}
puts $notes {Endpoint queries include FF D/CE, memory address/write/enable pins and non-clock/non-reset input pins of CPU-clocked DSP registers. Asynchronous reset/preset/clear recovery/removal and board I/O are not included in these family setup queries.}
puts $notes {Empty source/sink/pin/timing groups explicitly report 0 paths and NA metrics. Empty groups never establish timing improvement.}
puts $notes {negative_clusters.tsv is a capped diagnostic index, not complete path enumeration or release signoff. Setup/hold/pulse, CDC, bus skew, bitstream DRC and on-board stability require their separate release gates.}
close $notes
close_design
puts "BOARD_THROUGHPUT_CUT_QUERY: COMPLETE $out"
exit
