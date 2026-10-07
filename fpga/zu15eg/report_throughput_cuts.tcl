# Read-only, same-constraint queries of two linked SoC synthesis checkpoints.
# No opt/place/route/write_checkpoint, and no routed/board/Fmax signoff claim.
# Usage: BASELINE_SOC_DCP CANDIDATE_SOC_DCP FRESH_OUTPUT_DIRECTORY

proc tsv_field {value} {
    return [string map [list "\t" " " "\n" " " "\r" " "] $value]
}
proc safe_property {property object {fallback NA}} {
    if {[catch {get_property $property $object} value] || $value eq ""} { return $fallback }
    return $value
}
proc path_fields {path} {
    set fields {}
    foreach property {SLACK STARTPOINT_PIN ENDPOINT_PIN LOGIC_LEVELS DATAPATH_DELAY} {
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
    set references [dict create backend {IntegerBackend} issue {IssueExecuteStage} \
        raw {RegisteredFetchPacket} owner_ready {OwnerOperandReady} ledger {RenameRob} \
        multiply {PipelinedMultiply} divide {MultiplyDivide} ras {RetirementReturnStack} \
        fetch_adapter {InstructionTranslationAdapter WordInstructionTranslationAdapter} \
        frontend {SynchronousFetch InstructionLineCache InstructionLinePrefetch} \
        translation {SvTranslationService}]
    set result {}
    dict for {kind prefixes} $references { dict set result $kind {} }
    foreach cell [get_cells -quiet -hier -filter {IS_PRIMITIVE == 0}] {
        set name [get_property NAME $cell]
        dict for {kind prefixes} $references {
            set matched 0
            foreach property {REF_NAME ORIG_REF_NAME} {
                set reference [safe_property $property $cell ""]
                foreach prefix $prefixes {
                    if {[string match "$prefix*" $reference]} {
                        dict set result $kind $name 1
                        set matched 1
                        break
                    }
                }
                if {$matched} { break }
            }
        }
    }
    dict for {kind values} $result { dict set result $kind [dict keys $values] }
    return $result
}
proc family_matches {family name reference roots} {
    # Rebuilt hierarchy may prepend a top instance or rename module instances.
    # Use discovered reference roots plus leaf/segment patterns, never a fixed
    # complete CPU path or bit number. Report missing matches explicitly.
    set leaf [lindex [split $name /] end]
    set backend [expr {[under_roots $name [dict get $roots backend]] ||
        [regexp -nocase {(^|/)[^/]*backend(/|_)} $name]}]
    set issue [expr {[under_roots $name [dict get $roots issue]] ||
        [regexp -nocase {(^|/)(executionStages|execution_stage|IssueExecuteStage)[^/]*/} $name]}]
    set raw [expr {[under_roots $name [dict get $roots raw]] ||
        [regexp -nocase {(^|/)(fetchPacket|RegisteredFetchPacket)[^/]*/} $name]}]
    set fetch [expr {[under_roots $name [dict get $roots fetch_adapter]] ||
        [regexp -nocase {(^|/)(fetchAdapter|InstructionTranslationAdapter|WordInstructionTranslationAdapter)(/|_)} $name]}]
    set multiply [expr {[under_roots $name [dict get $roots multiply]] ||
        [regexp -nocase {(^|/)(multiplier|PipelinedMultiply)[^/]*/} $name]}]
    set divide [expr {[under_roots $name [dict get $roots divide]] ||
        [regexp -nocase {(^|/)(mulDiv|MultiplyDivide)[^/]*/} $name]}]
    set ras [expr {[under_roots $name [dict get $roots ras]] ||
        [regexp -nocase {(^|/)(returnStack|RetirementReturnStack)[^/]*/} $name]}]
    switch -- $family {
        ready {
            return [expr {$backend && [regexp -nocase {(^|/)ready(_|\[|_reg)} $name]}]
        }
        owner_ready {
            return [expr {[under_roots $name [dict get $roots owner_ready]] ||
                [regexp -nocase {(^|/)(ownerReady|OwnerOperandReady)[^/]*/} $name]}]
        }
        prf_values {
            return [expr {$backend && [regexp -nocase {(^|/)values(_|\[|_reg)} $name]}]
        }
        pending {
            return [expr {$backend && [regexp -nocase {(^|/)pending(_|\[|_reg)} $name]}]
        }
        issue_operands {
            return [expr {$issue && [regexp -nocase {(^|/)payload(_reg|\[|/)} $name]}]
        }
        issue_occupancy {
            return [expr {$issue && [regexp -nocase {(^|/)occupied(_reg|\[|/)} $name]}]
        }
        raw_slots {
            return [expr {$raw && [regexp -nocase {(^|/)slots(_|\[|_reg)} $name]}]
        }
        raw_hints {
            return [expr {$raw && [regexp -nocase {(^|/)hint(Valid|Pc|Instruction|NextPc|Aligned|Different)(_|\[|_reg)} $name]}]
        }
        raw_cursor {
            return [expr {$raw && [regexp -nocase {(^|/)(supplyPc|count)(_reg|\[|/)} $name]}]
        }
        core_pc {
            return [regexp -nocase {(^|/)pc_reg($|\[|/|_)} $name]
        }
        rename_ledger {
            return [expr {[under_roots $name [dict get $roots ledger]] ||
                ($backend && [regexp -nocase {(^|/)(ledger|renameRob|RenameRob)(/|_)} $name])}]
        }
        ras_entries {
            return [expr {$ras && [regexp -nocase {^entries(_reg|\[|_|$)} $leaf]}]
        }
        ras_control {
            return [expr {$ras && [regexp -nocase {^(top|count)(_reg|\[|_|$)} $leaf]}]
        }
        store_preparation {
            return [expr {$backend && [regexp -nocase {^(storeAddress(Known)?|storeEnd|storeSafeRange|storeData|storePrepared)(_reg|\[|_|$)} $leaf]}]
        }
        multiply {
            return $multiply
        }
        multiply_input {
            # Partial products may be absorbed into DSP output registers.
            # Include those primitives, not just surviving FF metadata.
            return [expr {$multiply && ([string match DSP* $reference] ||
                [regexp -nocase {^(partial(_reg|\[|_|$)|(correction|high|word|slots|tags|valid)(_?0(_reg|\[|_|$)|_reg\[0\]|\[0\]))} $leaf])}]
        }
        multiply_dsp {
            return [expr {$multiply && [string match DSP* $reference]}]
        }
        divide {
            return $divide
        }
        divide_input {
            return [expr {$divide && [regexp -nocase {^(request|left|right|state)(_reg|\[|_|$)} $leaf]}]
        }
        lsu_address {
            return [expr {$backend &&
                ([regexp -nocase {(^|/)(lsu|ParallelLoadStoreUnit|LoadStoreUnit)(/|_)} $name] ||
                 [regexp -nocase {(^|/)(stagedMemory|storeAddress|storeEnd|storeSafeRange|storeData|storePrepared|loadBeat|loadLanes)} $name])}]
        }
        frontend_cache {
            return [expr {[under_roots $name [dict get $roots frontend]] ||
                [regexp -nocase {(^|/)(frontend|fetchCache|fetchAdapter|InstructionLineCache|InstructionLinePrefetch)(/|_)} $name]}]
        }
        fetch_adapter {
            return $fetch
        }
        fetch_virtual {
            return [expr {$fetch && [regexp -nocase {^(virtualPc|secondVirtualPc)(_reg|\[|_|$)} $leaf]}]
        }
        fetch_physical {
            return [expr {$fetch && [regexp -nocase {^(firstPhysical|secondPhysical|physicalPc)(_reg|\[|_|$)} $leaf]}]
        }
        fetch_permission {
            return [expr {$fetch &&
                [regexp -nocase {^(allowed|physicalMask|errors|pageFaults|permissionCaptured|secondPageFault|secondAccessFault|requested|state|issued)(_reg|\[|_|$)} $leaf]}]
        }
        pmp_state {
            return [regexp -nocase {(^|/|_)pmp(Cfg|Addr|State)(_|[[]|_reg)} $name]
        }
        translation {
            return [expr {[under_roots $name [dict get $roots translation]] ||
                [regexp -nocase {(^|/)(translation|SvTranslationService)[^/]*/} $name]}]
        }
        fabric {
            return [regexp -nocase {(^|/)(physicalData|coherentCache|coherentHome|dataCache|bridge|crossbar|adapter|responses|checked|router|bankRouter|home|sharedData)[^/]*/} $name]
        }
        clocked_dsp {
            return [string match DSP* $reference]
        }
        clocked_memories {
            return [expr {[string match RAMB* $reference] || [string match URAM* $reference]}]
        }
        default { error "Unknown endpoint family: $family" }
    }
}
proc endpoint_pins {cells {kind data_enable}} {
    if {[llength $cells] == 0} { return {} }
    switch -- $kind {
        ce { return [get_pins -quiet -of_objects $cells -filter {DIRECTION == IN && REF_PIN_NAME == CE}] }
        d { return [get_pins -quiet -of_objects $cells -filter {DIRECTION == IN && REF_PIN_NAME == D}] }
        data_enable {
            set pins [get_pins -quiet -of_objects $cells -filter {DIRECTION == IN &&
                (REF_PIN_NAME == D || REF_PIN_NAME == CE || REF_PIN_NAME =~ ADDR* ||
                 REF_PIN_NAME =~ DI* || REF_PIN_NAME =~ EN* || REF_PIN_NAME =~ REGCE* ||
                 REF_PIN_NAME =~ WE* || REF_PIN_NAME =~ BW* || REF_PIN_NAME =~ OREG_CE* ||
                 REF_PIN_NAME =~ IREG_CE* || REF_PIN_NAME =~ RDB_WR*)}]
            # Never lsort or {*} a large Vivado collection: doing so may
            # convert through its 500-object display limit and silently omit
            # most endpoints. Read each NAME separately into an ordinary dict.
            set names {}
            foreach pin $pins { dict set names [get_property NAME $pin] 1 }
            set dsps [filter $cells {REF_NAME =~ DSP*}]
            if {[llength $dsps] > 0} {
                foreach pin [get_pins -quiet -of_objects $dsps -filter {
                    DIRECTION == IN && REF_PIN_NAME != CLK && REF_PIN_NAME !~ RST*}] {
                    dict set names [get_property NAME $pin] 1
                }
            }
            return [dict keys $names]
        }
        default { error "Unknown endpoint pin kind: $kind" }
    }
}
proc clocked_cells {clock} {
    set names {}
    foreach cell [all_registers -clock [get_clocks $clock] -cells] {
        dict set names [get_property NAME $cell] $cell
    }
    # Explicitly retain CPU-clocked inferred DSP/BRAM/UltraRAM even if their
    # particular internal register configuration is absent from all_registers.
    foreach cell [get_cells -quiet -hier -filter {
        REF_NAME =~ DSP* || REF_NAME =~ RAMB* || REF_NAME =~ URAM*}] {
        set clock_pins [get_pins -quiet -of_objects $cell -filter {
            REF_PIN_NAME == CLK || REF_PIN_NAME == CLKARDCLK || REF_PIN_NAME == CLKBWRCLK ||
            REF_PIN_NAME == CLKA || REF_PIN_NAME == CLKB}]
        if {[llength $clock_pins] == 0} { continue }
        foreach driving_clock [get_clocks -quiet -of_objects $clock_pins] {
            if {[get_property NAME $driving_clock] eq $clock} {
                dict set names [get_property NAME $cell] $cell
                break
            }
        }
    }
    return [dict values $names]
}
proc query_paths {clock pins {from_cells {}}} {
    if {[llength $pins] == 0} { return {} }
    set options [list -quiet -group $clock -delay_type max -to $pins -max_paths 5 -nworst 1]
    if {[llength $from_cells] > 0} { lappend options -from $from_cells }
    return [get_timing_paths {*}$options]
}
proc report_path_set {directory label clock pins from_cells paths} {
    if {[llength $paths] == 0} {
        set stream [open [file join $directory [format %s_paths.rpt $label]] w]
        puts $stream {0 matched timing paths. No timing improvement is established by an empty group.}
        close $stream
        return
    }
    set options [list -group $clock -delay_type max -to $pins -max_paths 5 -nworst 1 -input_pins]
    if {[llength $from_cells] > 0} { lappend options -from $from_cells }
    report_timing {*}$options -file [file join $directory [format %s_paths.rpt $label]]
}
proc summarize_paths {paths} {
    if {[llength $paths] == 0} { return [dict create path_count 0 slack NA startpoint NA endpoint NA logic_levels NA data_delay NA] }
    lassign [path_fields [lindex $paths 0]] slack startpoint endpoint logic_levels data_delay
    return [dict create path_count [llength $paths] slack $slack startpoint $startpoint endpoint $endpoint \
        logic_levels $logic_levels data_delay $data_delay]
}
proc inspect_design {label checkpoint directory family_names summary_stream top_stream family_stream cut_stream} {
    file mkdir $directory
    open_checkpoint $checkpoint
    set old_clocks [get_clocks -quiet]
    if {[llength $old_clocks] != 0} {
        error "$label input is not the expected clock-free linked soc_candidate.dcp"
    }
    set blackboxes [get_cells -quiet -hier -filter {IS_BLACKBOX}]
    if {[llength $blackboxes] != 0} { error "$label has unresolved black boxes: $blackboxes" }
    set rom_brams {}
    foreach cell [get_cells -quiet -hier -filter {REF_NAME =~ RAMB36* || REF_NAME =~ RAMB18*}] {
        set name [get_property NAME $cell]
        if {[regexp -nocase {(^|/)(rom|bootRom|boot_rom|blk_mem_gen[^/]*)(/|_)} $name]} {
            lappend rom_brams $cell
        }
    }
    if {[llength $rom_brams] == 0} {
        error "$label has no real RAMB primitives under a ROM/BMG hierarchy"
    }
    set clock_port [get_ports -quiet clock]
    if {[llength $clock_port] != 1} { error "$label must have exactly one top-level clock port" }
    set clock throughput_query_clock
    create_clock -name $clock -period 10.000 [lindex $clock_port 0]
    set registers [clocked_cells $clock]
    if {[llength $registers] == 0} { error "$label temporary query clock reaches no registers" }
    puts $summary_stream [join [list $label [tsv_field $checkpoint] 10.000 [llength $blackboxes] [llength $rom_brams] \
        [llength $registers] [file size $checkpoint] [file mtime $checkpoint]] "\t"]
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $directory timing_summary.rpt]
    report_utilization -file [file join $directory utilization.rpt]
    report_timing -group $clock -delay_type max -max_paths 100 -nworst 1 -input_pins \
        -file [file join $directory top100_paths.rpt]
    set top_paths [get_timing_paths -quiet -group $clock -delay_type max -max_paths 100 -nworst 1]
    set rank 0
    foreach path $top_paths {
        puts $top_stream [join [concat [list $label [incr rank]] [path_fields $path]] "\t"]
    }
    set result [dict create overall [summarize_paths $top_paths]]
    set roots [discover_roots]
    set roots_stream [open [file join $directory discovered_roots.tsv] w]
    puts $roots_stream "reference_family\tmatched_root_count\troot"
    dict for {kind values} $roots {
        if {[llength $values] == 0} { puts $roots_stream "$kind\t0\tNA" }
        foreach value $values { puts $roots_stream "$kind\t[llength $values]\t[tsv_field $value]" }
    }
    close $roots_stream
    set cells_by_family {}
    foreach family $family_names { dict set cells_by_family $family {} }
    foreach cell $registers {
        set name [get_property NAME $cell]
        set reference [safe_property REF_NAME $cell ""]
        set matched 0
        foreach family $family_names {
            if {$family eq "other_registers"} { continue }
            if {[family_matches $family $name $reference $roots]} {
                dict lappend cells_by_family $family $cell
                set matched 1
            }
        }
        if {!$matched} { dict lappend cells_by_family other_registers $cell }
    }
    set register_stream [open [file join $directory family_registers.tsv] w]
    puts $register_stream "family\tregister"
    foreach family $family_names {
        set cells [dict get $cells_by_family $family]
        foreach cell $cells { puts $register_stream "$family\t[tsv_field [get_property NAME $cell]]" }
        set pins [endpoint_pins $cells]
        set paths [query_paths $clock $pins]
        set status [expr {[llength $cells] == 0 ? "EMPTY_NO_REGISTERS" :
            ([llength $pins] == 0 ? "EMPTY_NO_ENDPOINT_PINS" :
            ([llength $paths] == 0 ? "EMPTY_NO_TIMED_PATHS" : "MATCHED"))}]
        set stats [summarize_paths $paths]
        dict set result "family:$family" $stats
        set rank 0
        if {[llength $paths] == 0} {
            puts $family_stream [join [list $label $family [llength $cells] [llength $pins] 0 $status 0 NA NA NA NA NA] "\t"]
        } else {
            foreach path $paths {
                puts $family_stream [join [concat [list $label $family [llength $cells] [llength $pins] \
                    [llength $paths] $status [incr rank]] [path_fields $path]] "\t"]
            }
        }
        report_path_set $directory $family $clock $pins {} $paths
    }
    close $register_stream
    # These source-to-sink cuts distinguish the old unregistered chain from
    # both sides of the new pipeline, and include ALU forwarding to the next
    # operand slot. A missing old stage is recorded as 0 paths / NA slack.
    foreach {cut from_family to_family pin_kind} {
        ready_to_prf_values ready prf_values data_enable
        ready_to_pending ready pending data_enable
        ready_to_issue_operands ready issue_operands data_enable
        prf_values_to_issue_operands prf_values issue_operands data_enable
        issue_operands_to_prf_values issue_operands prf_values data_enable
        issue_operands_to_pending issue_operands pending data_enable
        issue_operands_to_issue_operands issue_operands issue_operands data_enable
        ready_to_owner_ready ready owner_ready data_enable
        owner_ready_to_store owner_ready store_preparation data_enable
        owner_ready_to_multiply owner_ready multiply_input data_enable
        owner_ready_to_divide owner_ready divide_input data_enable
        ready_to_store ready store_preparation data_enable
        prf_values_to_store prf_values store_preparation data_enable
        store_to_store store_preparation store_preparation data_enable
        ledger_to_store rename_ledger store_preparation data_enable
        ready_to_multiply ready multiply_input data_enable
        prf_values_to_multiply prf_values multiply_input data_enable
        prf_values_to_multiply_dsp prf_values multiply_dsp data_enable
        pending_to_multiply pending multiply_input data_enable
        ready_to_divide ready divide_input data_enable
        prf_values_to_divide prf_values divide_input data_enable
        pending_to_divide pending divide_input data_enable
        virtual_to_translation fetch_virtual translation data_enable
        virtual_to_fetch_pa fetch_virtual fetch_physical data_enable
        virtual_to_fetch_permission fetch_virtual fetch_permission data_enable
        translation_to_fetch_pa translation fetch_physical data_enable
        translation_to_fetch_permission translation fetch_permission data_enable
        fetch_pa_to_permission fetch_physical fetch_permission data_enable
        pmp_to_fetch_permission pmp_state fetch_permission data_enable
        adapter_to_frontend fetch_adapter frontend_cache data_enable
        raw_slots_to_pc raw_slots core_pc data_enable
        frontend_to_raw_slots frontend_cache raw_slots data_enable
        cursor_to_cursor raw_cursor raw_cursor data_enable
        cursor_to_frontend raw_cursor frontend_cache data_enable
        ledger_to_ras_ce rename_ledger ras_entries ce
        ledger_to_ras_control rename_ledger ras_control data_enable
        prf_values_to_ras_data prf_values ras_entries d
        prf_values_to_all_dsp prf_values clocked_dsp data_enable
        fabric_to_memories fabric clocked_memories data_enable
    } {
        set sources [dict get $cells_by_family $from_family]
        set sinks [dict get $cells_by_family $to_family]
        set pins [endpoint_pins $sinks $pin_kind]
        set paths {}
        if {[llength $sources] > 0 && [llength $pins] > 0} {
            set paths [query_paths $clock $pins $sources]
        }
        set status [expr {[llength $sources] == 0 ? "EMPTY_NO_SOURCE_REGISTERS" :
            ([llength $sinks] == 0 ? "EMPTY_NO_SINK_REGISTERS" :
            ([llength $pins] == 0 ? "EMPTY_NO_ENDPOINT_PINS" :
            ([llength $paths] == 0 ? "EMPTY_NO_TIMED_PATHS" : "MATCHED")))}]
        dict set result "cut:$cut" [summarize_paths $paths]
        set rank 0
        if {[llength $paths] == 0} {
            puts $cut_stream [join [list $label $cut $from_family $to_family [llength $sources] [llength $sinks] \
                [llength $pins] 0 $status 0 NA NA NA NA NA] "\t"]
        } else {
            foreach path $paths {
                puts $cut_stream [join [concat [list $label $cut $from_family $to_family [llength $sources] \
                    [llength $sinks] [llength $pins] [llength $paths] $status [incr rank]] [path_fields $path]] "\t"]
            }
        }
        report_path_set $directory $cut $clock $pins $sources $paths
    }
    close_design
    return $result
}

if {$argc != 3} { error {usage: BASELINE_SOC_DCP CANDIDATE_SOC_DCP FRESH_OUTPUT_DIRECTORY} }
lassign $argv baseline candidate out
set baseline [file normalize $baseline]
set candidate [file normalize $candidate]
set out [file normalize $out]
foreach checkpoint [list $baseline $candidate] {
    if {![file isfile $checkpoint]} { error "Checkpoint missing: $checkpoint" }
}
if {[file exists $out]} {
    if {![file isdirectory $out]} { error {Output must be a fresh directory} }
    foreach entry [glob -nocomplain -directory $out * .*] {
        if {[file tail $entry] ni {. ..}} {
            error {Use a fresh output directory; never overwrite timing evidence}
        }
    }
}
file mkdir $out
set_param general.maxThreads 8
set family_names {ready owner_ready prf_values pending issue_operands issue_occupancy \
    raw_slots raw_hints raw_cursor core_pc rename_ledger ras_entries ras_control \
    store_preparation multiply multiply_input multiply_dsp divide divide_input \
    lsu_address frontend_cache fetch_adapter fetch_virtual fetch_physical fetch_permission \
    pmp_state translation fabric clocked_dsp clocked_memories other_registers}
set summary_stream [open [file join $out inputs.tsv] w]
puts $summary_stream "design\tcheckpoint\tquery_period_ns\tblackboxes\treal_rom_ramb_count\tclocked_registers\tcheckpoint_bytes\tcheckpoint_mtime"
set top_stream [open [file join $out top100_paths.tsv] w]
puts $top_stream "design\trank\tslack\tstartpoint\tendpoint\tlogic_levels\tdata_delay"
set family_stream [open [file join $out endpoint_families.tsv] w]
puts $family_stream "design\tfamily\tregister_count\tendpoint_pin_count\tpath_count\tstatus\trank\tslack\tstartpoint\tendpoint\tlogic_levels\tdata_delay"
set cut_stream [open [file join $out pipeline_cuts.tsv] w]
puts $cut_stream "design\tcut\tfrom_family\tto_family\tsource_register_count\tsink_register_count\tendpoint_pin_count\tpath_count\tstatus\trank\tslack\tstartpoint\tendpoint\tlogic_levels\tdata_delay"
set old [inspect_design baseline $baseline [file join $out baseline] $family_names \
    $summary_stream $top_stream $family_stream $cut_stream]
set new [inspect_design candidate $candidate [file join $out candidate] $family_names \
    $summary_stream $top_stream $family_stream $cut_stream]
foreach stream [list $summary_stream $top_stream $family_stream $cut_stream] { close $stream }
set comparison [open [file join $out comparisons.tsv] w]
puts $comparison "group\tbaseline_path_count\tcandidate_path_count\tbaseline_slack\tcandidate_slack\tcandidate_minus_baseline_slack\tbaseline_logic_levels\tcandidate_logic_levels\tbaseline_data_delay\tcandidate_data_delay"
foreach group [dict keys $old] {
    set a [dict get $old $group]
    set b [dict get $new $group]
    set delta NA
    if {[dict get $a path_count] > 0 && [dict get $b path_count] > 0 &&
        [string is double -strict [dict get $a slack]] && [string is double -strict [dict get $b slack]]} {
        set delta [format %.6f [expr {[dict get $b slack] - [dict get $a slack]}]]
    }
    puts $comparison [join [list $group [dict get $a path_count] [dict get $b path_count] \
        [dict get $a slack] [dict get $b slack] $delta [dict get $a logic_levels] [dict get $b logic_levels] \
        [dict get $a data_delay] [dict get $b data_delay]] "\t"]
}
close $comparison
set notes [open [file join $out query_scope.txt] w]
puts $notes {Both original checkpoints were opened read-only, required clock-free and black-box-free, and checked for real ROM/BMG RAMB primitives.}
puts $notes {A temporary 10 ns top-level query clock was created independently for each input. No design checkpoint was written.}
puts $notes {Reports use post-synthesis timing estimates; they are not routed timing, physical-board verification or a maximum-frequency claim.}
puts $notes {issue_operands includes the execution payload registers (operands plus instruction/owner metadata); issue_occupancy is reported separately.}
puts $notes {Each endpoint family and source-to-sink cut reports up to five paths, with exact matched register names in each design's family_registers.tsv.}
puts $notes {Clocked cell sets include CPU-clocked FFs, DSPs, BRAMs and UltraRAMs. Non-clock/non-reset DSP inputs and memory address/data/write/enable pins are included; asynchronous recovery/removal and board I/O are not family setup endpoints.}
puts $notes {Reference roots are discovered and archived per design. Each Vivado collection object's NAME is read independently; no large collection is expanded through lsort or {*} display conversion.}
puts $notes {clocked_dsp and clocked_memories cover all such CPU-clocked primitives even when they also match named modules; other_registers covers any remaining unmatched CPU-clocked cells. Families intentionally overlap.}
puts $notes {owner_ready isolates the new owner-local readiness registers; store_preparation and multiply/divide input cuts retain their original late grant authorization while exposing independent operand payload paths.}
puts $notes {fetch_physical includes legacy physicalPc and new firstPhysical/secondPhysical. Compare virtual/TLB-to-permission with TLB-to-PA and registered-PA-to-permission; old absent owner-ready/DSP/stage families remain 0 paths / NA metrics.}
puts $notes {RAS CE/control and data cuts are separate. Capped family/path counts are diagnostic, not the total failing endpoints or a release/signoff decision.}
puts $notes {Families may overlap. Empty groups explicitly have path_count=0 and slack/data_delay=NA; no improvement may be inferred from an empty group.}
puts $notes {Compare baseline ready_to_prf_values/ready_to_pending with candidate ready_to_issue_operands and candidate issue_operands_to_prf_values/issue_operands_to_pending.}
puts $notes {Also inspect candidate issue_operands_to_issue_operands: forwarding and slot replacement must not recreate the old serial execution chain.}
close $notes
puts "THROUGHPUT_CUT_QUERY: COMPLETE $out"
exit
