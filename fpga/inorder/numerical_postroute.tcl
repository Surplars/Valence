# One matched post-route cleanup per completed MDU checkpoint. No resynthesis/new clock/budget changes.
if {$argc != 3} { error "usage: numerical_postroute.tcl REFERENCE_DCP DEFAULT_DCP FRESH_REPORT_ROOT" }
lassign $argv reference candidate output
set output [file normalize $output]
set allowed [string tolower [file normalize E:/VM/Share/Valence-rtl/Valence-InOrder]]
foreach value [list $reference $candidate $output] {
    if {![string match "${allowed}/*" [string tolower [file normalize $value]]]} { error "path outside designated root" }
}
if {[file exists $output]} { error "fresh post-route evidence directory required" }
file mkdir $output
set_param general.maxThreads 8
source [file join [file dirname [info script]] numerical_timing.tcl]
foreach role {reference default} checkpoint [list $reference $candidate] {
    set folder [file join $output $role]
    file mkdir $folder
    open_checkpoint [file normalize $checkpoint]
    set clock [get_clocks -quiet i1_mdu_clock]
    if {[llength $clock] != 1 || [get_property PERIOD $clock] != 3.333} { error "expected original frozen clock" }
    # Both checkpoint inputs already carry the same real-clock/module budgets.
    phys_opt_design -directive AggressiveExplore
    route_design -directive Explore
    write_checkpoint [file join $folder postroute.dcp]
    report_utilization -file [file join $folder utilization_routed.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose \
        -file [file join $folder timing_routed.rpt]
    valence_i1_report_numerical_partitions i1_mdu_clock "" $folder postroute
    report_route_status -file [file join $folder route_status.rpt]
    check_timing -verbose -file [file join $folder check_timing.rpt]
    set registers [all_registers -clock i1_mdu_clock]
    set setup [get_timing_paths -from $registers -to $registers -delay_type max -max_paths 1]
    set hold [get_timing_paths -from $registers -to $registers -delay_type min -max_paths 1]
    if {![llength $setup] || ![llength $hold]} { error "missing internal timing paths" }
    set result [open [file join $folder result.json] w]
    puts $result [format {{"role":"%s","scope":"STANDALONE_MDU_POSTROUTE_ONLY","setup_slack_ns":%s,"hold_slack_ns":%s,"logic_lut_cells":%s,"ff_cells":%s,"dsp_cells":%s,"cpu_or_board_qualified":false}} \
        $role [get_property SLACK [lindex $setup 0]] [get_property SLACK [lindex $hold 0]] \
        [llength [get_cells -hierarchical -filter {REF_NAME =~ LUT*}]] \
        [llength [get_cells -hierarchical -filter {REF_NAME =~ FD*}]] \
        [llength [get_cells -hierarchical -filter {REF_NAME == DSP48E2}]]]
    close $result
    puts "I1_NUMERICAL_POSTROUTE_DONE role=$role"
    close_design
}
puts "I1_NUMERICAL_POSTROUTE_PAIR_DONE NO_NEW_SYNTHESIS NO_CLOCK_CHANGES NO_BIT"
