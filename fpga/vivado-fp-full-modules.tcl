# Full numerical groups and their actual architectural bridge, one native batch.
# No board GUI project is opened or modified. Fresh outputs only.
if {$argc < 2 || $argc > 3} {
    error "usage: vivado-fp-full-modules.tcl RTL_ROOT REPORT_ROOT [RV64GC_CORE_RTL]"
}
set fp_full_rtl_root [file normalize [lindex $argv 0]]
set fp_full_report_root [file normalize [lindex $argv 1]]
set fp_full_core_rtl [expr {$argc == 3 ? [file normalize [lindex $argv 2]] : ""}]
if {[file exists $fp_full_report_root]} { error "Report root exists; use a fresh directory" }
set fp_full_module_script [file join [file dirname [info script]] vivado-module-ooc.tcl]
set fp_full_tops {FloatingPointAddS FloatingPointMultiplyS FloatingPointFusedS
    FloatingPointDivSqrtS FloatingPointMiscS
    FloatingPointAddD FloatingPointMultiplyD FloatingPointFusedD
    FloatingPointDivSqrtD FloatingPointMiscD
    FloatingPointState FloatingPointExecute FloatingPointSystem}
foreach fp_full_top $fp_full_tops {
    set argc 6
    set argv [list [file join $fp_full_rtl_root $fp_full_top] xczu15eg-ffvb1156-2-i 10.0 $fp_full_top route \
        [file join $fp_full_report_root $fp_full_top]]
    puts "FULL_FP_MODULE_BEGIN $fp_full_top"
    source $fp_full_module_script
    close_project
    puts "FULL_FP_MODULE_COMPLETE $fp_full_top"
}
if {$fp_full_core_rtl ne ""} {
    set argc 6
    set argv [list $fp_full_core_rtl xczu15eg-ffvb1156-2-i 10.0 MachineCore route \
        [file join $fp_full_report_root MachineCore]]
    puts "RV64GC_CORE_BEGIN"
    source $fp_full_module_script
    close_project
    puts "RV64GC_CORE_COMPLETE"
}
puts "FULL_FP_MODULE_BATCH_COMPLETE"
