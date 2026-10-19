# Read-only netlist/constraint diagnostic; no synthesis, opt, place, route or bit.
if {$argc != 3} { error "usage: diagnose_fd_jtag.tcl DCP RTL_ROOT FRESH_REPORT_ROOT" }
set checkpoint [file normalize [lindex $argv 0]]
set rtl_root [file normalize [lindex $argv 1]]
set output [file normalize [lindex $argv 2]]
if {[file exists $output]} { error "fresh diagnostic directory required" }
file mkdir $output
set_param general.maxThreads 8
open_checkpoint $checkpoint
source [file join $rtl_root bscan_timing.tcl]
set primitives [get_cells -hierarchical -filter {REF_NAME == BSCANE2}]
if {[llength $primitives] != 1} { error "ambiguous BSCAN owner" }
set primitive [get_property NAME $primitives]
regsub {([/.])user_scan$} $primitive {\1transport} engine
set code [catch {
    valence_apply_bscan_timing $primitive $engine orbital_i1_cpu zu15eg-user2-tck50-positive-v1
} message options]
set audit [open [file join $output bscan_diagnostic.txt] w]
puts $audit "gate_code=$code message=$message"
if {$code} { puts $audit [dict get $options -errorinfo] }
foreach pattern {*update_selected* *update_ack* *update_release*} {
    foreach cell [get_cells -quiet -hierarchical -filter "NAME =~ $pattern"] {
        puts $audit "CELL=$cell REF=[get_property REF_NAME $cell] INVERTED=[get_property IS_C_INVERTED $cell]"
        foreach pin [get_pins -quiet -of_objects $cell] { puts $audit "PIN=$pin" }
    }
}
close $audit
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $output timing_diagnostic.rpt]
report_timing -from [get_clocks orbital_i1_cpu] -to [get_clocks orbital_i1_cpu] \
    -delay_type max -max_paths 30 -nworst 2 -file [file join $output setup_cpu_diagnostic.rpt]
report_clocks -file [file join $output clocks_diagnostic.rpt]
puts "I1_BSCAN_DIAGNOSTIC gate_code=$code message=$message"
close_design
