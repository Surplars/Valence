# Experimental CPU + fabric OOC implementation. No MIG, board pins or bitstream.
if {$argc != 4} { error "Use run_local.py: expected package directory, fresh run directory, CPU and fabric periods" }
set package [file normalize [lindex $argv 0]]
set output [file normalize [lindex $argv 1]]
set cpuPeriod [lindex $argv 2]
set fabricPeriod [lindex $argv 3]
foreach period [list $cpuPeriod $fabricPeriod] {
    if {![string is double -strict $period] || $period <= 0} { error "Invalid clock period" }
}
set part xczu15eg-ffvb1156-2-i
if {[llength [get_parts -quiet $part]] != 1} { error "Install device support for exact part $part" }
create_project -in_memory -part $part
set handle [open [file join $package rtl-files.txt] r]
set sources [split [string trim [read $handle]] "\n"]
close $handle
foreach relative $sources {
    set source [file join $package $relative]
    if {![file isfile $source]} { error "Missing source $relative" }
    read_verilog -sv $source
}
# Read constraints before synthesis so both synthesis and implementation see the
# same real top-level clocks. No asynchronous groups or fabricated IO clock.
set constraints [file join $output requested_clocks.xdc]
set handle [open $constraints w]
puts $handle [format {create_clock -name cpu -period %s [get_ports cpuClock]} $cpuPeriod]
puts $handle [format {create_clock -name fabric -period %s [get_ports fabricClock]} $fabricPeriod]
puts $handle {set_clock_uncertainty -setup 0.100 [get_clocks {cpu fabric}]}
puts $handle {set_clock_uncertainty -hold 0.080 [get_clocks {cpu fabric}]}
close $handle
read_xdc $constraints
synth_design -top CombinedA1FabricTimingTop -part $part -mode out_of_context
if {[llength [get_cells -quiet -hierarchical -filter {IS_BLACKBOX == 1}]] != 0} {
    error "Unresolved blackboxes: refusing incomplete implementation"
}
foreach name {cpu fabric} {
    if {[llength [get_clocks -quiet $name]] != 1} { error "Missing expected real clock $name" }
}
# Cross-domain paths remain conservatively timed, not CDC-qualified by this run.
# OOC boundary timing is intentionally unspecified. Do not interpret boundary
# unconstrained paths as board timing. No false paths or artificial clocks.
proc reports {stage output} {
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $output ${stage}_timing_summary.rpt]
    report_timing -delay_type max -max_paths 100 -file [file join $output ${stage}_setup_paths.rpt]
    report_timing -delay_type min -max_paths 100 -file [file join $output ${stage}_hold_paths.rpt]
    report_utilization -hierarchical -file [file join $output ${stage}_utilization.rpt]
    report_clock_interaction -file [file join $output ${stage}_clock_interaction.rpt]
    check_timing -verbose -file [file join $output ${stage}_check_timing.rpt]
    report_drc -file [file join $output ${stage}_drc.rpt]
    write_checkpoint -force [file join $output ${stage}.dcp]
}
reports synth $output
opt_design
place_design
phys_opt_design
reports placed $output
route_design
reports routed $output
report_route_status -file [file join $output routed_route_status.rpt]
report_cdc -details -file [file join $output routed_cdc.rpt]
write_xdc -force [file join $output implemented_constraints.xdc]
set handle [open [file join $output COMPLETED.txt] w]
puts $handle "Implementation commands finished; inspect timing, DRC, route status and CDC. This is not board signoff."
close $handle
