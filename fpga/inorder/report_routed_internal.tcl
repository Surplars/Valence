# Read-only partition of a completed routed OOC diagnostic.
if {$argc != 2} { error "usage: report_routed_internal.tcl ROUTED_DCP EXISTING_REPORT_DIR" }
lassign $argv checkpoint output
open_checkpoint [file normalize $checkpoint]
foreach {file kind} {setup_internal_routed.rpt max hold_internal_routed.rpt min} {
    set path [file join [file normalize $output] $file]
    if {[file exists $path]} { error "do not overwrite prior physical evidence" }
    report_timing -from [all_registers] -to [all_registers] -delay_type $kind \
        -max_paths 40 -nworst 1 -file $path
}
puts "I1_ROUTED_INTERNAL_REPORTS_DONE NO_NETLIST_OR_CONSTRAINT_CHANGES"
close_design
