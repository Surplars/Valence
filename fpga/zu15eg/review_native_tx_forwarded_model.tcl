# Read-only diagnostic: compare candidate re-expressions of PHY TX bounds.
# Algebraic bounds alone do NOT prove equivalent DDR edge selection. The
# delay-translated candidate selected a different hold edge and was rejected;
# the physical-OQ candidate also failed. Neither is a signoff constraint set.
# Same physical DCP, same 2ns nominal PHY delay and +/-1.75ns budgets. No route
# edits/checkpoint/bit and no clock/source latency overrides or false paths.
if {$argc != 2} {error "Expected ROUTED_DCP FRESH_OUTPUT_DIR"}
lassign $argv dcp out
if {[file exists $out]} {error "Preserve evidence"}
file mkdir $out
cd $out
set_param general.maxThreads 8
open_checkpoint $dcp
set src [get_pins u_rgmii/tx_clock_ddr/CLK]
set master [get_clocks -of_objects $src]
if {[llength $master]!=1 || abs([get_property PERIOD $master]-8.0)>0.001} {error "Actual 125MHz CLK master absent"}
set ports [get_ports {eth_txd[*] eth_tx_ctl}]
report_clocks -file original_clocks.rpt
report_timing -to $ports -delay_type min_max -max_paths 10 -input_pins -file original_tx.rpt
# External 2ns PHY capture delay may be placed in output delays rather than
# the generated-clock waveform: max=1.75-2=-0.25, min=-1.75-2=-3.75.
# For edge-aligned DDR this selects the next edge (4ns) for setup; use the
# exact original remote-capture edges via multicycle only if proven needed.
create_generated_clock -name phy_tx_capture -source $src -divide_by 1 [get_ports eth_txc]
foreach edge {rise fall} {
    set args {}
    if {$edge eq "fall"} {set args {-clock_fall -add_delay}}
    set_output_delay -clock phy_tx_capture {*}$args -max -0.250 $ports
    set_output_delay -clock phy_tx_capture {*}$args -min -3.750 $ports
}
report_timing -to $ports -delay_type min_max -max_paths 10 -input_pins -file delay_translated_tx.rpt
report_clocks -file delay_translated_clocks.rpt
# A second diagnostic explicitly models forwarding through the physical OQ.
# This must not create a fictitious ideal clock or drop any I/O endpoints.
create_generated_clock -name native_tx_forward -source $src -divide_by 1 [get_pins u_rgmii/tx_clock_ddr/OQ]
create_generated_clock -name phy_tx_capture -source [get_pins u_rgmii/tx_clock_ddr/OQ] -edges {1 2 3} -edge_shift {2.0 2.0 2.0} [get_ports eth_txc]
foreach edge {rise fall} {
    set args {}
    if {$edge eq "fall"} {set args {-clock_fall -add_delay}}
    set_output_delay -clock phy_tx_capture {*}$args -max 1.750 $ports
    set_output_delay -clock phy_tx_capture {*}$args -min -1.750 $ports
}
report_timing -to $ports -delay_type min_max -max_paths 10 -input_pins -file physical_oq_tx.rpt
report_clocks -file physical_oq_clocks.rpt
puts "TX_MODEL_DIAGNOSTIC_COMPLETE NOT_A_SIGNOFF NO_BIT"
close_design
