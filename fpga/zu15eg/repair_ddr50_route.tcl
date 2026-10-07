# Match soc_top_ddr.sv's explicit AWREGION/ARREGION=0 in the retained routed design.
# AMD UG835 connect_net / route_design / phys_opt_design incremental ECO flow.
if {$argc != 2} {error "Expected ROUTED_ERROR_DCP OUTPUT_DIR"}
lassign $argv dcp output_dir
set output_dir [file normalize $output_dir]
file mkdir $output_dir
set_param general.maxThreads 8
open_checkpoint $dcp
set pins [get_pins -quiet {u_axi_cdc/s_axi_awregion* u_axi_cdc/s_axi_arregion*}]
if {[llength $pins] != 8} {error "Expected exactly 8 REGION input pins"}
set ground [get_nets {<const0>}]
if {[llength $ground] != 1 || [get_property TYPE $ground] ne "GROUND"} {error "Missing ground net"}
foreach pin $pins {
    if {[llength [get_nets -quiet -of_objects $pin]] != 0} {error "REGION pin unexpectedly connected: $pin"}
}
connect_net -hierarchical -net $ground -objects $pins
foreach pin $pins {
    set net [get_nets -of_objects $pin]
    if {[get_property TYPE $net] ne "GROUND"} {error "REGION tie-off did not propagate: $pin"}
    puts "DDR50 ECO: $pin tied to [get_property TYPE $net]"
}
write_checkpoint -force [file join $output_dir region_fixed.dcp]
route_design -preserve -tns_cleanup
report_route_status -file [file join $output_dir repaired_route_status.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $output_dir repaired_timing.rpt]
write_checkpoint -force [file join $output_dir repaired_routed.dcp]
phys_opt_design -directive Explore
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $output_dir optimized_timing.rpt]
report_timing -delay_type max -max_paths 30 -input_pins -file [file join $output_dir optimized_paths.rpt]
report_timing -group clk_out1_clk_wiz_ddr -delay_type max -max_paths 10 -file [file join $output_dir cpu_paths.rpt]
report_timing -group mmcm_clkout0 -delay_type max -max_paths 5 -file [file join $output_dir mig_ui_paths.rpt]
report_route_status -file [file join $output_dir optimized_route_status.rpt]
report_utilization -hierarchical -file [file join $output_dir utilization.rpt]
report_clock_interaction -file [file join $output_dir clock_interaction.rpt]
report_cdc -file [file join $output_dir cdc.rpt]
report_drc -file [file join $output_dir drc.rpt]
write_checkpoint -force [file join $output_dir optimized_routed.dcp]
puts "DDR50 ECO: repair, optimization and reports complete; no bitstream generated"
close_design
