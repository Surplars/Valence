# Reuse the frozen full-board synthesis checkpoint. No CPU/VPU clock cuts.
set_param general.maxThreads 8
set root [file normalize [lindex $argv 0]]
set output [file join $root implementation]
create_project -in_memory -part xczu15eg-ffvb1156-2-i
open_checkpoint [file join $output synthesized.dcp]
source [file join $root board_cdc.tcl]
set clocks [board_cdc::apply $output]
board_cdc::coverage $output
write_checkpoint [file join $output constrained.dcp]
opt_design -directive Default
place_design -directive Default
phys_opt_design -directive Default
route_design -directive Default
write_checkpoint [file join $output routed.dcp]
report_utilization -hierarchical -file [file join $output utilization_routed.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose -file [file join $output timing_summary.rpt]
report_clock_interaction -file [file join $output clock_interaction.rpt]
report_clocks -file [file join $output clocks_routed.rpt]
report_cdc -details -file [file join $output cdc.rpt]
report_bus_skew -warn_on_violation -file [file join $output bus_skew.rpt]
report_pulse_width -file [file join $output pulse_width.rpt]
report_drc -file [file join $output drc.rpt]
check_timing -verbose -file [file join $output check_timing.rpt]
board_cdc::coverage $output
set fd [open [file join $output clock_results.tsv] w]
puts $fd "role\tclock\tperiod_ns\tsetup_wns_ns\tnegative_endpoints\thold_wns_ns"
foreach role {CPU VPU SYSTEM} clk $clocks {
    set regs [all_registers -clock $clk]
    set setup [get_timing_paths -from $regs -to $regs -delay_type max -max_paths 1]
    set hold [get_timing_paths -from $regs -to $regs -delay_type min -max_paths 1]
    set bad [get_timing_paths -from $regs -to $regs -delay_type max -slack_lesser_than 0 -nworst 1 -max_paths 10000]
    if {[llength $bad] >= 10000} {error "board timing endpoint enumeration limit"}
    puts $fd "$role\t$clk\t[get_property PERIOD [get_clocks $clk]]\t[get_property SLACK $setup]\t[llength $bad]\t[get_property SLACK $hold]"
    report_timing -from $regs -to $regs -delay_type max -max_paths 30 -nworst 1 -input_pins -file [file join $output ${role}_setup_paths.rpt]
    report_timing -from $regs -to $regs -delay_type min -max_paths 10 -nworst 1 -input_pins -file [file join $output ${role}_hold_paths.rpt]
}
close $fd
set setupBad [get_timing_paths -delay_type max -slack_lesser_than 0 -max_paths 1]
set holdBad [get_timing_paths -delay_type min -slack_lesser_than 0 -max_paths 1]
set drcBad [get_drc_violations -quiet -filter {SEVERITY == Error}]
puts "BOARD_GLOBAL_SIGNOFF setup_fail=[llength $setupBad] hold_fail=[llength $holdBad] drc_errors=[llength $drcBad]"
puts PASS_FULL_BOARD_IMPLEMENTATION_REPORTS_READY
close_design
close_project
exit
