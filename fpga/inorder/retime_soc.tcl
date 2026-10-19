# Read-only timing reanalysis of ONE synthesized checkpoint, not another synthesis/implementation.
if {$argc != 2} { error "usage: retime_soc.tcl SYNTH_DCP FRESH_REPORT_ROOT" }
set input [file normalize [lindex $argv 0]]
set output [file normalize [lindex $argv 1]]
if {![file exists $input] || [file exists $output]} { error "existing DCP and fresh reports required" }
file mkdir $output
set_param general.maxThreads 8
open_checkpoint $input
foreach setting {{200 5.000000} {300 3.333333}} {
    lassign $setting mhz period
    set target [file join $output "cpu$mhz"]
    file mkdir $target
    create_clock -name orbital_i1_cpu -period $period [get_ports clock]
    set_input_delay 0.000 -clock orbital_i1_cpu [get_ports -filter {DIRECTION == IN && NAME != clock}]
    set_output_delay 0.000 -clock orbital_i1_cpu [get_ports -filter {DIRECTION == OUT}]
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $target timing_synth.rpt]
    report_timing -from [all_registers] -to [all_registers] -delay_type max -max_paths 20 -nworst 2 \
        -file [file join $target setup_internal_synth.rpt]
    check_timing -verbose -file [file join $target check_timing.rpt]
    set paths [get_timing_paths -delay_type max -max_paths 1]
    set wns [get_property SLACK $paths]
    set result [open [file join $target result.json] w]
    puts $result "{\"status\":\"REANALYZED_SAME_SYNTH_NETLIST_NOT_ROUTED\",\"target_mhz\":$mhz,\"period_ns\":$period,\"setup_wns_ns\":$wns,\"hardware_nominal_timebase_hz\":100000000,\"bit_generated\":false}"
    close $result
    puts "I1_SAME_NETLIST_TARGET_ESTIMATE mhz=$mhz wns=$wns"
}
close_design
