# Read-only audit of one routed I1 OOC candidate. No clocks/exceptions changed.
if {$argc != 3} { error "usage: report_route_optimization.tcl PACKAGE ROUTED_DCP FRESH_OUTPUT" }
lassign $argv package checkpoint output
foreach name {package checkpoint output} { set $name [file normalize [set $name]] }
if {[file exists $output]} { error "preserve existing physical reports" }
file mkdir $output
set_param general.maxThreads 8
open_checkpoint $checkpoint
if {[get_property TOP [current_design]] ne "FiveStageFpgaShell" ||
    [string tolower [get_property PART [current_design]]] ne "xczu15eg-ffvb1156-2-i"} {
    error "wrong independent I1 shell/part"
}
set cpu [get_clocks orbital_i1_cpu]
if {[llength $cpu] != 1 || abs([get_property PERIOD $cpu] - 3.333) > 0.0005} {
    error "300MHz target changed"
}
set actual [lsort [get_property NAME [get_clocks]]]
set expected [lsort {orbital_i1_cpu valence_bscan_tck valence_bscan_drck valence_bscan_update}]
if {$actual ne $expected} { error "clock set changed: $actual" }
foreach name {valence_bscan_tck valence_bscan_drck valence_bscan_update} {
    if {abs([get_property PERIOD [get_clocks $name]] - 50.000) > 0.000001} {
        error "USER2 clock period changed"
    }
}
source [file join $package bscan_timing.tcl]
set primitive [get_property NAME [get_cells -hierarchical -filter {REF_NAME == BSCANE2}]]
if {![regsub {([/.])user_scan$} $primitive {\1transport} engine]} { error "USER2 sibling shape" }
valence_assert_jtag_chain 2 $primitive
# This procedure checks structure/functional reset fences, without setting constraints.
valence_bscan_qualifiers $primitive $engine
report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose \
    -file [file join $output timing_summary.rpt]
report_clocks -file [file join $output clocks.rpt]
report_clock_interaction -file [file join $output clock_interaction.rpt]
report_exceptions -coverage -file [file join $output exceptions.rpt]
report_bus_skew -file [file join $output bus_skew.rpt]
check_timing -verbose -file [file join $output check_timing.rpt]
report_route_status -file [file join $output route_status.rpt]
report_drc -file [file join $output drc.rpt]
report_utilization -hierarchical -file [file join $output utilization.rpt]
foreach {name from to kind} [list \
    setup_global {} {} max hold_global {} {} min \
    setup_internal [all_registers] [all_registers] max \
    hold_internal [all_registers] [all_registers] min \
    setup_cpu $cpu $cpu max hold_cpu $cpu $cpu min] {
    set path [file join $output "$name.rpt"]
    if {$from eq ""} {
        report_timing -delay_type $kind -max_paths 40 -nworst 1 -file $path
        set worst [get_timing_paths -delay_type $kind -max_paths 1]
    } else {
        report_timing -from $from -to $to -delay_type $kind -max_paths 40 -nworst 1 -file $path
        set worst [get_timing_paths -from $from -to $to -delay_type $kind -max_paths 1]
    }
    if {[llength $worst] != 1} { error "missing routed timing scope $name" }
    puts "I1_ROUTED_PATH scope=$name slack=[get_property SLACK $worst]"
}
foreach {name pattern} {
    csr soc/core/core/csr/*
    instruction_translation soc/core/it/*
    data_translation soc/core/dt/*
    dcache soc/core/dcache/*
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
    set endpoints [get_cells -quiet -hierarchical -filter "IS_SEQUENTIAL == 1 && NAME =~ $pattern"]
    if {[llength $endpoints] == 0} { error "missing routed unit $name" }
    report_timing -from $cpu -to $endpoints -delay_type max -max_paths 8 -nworst 1 \
        -file [file join $output "setup_$name.rpt"]
}
puts "I1_ROUTE_OPTIMIZATION_REPORT_DONE NO_CLOCK_OR_EXCEPTION_CHANGES NOT_BOARD_NO_BIT"
close_design
