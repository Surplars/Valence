# Isolate six TX pad DDR clocks from raw fabric load, retaining every original
# placement and the 2ns/1.75ns PHY capture contract. No CPU synthesis or bit.
if {$argc != 3} {error "Expected ROUTED_DCP SHORT_PROOF FRESH_OUT"}
lassign $argv dcp proof out
if {[file exists $out]} {error "Preserve existing evidence"}
proc read_text {path} {set f [open $path r]; set s [read $f]; close $f; return $s}
set receipt [read_text [file join $proof receipt.json]]
foreach required {{"status": "PASS_NATIVE_RX_DESKEW_SHORT"} {"isolated_tx_pad_clock": true} {"rx_phase_degrees": 22.5} {"delay_ps": 0}} {
    if {![string match *$required* $receipt]} {error "Missing short proof: $required"}
}
file mkdir $out
cd $out
file copy [info script] executed_tx_isolation.tcl
file copy [file join $proof native_rgmii.sv] compiled_boundary_source.sv
set_param general.maxThreads 8
open_checkpoint $dcp
set frozen [dict create]
foreach c [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}] {
    dict set frozen $c [list [get_property LOC $c] [get_property BEL $c]]
}
set raw [get_cells u_eth_clk_wiz/inst/clkout1_buf]
set rawInput [get_nets -of_objects [get_pins $raw/I]]
set rawOutput [get_nets -of_objects [get_pins $raw/O]]
set capture [get_clocks -of_objects [get_ports eth_txc]]
if {[llength $capture] != 1} {error "Require the qualified unique forwarded capture clock"}
set captureName [get_property NAME $capture]
set driver [get_pins -leaf -of_objects [get_nets -segments $rawInput] -filter {DIRECTION == OUT}]
if {$driver ne "native_rx_pll/CLKOUT0"} {error "Not the qualified ETH PLL source"}
set padCells [get_cells -hier -filter {REF_NAME == OSERDESE3 && NAME =~ u_rgmii/*}]
if {[llength $padCells] != 6} {error "Require the exact six TX pad DDRs"}
set padPins [get_pins -of_objects $padCells -filter {REF_PIN_NAME == CLK}]
foreach p $padPins {
    if {[get_nets -of_objects $p] ni [get_nets -segments $rawOutput]} {error "Unexpected pad clock $p"}
}
set oqNets [get_nets -of_objects [get_pins -of_objects $padCells -filter {REF_PIN_NAME == OQ}]]
if {[llength $oqNets] != 6} {error "Require six separately routed outputs"}
report_property -file original_raw_bufg.rpt $raw
report_property -file original_control_ddr.rpt [get_cells u_rgmii/tx_control_ddr]
set controlFall [get_pins -of_objects [get_cells u_rgmii/tx_control_ddr] -filter {REF_PIN_NAME == "D[4]"}]
if {[llength $controlFall] != 1} {error "Missing mapped ODDR falling symbol D[4]"}
set fallNet [get_nets -of_objects $controlFall]
set fallDriver [get_pins -leaf -of_objects [get_nets -segments $fallNet] -filter {DIRECTION == OUT}]
set enablePin [get_pins u_rgmii/tx_enable_reg/Q]
if {[llength $enablePin] != 1} {error "Missing qualified TX enable stage"}
set controlMode ""
if {$fallDriver eq $enablePin} {
    # The current board MAC never raises GMII_TX_ER. Synthesis merges the
    # newly pre-registered fall symbol with tx_enable; no logic ECO needed.
    set errors [get_cells -quiet u_rgmii/tx_error_reg]
    if {[llength $errors] != 0} {error "Unexpected unused TX error register"}
    set controlMode "REGISTERED_FALL_SYMBOL_MERGED_CONSTANT_ER0"
} else {
    # Fail closed rather than guessing LUT pin mapping in a new netlist.
    report_property -file unmatched_control_driver.rpt [get_cells -of_objects $fallDriver]
    error "Nonconstant TX_ER requires independently synthesized control-stage ECO: $fallDriver"
}
set mutable [get_nets -segments [concat $rawInput $rawOutput $oqNets]]
set saved [dict create]
foreach n $mutable {dict set saved $n [get_property DONT_TOUCH $n]; set_property DONT_TOUCH FALSE $n}
route_design -unroute -nets [concat [list $rawInput $rawOutput] $oqNets]
create_cell -reference BUFGCE native_tx_pad_buffer
set_property CE_TYPE [get_property CE_TYPE $raw] [get_cells native_tx_pad_buffer]
set_property SIM_DEVICE ULTRASCALE_PLUS [get_cells native_tx_pad_buffer]
set chosen ""
foreach site {BUFGCE_X0Y54 BUFGCE_X0Y56 BUFGCE_X0Y57 BUFGCE_X0Y58 BUFGCE_X0Y59 BUFGCE_X0Y62 BUFGCE_X0Y63} {
    if {[llength [get_cells -quiet -of_objects [get_sites $site]]] == 0} {set chosen $site; break}
}
if {$chosen eq ""} {error "No free Bank66 pad clock buffer"}
set rawCe [get_nets -of_objects [get_pins $raw/CE]]
set ceDriver [get_cells -of_objects [get_pins -leaf -of_objects [get_nets -segments $rawCe] -filter {DIRECTION == OUT}]]
if {[get_property REF_NAME $ceDriver] ne "VCC"} {error "Pad clock must never be CMU-gated"}
connect_net -hier -net $rawInput -objects [get_pins native_tx_pad_buffer/I]
connect_net -hier -net $rawCe -objects [get_pins native_tx_pad_buffer/CE]
create_net native_tx_pad_clock
connect_net -hier -net native_tx_pad_clock -objects [get_pins native_tx_pad_buffer/O]
foreach p $padPins {
    disconnect_net -net [get_nets -of_objects $p] -objects $p
    connect_net -hier -net native_tx_pad_clock -objects $p
}
set_property USER_CLOCK_ROOT X3Y2 [get_nets native_tx_pad_clock]
set_property CLOCK_DELAY_GROUP VALENCE_MAC_TX_PAD_PAIR [get_nets native_tx_pad_clock]
set_property CLOCK_DELAY_GROUP VALENCE_MAC_TX_PAD_PAIR $rawOutput
dict for {n value} $saved {if {$value ne ""} {set_property DONT_TOUCH $value $n}}
set_property DONT_TOUCH TRUE [get_cells native_tx_pad_buffer]
place_cell [list native_tx_pad_buffer $chosen]
set actualTx [get_pins u_rgmii/tx_clock_ddr/CLK]
set txMasters [get_clocks -of_objects $actualTx]
if {[llength $txMasters]!=1 || abs([get_property PERIOD $txMasters]-8.0)>0.001} {error "TX master absent"}
create_generated_clock -name $captureName -source $actualTx \
    -edges {1 2 3} -edge_shift {2.0 2.0 2.0} [get_ports eth_txc]
puts "TX_PAD_TREE_ISOLATED CONTROL=$controlMode BUFFER=$chosen UNCHANGED_PHY_IO_BUDGET"
write_checkpoint modified.dcp
update_clock_routing
route_design -preserve
dict for {name expected} $frozen {
    if {[list [get_property LOC [get_cells $name]] [get_property BEL [get_cells $name]]] ne $expected} {error "Original placement changed: $name"}
}
puts "ORIGINAL_PLACEMENTS_PRESERVED [dict size $frozen]"
write_checkpoint routed.dcp
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file rx_io.rpt
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_io.rpt
report_timing -delay_type min -slack_lesser_than 0 -max_paths 30 -input_pins -file failing_hold.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_cdc -details -file cdc.rpt
report_route_status -file route_status.rpt
report_clocks -file clocks.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
puts "NATIVE_TX_ISOLATION_COMPLETE NO_BIT_GENERATED"
close_design
