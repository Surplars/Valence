# Matched standalone MDU OOC pair. One synthesis/implementation per role, no board/bit.
if {$argc ni {3 4}} { error "usage: numerical_ooc.tcl PAIRED_RTL_ROOT FRESH_REPORT_ROOT PERIOD_NS ?candidate-only|default-only?" }
lassign $argv rtl output period selection
if {$argc == 4 && $selection ni {candidate-only default-only}} { error "explicit candidate-only or default-only selection required" }
set roles [expr {$argc == 4 ? [list [expr {$selection eq "default-only" ? "default" : "candidate"}]] : [list reference candidate]}]
set rtl [file normalize $rtl]
set output [file normalize $output]
set allowed [string tolower [file normalize E:/VM/Share/Valence-rtl/Valence-InOrder]]
foreach path [list $rtl $output] {
    if {![string match "${allowed}/*" [string tolower $path]]} { error "path outside designated simulation root" }
}
if {[file exists $output]} { error "fresh evidence root required" }
if {![string is double -strict $period] || $period <= 0.333} { error "explicit positive clock period required" }
file mkdir $output
set_param general.maxThreads 8
source [file join [file dirname [info script]] numerical_timing.tcl]
foreach role $roles {
    set folder [file join $output $role]
    file mkdir $folder
    set sources [lsort [glob -nocomplain -directory [file join $rtl $role] *.sv]]
    if {[llength $sources] == 0} { error "missing frozen RTL: $role" }
    create_project -in_memory -part xczu15eg-ffvb1156-2-i
    read_verilog -sv $sources
    # Defer object queries in an XDC so synthesis sees the same real-clock
    # contract; get_ports cannot query a design before elaboration.
    set xdc [open [file join $folder module_context.xdc] w]
    puts $xdc [format {create_clock -name i1_mdu_clock -period %s [get_ports clock]} $period]
    puts $xdc {set_clock_uncertainty -setup 0.100 [get_clocks i1_mdu_clock]}
    puts $xdc {set_input_delay -clock i1_mdu_clock -max 0.333 [get_ports -filter {DIRECTION == IN && NAME != clock}]}
    puts $xdc {set_input_delay -clock i1_mdu_clock -min 0.000 [get_ports -filter {DIRECTION == IN && NAME != clock}]}
    puts $xdc {set_output_delay -clock i1_mdu_clock -max 0.333 [get_ports -filter {DIRECTION == OUT}]}
    puts $xdc {set_output_delay -clock i1_mdu_clock -min 0.000 [get_ports -filter {DIRECTION == OUT}]}
    close $xdc
    read_xdc [file join $folder module_context.xdc]
    synth_design -top FiveStageMulDiv -part xczu15eg-ffvb1156-2-i -mode out_of_context \
        -flatten_hierarchy rebuilt -directive Default
    write_checkpoint [file join $folder synthesized.dcp]
    valence_i1_apply_numerical_budgets i1_mdu_clock "" $folder
    write_checkpoint [file join $folder synthesized_constrained.dcp]
    report_utilization -file [file join $folder utilization_synth.rpt]
    valence_i1_report_numerical_partitions i1_mdu_clock "" $folder synth
    set sites [lsort -dictionary [get_sites -quiet BUFGCE_X0Y*]]
    if {[llength $sites] == 0} { error "missing explicit external-clock context sites" }
    set source [lindex $sites [expr {[llength $sites] / 2}]]
    set_property HD.CLK_SRC $source [get_ports clock]
    set context [open [file join $folder context.txt] w]
    puts $context "scope=STANDALONE_MDU_ONLY_NOT_CPU_NOT_BOARD"
    puts $context "part=xczu15eg-ffvb1156-2-i period_ns=$period setup_uncertainty_ns=0.100"
    puts $context "input_output_max_delay_ns=0.333 input_output_min_delay_ns=0.000 external_BUFGCE=$source"
    puts $context "internal_module_max_delay_ns=[expr {$period - 0.333}] no_false_or_multicycle_paths=1"
    close $context
    opt_design
    place_design -directive Default
    phys_opt_design -directive Default
    route_design -directive Default
    write_checkpoint [file join $folder routed.dcp]
    report_utilization -file [file join $folder utilization_routed.rpt]
    report_utilization -hierarchical -file [file join $folder hierarchical_utilization_routed.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose \
        -file [file join $folder timing_routed.rpt]
    valence_i1_report_numerical_partitions i1_mdu_clock "" $folder routed
    report_route_status -file [file join $folder route_status.rpt]
    report_drc -file [file join $folder drc.rpt]
    check_timing -verbose -file [file join $folder check_timing.rpt]
    set registers [all_registers -clock i1_mdu_clock]
    set setup [get_timing_paths -from $registers -to $registers -delay_type max -max_paths 1]
    set hold [get_timing_paths -from $registers -to $registers -delay_type min -max_paths 1]
    if {[llength $setup] == 0 || [llength $hold] == 0} { error "missing actual internal timing paths" }
    set result [open [file join $folder result.json] w]
    puts $result [format {{"status":"COMPLETE_STANDALONE_MDU_ONLY","role":"%s","period_ns":%s,"setup_slack_ns":%s,"hold_slack_ns":%s,"logic_lut_cells":%s,"ff_cells":%s,"carry_cells":%s,"dsp_cells":%s,"cpu_or_board_qualified":false}} \
        $role $period [get_property SLACK [lindex $setup 0]] [get_property SLACK [lindex $hold 0]] \
        [llength [get_cells -hierarchical -filter {REF_NAME =~ LUT*}]] \
        [llength [get_cells -hierarchical -filter {REF_NAME =~ FD*}]] \
        [llength [get_cells -hierarchical -filter {REF_NAME =~ CARRY*}]] \
        [llength [get_cells -hierarchical -filter {REF_NAME == DSP48E2}]]]
    close $result
    puts "I1_NUMERICAL_OOC_ROLE_COMPLETE role=$role period=$period"
    close_project
}
puts "I1_NUMERICAL_OOC_COMPLETE roles=$roles NO_CPU_OR_BOARD_CLAIM NO_BIT"
