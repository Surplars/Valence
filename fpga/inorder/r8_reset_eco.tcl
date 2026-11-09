# One-pin board reset ECO. CPU/VPU RTL, placement and clocks are the R8 design.
set_param general.maxThreads 8
set root [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
file mkdir $out
open_checkpoint [file join $root implementation routed.dcp]
set stage {i1_board_i/coldReset/U0/EXT_LPF/ACTIVE_LOW_AUX.ACT_LO_AUX/syncstages_ff_reg[0]}
set cell [get_cells $stage]
set pin [get_pins "$stage/D"]
set old [get_nets -of_objects $pin]
set ground [get_nets -of_objects [get_pins "$stage/R"]]
if {[llength $pin] != 1 || [get_property REF_NAME $cell] ne "FDRE" ||
    [get_property REF_NAME [get_cells -of_objects [get_pins -leaf -of_objects $old -filter {DIRECTION == OUT}]]] ne "VCC" ||
    [get_property REF_NAME [get_cells -of_objects [get_pins -leaf -of_objects $ground -filter {DIRECTION == OUT}]]] ne "GND"} {
    error "R8 reset ECO precondition differs from audited netlist"
}
# C_AUX_RESET_HIGH=0 with aux_reset_in=0 became a constant 1 after inversion.
# Feed this synchronizer a constant 0: equivalent to tying unused aux_reset_in=1.
route_design -unroute -pins $pin
disconnect_net -net $old -objects $pin
connect_net -net $ground -objects $pin
# The changed pin uses physical constant nets, not an ordinary routed signal.
route_design -physical_nets
report_route_status -file [file join $out route-status-final.rpt]
report_drc -ruledeck bitstream_checks -file [file join $out drc-final.rpt]
report_timing_summary -delay_type min_max -check_timing_verbose -max_paths 10 -file [file join $out timing-final.rpt]
report_bus_skew -file [file join $out bus-skew-final.rpt]
if {[llength [get_timing_paths -delay_type min -slack_lesser_than 0 -max_paths 1]] ||
    [llength [get_drc_violations -quiet -filter {SEVERITY == Error}]]} {error "Reset ECO physical checks failed"}
write_verilog -cell [get_cells i1_board_i/coldReset] -mode funcsim [file join $out cold-reset-fixed.v]
write_checkpoint [file join $out routed-reset-final.dcp]
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
write_bitstream [file join $out i1_board.bit]
puts PASS_R8_RESET_ECO_BIT_WRITTEN_NOT_BOARD_TESTED
close_design
exit