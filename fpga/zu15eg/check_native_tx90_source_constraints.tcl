# Check actual synthesized wrapper names and pin constraints without CPU/IP implementation.
if {$argc!=3} {error "Expected WRAPPER_INTERFACE_DCP PIN_XDC FRESH_OUT"}
lassign $argv dcp xdc out
if {[file exists $out]} {error "Preserve existing proof"}
file mkdir $out
cd $out
file copy [info script] executed_source_constraints.tcl
file copy $xdc tested_native_gmac_pins.xdc
set_param general.maxThreads 8
open_checkpoint $dcp
create_clock -name ui_interface_proxy -period 4 [get_pins u_ddr/c0_ddr4_ui_clk]
read_xdc $xdc
source [file join [file dirname $xdc] native_board_constraints.tcl]
valence_native_tx_constraints
foreach path {centered_tx_clock.clock_dut/pll centered_tx_clock.clock_dut/raw_div centered_tx_clock.clock_dut/pad_div centered_tx_clock.clock_dut/forward_div centered_tx_clock.clock_dut/delay_buffer centered_rx_clock.clock_dut/mmcm centered_rx_clock.rx_clock_buffer centered_rx_clock.clock_dut/feedback_buffer} {
    if {[llength [get_cells -quiet $path]]!=1} {error "Source constraint hierarchy absent: $path"}
}
foreach {name rise fall} {valence_tx_raw_div 0 4 valence_tx_pad_div 0 4 valence_tx_forward_div 2 6} {
    set c [get_clocks $name]
    lassign [get_property WAVEFORM $c] r f
    if {[get_property PERIOD $c]!=8 || abs($r-$rise)>0.001 || abs($f-$fall)>0.001} {error "Wrong divider source waveform $name"}
}
set capture [get_clocks phy_tx_capture]
lassign [get_property WAVEFORM $capture] rise fall
if {[get_property PERIOD $capture]!=8 || abs($rise-2)>0.001 || abs($fall-6)>0.001} {error "Wrong generated pad waveform: [get_property WAVEFORM $capture]"}
report_clocks -file source_clocks.rpt
puts "PASS_NATIVE_TX90_SOURCE_CONSTRAINTS INTERFACE_PROXY_ONLY_NO_FULL_BOARD_QUALIFICATION"
close_design
