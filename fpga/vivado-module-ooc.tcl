# Compare one exported RTL module at a time. Run from a dedicated copy of the RTL directory.
# vivado -mode batch -source vivado-module-ooc.tcl -tclargs RTL_DIRECTORY PART PERIOD_NS TOP synth|place|route
set module_details_script [file join [file dirname [info script]] vivado-module-path-details.tcl]
if {$argc < 5 || $argc > 6} {
    error "usage: vivado-module-ooc.tcl RTL_DIRECTORY FULL_PART PERIOD_NS TOP synth|place|route [REPORT_DIRECTORY]"
}
set rtl_dir [file normalize [lindex $argv 0]]
set target_part [lindex $argv 1]
set period_ns [lindex $argv 2]
set top_module [lindex $argv 3]
set stage [lindex $argv 4]
set report_dir [expr {$argc == 6 ? [lindex $argv 5] : "reports"}]
if {$top_module ni {PmpChecker StoreBuffer MachineSystemUnit MachineCore IntegerBackend
    RenameRob LoadStoreUnit IntegerAlu SharedDataGsim AtomicMemory
    InstructionLineCache SynchronousFetch CoherentLineCache DataTranslationAdapter
    InstructionTranslationAdapter SvTranslationService TwoMasterTwoBankTileLinkCrossbar LoadReplayPathTimingTop
    FloatingPointAdd FloatingPointState FloatingPointSystem FloatingPointExecute
    FloatingPointMemoryPipeline RegisteredFetchPacket
    FloatingPointAddS FloatingPointMultiplyS FloatingPointFusedS FloatingPointDivSqrtS FloatingPointMiscS
    FloatingPointAddD FloatingPointMultiplyD FloatingPointFusedD FloatingPointDivSqrtD FloatingPointMiscD}} {
    error "Unsupported module top"
}
if {$stage ni {synth place route}} { error "Stage must be synth, place or route" }
if {![string is double -strict $period_ns] || $period_ns <= 0} {
    error "PERIOD_NS must be positive"
}
set matched_parts [get_parts -quiet $target_part]
if {[llength $matched_parts] != 1 || [get_property NAME $matched_parts] ne $target_part} {
    error "Specify an exact installed FPGA part"
}
cd $rtl_dir
set source_files [glob -nocomplain *.sv]
if {[llength $source_files] == 0} { error "No exported SystemVerilog files" }
create_project -in_memory -part $target_part
set_param general.maxThreads 8
read_verilog -sv $source_files
synth_design -top $top_module -part $target_part -mode out_of_context -flatten_hierarchy none

# A virtual clock constrains the combinational PMP checker; sequential modules use their real clock.
# Zero boundary delays are a reproducible comparison convention, not a board-level I/O budget.
if {[llength [get_ports -quiet clock]] == 0} {
    create_clock -name module_clock -period $period_ns
} else {
    create_clock -name module_clock -period $period_ns [get_ports clock]
}
set data_inputs [get_ports -quiet -filter {DIRECTION == IN && NAME != clock && NAME != reset}]
set data_outputs [get_ports -quiet -filter {DIRECTION == OUT}]
if {[llength $data_inputs] > 0} { set_input_delay -clock module_clock 0 $data_inputs }
if {[llength $data_outputs] > 0} { set_output_delay -clock module_clock 0 $data_outputs }
file mkdir $report_dir
report_utilization -file [file join $report_dir post_synth_utilization.rpt]
report_timing_summary -report_unconstrained -file [file join $report_dir post_synth_timing.rpt]
report_timing -delay_type max -max_paths 20 -file [file join $report_dir post_synth_paths.rpt]
write_checkpoint -force [file join $report_dir post_synth.dcp]
if {$stage eq "synth"} {
    puts "Module synthesis complete; placement skipped"
    return
}
opt_design
place_design
report_utilization -file [file join $report_dir post_place_utilization.rpt]
report_timing_summary -report_unconstrained -file [file join $report_dir post_place_timing.rpt]
report_timing -delay_type max -max_paths 20 -file [file join $report_dir post_place_paths.rpt]
write_checkpoint -force [file join $report_dir post_place.dcp]
if {$stage eq "place"} {
    puts "Module placement complete; routing skipped"
    return
}
route_design
report_utilization -file [file join $report_dir post_route_utilization.rpt]
report_timing_summary -report_unconstrained -file [file join $report_dir post_route_timing.rpt]
report_timing -delay_type max -max_paths 20 -file [file join $report_dir post_route_paths.rpt]
report_timing -delay_type min -max_paths 10 -file [file join $report_dir post_route_hold_paths.rpt]
source $module_details_script
valence_module_path_details $report_dir
write_checkpoint -force [file join $report_dir post_route.dcp]
puts "Module routing complete; OOC results are not a whole-board timing guarantee"
