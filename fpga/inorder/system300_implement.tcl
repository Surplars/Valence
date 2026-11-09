# One implementation of the frozen, GSIM-qualified managed system.
set_param general.maxThreads 8
puts "VIVADO_THREADS [get_param general.maxThreads]"
set root [file dirname [info script]]
set output [file join $root impl]
if {[file exists $output]} {error "fresh implementation output required"}
file mkdir $output
open_checkpoint [file join $root cdc-preflight constrained.dcp]
source [file join $root system_cdc.tcl]
foreach {name path} {cpu unit/unit/cpu vpu unit/unit/vector fabric unit/fabric cmu unit/cmu
    mdu unit/unit/cpu/core/mulDiv icache unit/unit/cpu/icache dcache unit/unit/cpu/dcache} {
    set cells [get_cells -quiet -hierarchical -filter "NAME =~ $path/* && (REF_NAME =~ FD* || REF_NAME =~ RAM* || REF_NAME =~ DSP*)"]
    if {![llength $cells]} {error "missing module: $path"}
    group_path -name system_$name -to $cells
}
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $output timing_synth.rpt]
opt_design -directive Explore
place_design -directive Explore
write_checkpoint [file join $output placed.dcp]
phys_opt_design -directive AggressiveExplore
spinor_cdc::apply $output
route_design -directive Explore
write_checkpoint [file join $output routed.dcp]
spinor_cdc::coverage $output
report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose -file [file join $output timing_routed.rpt]
set fd [open [file join $output internal_result.tsv] w]
puts $fd "domain\tsetup_ns\thold_ns"
foreach {name clk} {cpu i1_cpu300 vpu i1_vpu300 system i1_system300} {
    set cells [all_registers -clock $clk]
    report_timing -from $cells -to $cells -delay_type max -max_paths 50 -nworst 1 -file [file join $output ${name}_setup.rpt]
    report_timing -from $cells -to $cells -delay_type min -max_paths 30 -nworst 1 -file [file join $output ${name}_hold.rpt]
    set setup [get_timing_paths -from $cells -to $cells -delay_type max -max_paths 1]
    set hold [get_timing_paths -from $cells -to $cells -delay_type min -max_paths 1]
    if {![llength $setup] || ![llength $hold]} {error "missing domain paths: $name"}
    puts $fd "$name\t[get_property SLACK $setup]\t[get_property SLACK $hold]"
}
close $fd
foreach {name path} {cpu unit/unit/cpu vpu unit/unit/vector fabric unit/fabric cmu unit/cmu
    mdu unit/unit/cpu/core/mulDiv icache unit/unit/cpu/icache dcache unit/unit/cpu/dcache} {
    set cells [get_cells -quiet -hierarchical -filter "NAME =~ $path/* && (REF_NAME =~ FD* || REF_NAME =~ RAM* || REF_NAME =~ DSP*)"]
    report_timing -to $cells -delay_type max -max_paths 10 -nworst 1 -file [file join $output ${name}_module_setup.rpt]
}
report_bus_skew -warn_on_violation -file [file join $output bus_skew.rpt]
report_cdc -details -file [file join $output cdc_routed.rpt]
report_clock_interaction -file [file join $output clock_interaction.rpt]
report_utilization -file [file join $output utilization_routed.rpt]
report_utilization -hierarchical -file [file join $output utilization_hierarchical.rpt]
report_route_status -file [file join $output route_status.rpt]
report_exceptions -file [file join $output exceptions.rpt]
report_exceptions -ignored -file [file join $output exceptions_ignored.rpt]
check_timing -verbose -file [file join $output check_timing.rpt]
write_xdc [file join $output routed.xdc]
puts "I1_SYSTEM300_ROUTED_DONE NO_BIT NO_BOARD_SIGNOFF H_PRESENT_DIRECTED_FUNCTION_QUALIFIED"
close_design
