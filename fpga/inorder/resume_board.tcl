# Resume ONLY this isolated board's completed synthesis after a constraint fix.
if {$argc != 1} {error "usage: resume_board.tcl STAGED_BOARD_ROOT"}
set root [file normalize [lindex $argv 0]]
if {![string match orbital-i1-board-zu15eg-* [file tail $root]] ||
    ![file isfile [file join $root board-manifest.json]]} {
    error "An explicitly staged I1 real-board directory is required"
}
set_param general.maxThreads 8
open_project [file join $root project i1_board.xpr]
if {[get_property TOP [get_filesets sources_1]] ne "soc_top_i1_network_ddr" ||
    [get_property PROGRESS [get_runs synth_1]] ne "100%" ||
    [get_property NEEDS_REFRESH [get_runs synth_1]]} {
    error "Refuse to reuse incomplete, stale or different board synthesis"
}
set preserved [file join $root failed-attempts impl_1-precheck]
set attempt 1
while {[file exists $preserved]} {
    incr attempt
    set preserved [file join $root failed-attempts impl_1-precheck-$attempt]
}
file mkdir $preserved
set run_dir [get_property DIRECTORY [get_runs impl_1]]
foreach pattern {*.log *.jou *.tcl *.rpt} {
    foreach file [glob -nocomplain [file join $run_dir $pattern]] {
        file copy $file $preserved
    }
}
# This is our failed implementation only. The completed CPU/MIG/clock/AXI
# synthesis runs and their original checkpoints are never reset or replaced.
reset_run impl_1
set_property STEPS.OPT_DESIGN.TCL.PRE [file join $root scripts board_constraints.tcl] [get_runs impl_1]
puts "I1_BOARD_RESUME_OWN_SYNTH_ONLY CPU_SYNTH_NOT_RESET IP_SYNTH_NOT_RESET"
launch_runs impl_1 -to_step route_design -jobs 1
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {
    error "Real board implementation did not complete"
}
open_run impl_1
source [file join $root scripts report_board.tcl]
i1_report_real_board $root
close_project
