# Supplemental unit reports from one unchanged constrained checkpoint.
# No synthesis, placement, routing, clock changes or timing exceptions.
if {$argc != 2} { error "usage: report_selected_units.tcl CONSTRAINED_DCP REPORT_ROOT" }
set checkpoint [file normalize [lindex $argv 0]]
set output [file normalize [lindex $argv 1]]
if {![file isdirectory $output]} { error "completed report directory required" }
set_param general.maxThreads 8
open_checkpoint $checkpoint
foreach {name pattern} {
    fp_arithmetic_s soc/core/core/execute/I1FloatingPointSharedArithmeticS/*
    fp_arithmetic_d soc/core/core/execute/I1FloatingPointSharedArithmeticD/*
    fp_misc_s soc/core/core/execute/I1FloatingPointMiscS/*
    fp_misc_d soc/core/core/execute/I1FloatingPointMiscD/*
    core_recovery soc/core/core/architecturalNextPc_reg*
    icache soc/core/icache/*
    fetch_aligner soc/core/aligner/cuts/*
    decode_stage soc/core/core/rrPacket_*
    execute_stage soc/core/core/exPacket_*
    operand_hold soc/core/core/held*
    address_stage soc/core/core/addrPacket_*
    completion_stage soc/core/core/cmpPacket_*
} {
    set path [file join $output "setup_${name}_synth.rpt"]
    if {[file exists $path]} { error "preserve previous unit report: $name" }
    set endpoints [get_cells -quiet -hierarchical -filter "IS_SEQUENTIAL == 1 && NAME =~ $pattern"]
    if {[llength $endpoints] == 0} { error "missing timing unit: $name" }
    report_timing -from [get_clocks orbital_i1_cpu] -to $endpoints -delay_type max \
        -max_paths 10 -nworst 1 -file $path
}
puts "I1_SELECTED_UNIT_REPORTS_DONE NO_SYNTHESIS NO_CONSTRAINT_CHANGES"
close_design
