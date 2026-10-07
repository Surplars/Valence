if {$argc != 2} {error "Expected PROJECT_XPR REPORT_DIR"}
lassign $argv project_xpr report_dir
file mkdir $report_dir
set_param general.maxThreads 8
open_project $project_xpr
if {[get_property top [get_filesets sources_1]] ne "soc_top_ddr"} {error "Wrong DDR top"}
if {[llength [get_files -quiet *ip_port_stubs*]]} {error "Validation stubs must not enter synthesis"}
generate_target all [get_ips blk_mem_gen_0] -force
foreach ip [get_ips] {create_ip_run $ip}
update_compile_order -fileset sources_1
puts "DDR50: starting real synthesis with vendor IP OOC runs"
launch_runs synth_1 -jobs 6
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "Synthesis failed: [get_property STATUS [get_runs synth_1]]"}
open_run synth_1
report_utilization -file [file join $report_dir synth_utilization.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $report_dir synth_timing.rpt]
report_timing -delay_type max -max_paths 30 -input_pins -file [file join $report_dir synth_paths.rpt]
close_design
puts "DDR50: starting implementation through route_design (no bitstream)"
launch_runs impl_1 -to_step route_design -jobs 6
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "Implementation failed: [get_property STATUS [get_runs impl_1]]"}
open_run impl_1
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $report_dir route_timing.rpt]
report_timing -delay_type max -max_paths 50 -input_pins -file [file join $report_dir route_paths.rpt]
report_utilization -hierarchical -file [file join $report_dir route_utilization.rpt]
report_clock_interaction -file [file join $report_dir clock_interaction.rpt]
report_cdc -file [file join $report_dir cdc.rpt]
report_drc -file [file join $report_dir drc.rpt]
puts "DDR50: route and reports complete"
close_project
