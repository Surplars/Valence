# Query the TWO existing constrained DCPs with IDENTICAL path sets.
# No synthesis, retiming, clock modification, placement, routing or exceptions.
if {$argc != 3} {
    error "usage: report_ex_wb_comparison.tcl BASELINE_DCP CURRENT_DCP FRESH_OUTPUT"
}
set baseline [file normalize [lindex $argv 0]]
set candidate [file normalize [lindex $argv 1]]
set output [file normalize [lindex $argv 2]]
if {[file exists $output]} { error "preserve previous EX/WB comparison evidence" }
file mkdir $output
set_param general.maxThreads 8
set numbers {}
foreach {name checkpoint} [list baseline $baseline current $candidate] {
    open_checkpoint $checkpoint
    if {[get_property TOP [current_design]] ne "FiveStageFpgaShell" ||
        [string tolower [get_property PART [current_design]]] ne "xczu15eg-ffvb1156-2-i"} {
        error "review comparison top/device mismatch"
    }
    set clock [get_clocks orbital_i1_cpu]
    set period [get_property PERIOD $clock]
    if {abs($period - 3.333) > 0.000001} { error "300MHz tool-rounded clock changed" }
    set folder [file join $output $name]
    file mkdir $folder
    set registers [get_cells -quiet -hierarchical -filter {
        IS_SEQUENTIAL == 1 && NAME =~ soc/core/core/addrPacket_result_reg*
    }]
    set endpoints [get_pins -quiet -of_objects $registers -filter {REF_PIN_NAME == D}]
    if {[llength $endpoints] < 32} { error "missing EX result D endpoints" }
    report_timing -from $clock -to $endpoints -delay_type max -max_paths 10 -nworst 1 \
        -file [file join $folder setup_ex_result_data_synth.rpt]
    set path [get_timing_paths -from $clock -to $endpoints -delay_type max -max_paths 1]
    set ex_wns [get_property SLACK $path]
    set starts [get_cells -quiet -hierarchical -filter {
        IS_SEQUENTIAL == 1 && (
            NAME =~ soc/core/core/wbPacket_control* || NAME =~ soc/core/core/wbValid_reg* ||
            NAME =~ soc/core/core/wbPacket_fault_reg* || NAME =~ soc/core/core/wbPacket_contextBarrier_reg* ||
            NAME =~ soc/core/core/wbRecovery_reg*
        )
    }]
    if {[llength $starts] == 0} { error "missing WB control startpoints" }
    report_timing -from $starts -to $clock -delay_type max -max_paths 10 -nworst 1 \
        -file [file join $folder setup_wb_control_synth.rpt]
    set path [get_timing_paths -from $starts -to $clock -delay_type max -max_paths 1]
    set wb_wns [get_property SLACK $path]
    set stage_numbers ""
    foreach {stage pattern} {
        decode_stage soc/core/core/rrPacket_*
        execute_stage soc/core/core/exPacket_*
        operand_hold soc/core/core/held*
        address_stage soc/core/core/addrPacket_*
        completion_stage soc/core/core/cmpPacket_*
    } {
        set targets [get_cells -quiet -hierarchical -filter "IS_SEQUENTIAL == 1 && NAME =~ $pattern"]
        if {[llength $targets] == 0} { error "missing stage comparison: $name/$stage" }
        report_timing -from $clock -to $targets -delay_type max -max_paths 10 -nworst 1 \
            -file [file join $folder "setup_${stage}_synth.rpt"]
        set path [get_timing_paths -from $clock -to $targets -delay_type max -max_paths 1]
        set stage_wns [get_property SLACK $path]
        append stage_numbers ",\"${stage}_wns_ns\":$stage_wns"
        puts "I1_STAGE_REPORT_ONLY name=$name stage=$stage wns=$stage_wns"
    }
    lappend numbers "\"$name\":{\"ex_result_data_wns_ns\":$ex_wns,\"wb_control_wns_ns\":$wb_wns$stage_numbers}"
    puts "I1_EX_WB_REPORT_ONLY name=$name period=$period ex_data_wns=$ex_wns wb_control_wns=$wb_wns checkpoint=$checkpoint"
    close_design
}
set result [open [file join $output result.json] w]
puts $result "{[join $numbers ,]}"
close $result
puts "I1_EX_WB_COMPARISON_DONE TWO_EXISTING_CHECKPOINTS NO_SYNTHESIS NO_CONSTRAINT_CHANGES"
