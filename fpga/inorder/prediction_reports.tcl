# Read-only report audit of completed predictor DCPs. No constraints or netlist changes.
if {$argc != 2} { error "usage: prediction_reports.tcl COMPLETED_PHYSICAL_ROOT FRESH_REPORT_ROOT" }
lassign $argv input output
set allowed [string tolower [file normalize E:/VM/Share/Valence-rtl/Valence-InOrder]]
foreach path [list $input $output] {
    if {![string match "${allowed}/*" [string tolower [file normalize $path]]]} { error "path outside designated root" }
}
if {[file exists $output]} { error "fresh audit output required" }
file mkdir $output
set_param general.maxThreads 4
foreach role {reference local hashed} {
    set folder [file join $output $role]
    file mkdir $folder
    open_checkpoint [file normalize [file join $input $role routed.dcp]]
    set clk [get_clocks -quiet i1_prediction_clock]
    if {[llength $clk] != 1 || [get_property PERIOD $clk] != 3.333} { error "unexpected frozen clock" }
    set registers [all_registers -clock i1_prediction_clock]
    set ram [get_cells -hierarchical -filter {REF_NAME =~ RAM*}]
    set sequential [lsort -unique [concat $registers $ram]]
    if {![llength $ram] || ![llength $registers]} { error "missing state/RAM coverage" }
    set ledger [open [file join $folder sequential_coverage.txt] w]
    puts $ledger "all_registers_count=[llength $registers] ram_cells=[llength $ram] union_cells=[llength $sequential]"
    foreach cell $sequential { puts $ledger "[get_property NAME $cell] [get_property REF_NAME $cell]" }
    close $ledger
    report_timing -from $sequential -to $sequential -delay_type max -max_paths 10 \
        -file [file join $folder internal_setup.rpt]
    report_timing -from $sequential -to $sequential -delay_type min -max_paths 10 \
        -file [file join $folder internal_hold.rpt]
    set setup [get_timing_paths -from $sequential -to $sequential -delay_type max -max_paths 1]
    set hold [get_timing_paths -from $sequential -to $sequential -delay_type min -max_paths 1]
    if {![llength $setup] || ![llength $hold]} { error "missing state-to-state paths" }
    set result [open [file join $folder result.json] w]
    puts $result [format {{"role":"%s","scope":"STATE_TO_STATE_INCLUDING_DISTRIBUTED_RAM_READ_ONLY_DCP","internal_setup_slack_ns":%s,"internal_hold_slack_ns":%s,"all_registers_count":%s,"ram_cell_count":%s,"union_state_cells":%s,"cpu_or_board_qualified":false}} \
        $role [get_property SLACK [lindex $setup 0]] [get_property SLACK [lindex $hold 0]] \
        [llength $registers] [llength $ram] [llength $sequential]]
    close $result
    puts "I1_PREDICTION_REPORT_AUDIT role=$role"
    close_design
}
puts "I1_PREDICTION_REPORT_AUDIT_DONE NO_IMPLEMENTATION NO_CONSTRAINT_CHANGE"
