# Three small production modules in one native Vivado process; no board project is touched.
# Usage: vivado -mode batch -source vivado-fp-modules.tcl -tclargs RTL_ROOT REPORT_ROOT
if {$argc != 2} { error "usage: vivado-fp-modules.tcl RTL_ROOT REPORT_ROOT" }
set fp_rtl_root [file normalize [lindex $argv 0]]
set fp_report_root [file normalize [lindex $argv 1]]
if {[file exists $fp_report_root]} { error "Report root already exists; choose a fresh directory" }
set fp_module_script [file join [file dirname [info script]] vivado-module-ooc.tcl]
foreach fp_top {FloatingPointAdd FloatingPointState FloatingPointSystem} {
    set argc 6
    set argv [list [file join $fp_rtl_root $fp_top] xczu15eg-ffvb1156-2-i 10.0 $fp_top route \
        [file join $fp_report_root $fp_top]]
    source $fp_module_script
    close_project
}
puts "FP_MODULE_BATCH_COMPLETE"
