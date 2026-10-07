# Continue saved complete board synthesis; no CPU or wrapper re-synthesis.
if {$argc != 3} {error "Expected COMPLETE_SYNTH_DCP ROOT FRESH_ROUTE_DIR"}
lassign $argv dcp root out
foreach name {dcp root out} {set $name [file normalize [set $name]]}
if {[file exists $out]} {error "Preserve previous reports"}
file mkdir $out
cd $out
set_param general.maxThreads 8
open_checkpoint $dcp
read_xdc [file join $root board board_ddr.xdc]
read_xdc [file join $root board pl_ddr4_pins.xdc]
read_xdc [file join $root board native_gmac_pins.xdc]
source [file join $root scripts native_board_constraints.tcl]
valence_native_board_constraints
foreach {pin hz} {u_soc/clock 100000000 u_soc/io_alwaysOnClock 50000000 u_soc/nativeBank/uart/uart/clock 50000000 u_soc/io_nativeGmac_rawTxClock 125000000 u_rgmii/delay_clock 500000000} {
    set clk [get_clocks -of_objects [get_pins $pin]]
    if {[llength $clk]!=1 || abs([get_property PERIOD $clk] - 1.0e9/$hz)>0.001} {error "Missing real clock on $pin"}
}
foreach port [get_ports] {
    if {[get_property PACKAGE_PIN $port] eq "" || [get_property IOSTANDARD $port] in {"" DEFAULT}} {
        error "Unconstrained board I/O: $port"
    }
}
report_io -file io.rpt
report_clocks -file clocks.rpt
report_utilization -hierarchical -file post_synth_utilization.rpt
write_checkpoint assembled.dcp
# The native Windows MIG PHY stitcher failed before RTL elaboration with
# "can't read rt::result" in its automatically spawned synth helper. Reuse
# this complete SoC checkpoint and serialize ONLY opt's internal IP synthesis;
# restore implementation parallelism immediately afterward. No RTL/IP settings
# or timing requirements are changed by this tool-workaround trial.
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
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
puts "NATIVE_BOARD_ROUTED_REQUIRES_SIGNOFF NO_BIT_GENERATED"
close_design
