# Pure Tcl integration check: project/design object names are not RTL top names.
# This is NOT hardware or physical timing evidence.
if {$argc != 2} { error "usage: test_route_mock.tcl ROUTE_SCRIPT FRESH_TEMP_ROOT" }
set script [file normalize [lindex $argv 0]]
set task_root [file normalize [lindex $argv 1]]
if {[file exists $task_root]} { error "fresh test directory required" }
file mkdir $task_root
set checkpoint [file join $task_root input.dcp]
set fixture [open $checkpoint w]
puts $fixture "TEST MOCK ONLY, NOT A REAL CHECKPOINT"
close $fixture
set calls {}
proc set_param {args} {}
proc open_checkpoint {path} { lappend ::calls open }
proc current_design {} { return arbitrary_project_design_object }
proc get_cells {args} { return [lindex $args end] }
proc get_clocks {args} { return orbital_i1_cpu }
proc get_ports {args} { return clock }
proc get_sites {args} { return {BUFGCE_X0Y0 BUFGCE_X0Y8 BUFGCE_X0Y16} }
proc get_property {name object} {
    switch $name {
        NAME { return arbitrary_project_design_object }
        REF_NAME { return RAMB36E2 }
        PERIOD { return 5.000 }
        SLACK { return 0.25 }
        default { error "unexpected queried property $name" }
    }
}
proc set_property {name value object} {
    if {$name != "HD.CLK_SRC" || $value != "BUFGCE_X0Y8" || $object != "clock"} {
        error "bad explicit clock context"
    }
    lappend ::calls context
}
foreach command {opt_design place_design phys_opt_design route_design write_checkpoint
    report_utilization report_timing_summary report_timing report_route_status report_drc} {
    proc $command {args} [format {lappend ::calls %s} $command]
}
proc get_timing_paths {args} { return mocked_path }
set argc 2
set argv [list $checkpoint [file join $task_root reports]]
source $script
if {[lrange $calls 0 6] != {open context opt_design place_design phys_opt_design route_design write_checkpoint}} {
    error "unexpected implementation sequence $calls"
}
set file [open [file join $task_root reports context.txt] r]
set context [read $file]
close $file
if {![string match "*assumed_external_clock_source=BUFGCE_X0Y8*" $context]} {
    error "clock context not recorded"
}
puts "ORBITAL_I1_ROUTE_SCRIPT_MOCK_PASS_NOT_TIMING_EVIDENCE"
