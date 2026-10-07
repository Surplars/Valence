# Reuse synthesized SoC when only the physical wrapper/constraints change.
# Args ORIGINAL_COMPLETE_SYNTH_DCP FRESH_ROOT EXISTING_VERIFIED_MIG_XCI.
if {$argc != 3} {error "Expected SYNTH_DCP FRESH_ROOT MIG_XCI"}
lassign $argv original root mig
set root [file normalize $root]
set out [file join $root implementation]
if {[file exists $out]} {error "Fresh wrapper candidate required"}
file mkdir $out
cd $out
set_param general.maxThreads 8
open_checkpoint $original
write_checkpoint -cell u_soc soc_reused.dcp
write_edif -cell u_soc soc_reused.edf
close_design
create_project -in_memory -part xczu15eg-ffvb1156-2-i
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
add_files -norecurse [file join $out soc_reused.dcp]
set_property SCOPED_TO_CELLS u_soc [get_files soc_reused.dcp]
set iproot [file join [file dirname [file dirname $original]] ip-build board_ip.srcs sources_1 ip]
foreach name {clk_wiz_ddr axi_clock_converter_ddr} {read_ip [file join $iproot $name $name.xci]}
read_ip $mig
foreach name {soc_top_gmac_ddr.sv native_rgmii.sv native_gmac_clocks.sv native_gmac_divided_clock.sv native_gmac_pll_pair.sv native_tx_common_delay.sv native_tx_reset_boundary.sv native_phy_board_control.sv native_phy_tx_init.sv} {
    read_verilog -sv [file join $root board $name]
}
# The optional hardware PHY helper instantiates this unchanged Chisel export.
# It is pruned in the default software-PHY board mode.
read_verilog -sv [file join $root rtl MdioClause22.sv]
synth_design -top soc_top_gmac_ddr -flatten_hierarchy none
write_checkpoint post_synth_unconstrained.dcp
close_project
open_checkpoint post_synth_unconstrained.dcp
read_xdc [file join $root board board_ddr.xdc]
read_xdc [file join $root board pl_ddr4_pins.xdc]
read_xdc [file join $root board native_gmac_pins.xdc]
source [file join $root scripts native_board_constraints.tcl]
valence_native_board_constraints
write_checkpoint assembled.dcp
set_param general.maxThreads 1
opt_design
set_param general.maxThreads 8
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Unresolved functional blackbox"}
valence_native_board_constraints
write_checkpoint optimized.dcp
place_design -directive Explore
phys_opt_design -directive Explore
write_checkpoint placed.dcp
report_timing_summary -delay_type min_max -file placed_timing.rpt
route_design -directive Explore -tns_cleanup
phys_opt_design -directive Explore
write_checkpoint routed.dcp
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_timing -delay_type max -max_paths 40 -input_pins -file setup_paths.rpt
report_timing -delay_type min -max_paths 30 -input_pins -file hold_paths.rpt
report_utilization -hierarchical -file utilization.rpt
report_cdc -details -file cdc.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_route_status -file route_status.rpt
report_exceptions -coverage -file exception_coverage.rpt
report_clock_interaction -file clock_interaction.rpt
report_clocks -file clocks.rpt
report_io -file io.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
puts "NATIVE_BOARD_ROUTED_REQUIRES_SIGNOFF NO_BIT_GENERATED"
close_design
