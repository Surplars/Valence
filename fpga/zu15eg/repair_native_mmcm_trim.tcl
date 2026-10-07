# RX eye centering + restore serial TX CMU gate (avoid unmatched raw/managed
# parallel-tree hold skew). Tiny clock proof first; keep CPU/data placement.
if {$argc != 4} {error "Expected SWAPPED_ROUTED_DCP RX_SHORT RX_OOC FRESH_OUT"}
lassign $argv dcp proof ooc out
if {[file exists $out]} {error "Preserve existing evidence"}
proc proof_text {file} {set f [open $file r]; set text [read $f]; close $f; return $text}
set receipt [proof_text [file join $proof receipt.json]]
foreach required {{"status": "PASS_NATIVE_RX_DESKEW_SHORT"} {"rx_phase_degrees": 22.5} {"delay_ps": 0} {"rx_primitive": "MMCME4_ADV"}} {
    if {![string match *$required* $receipt]} {error "RX proof absent: $required"}
}
set source [proof_text [file join $proof native_rx_clock.sv]]
if {$source ne [proof_text [file join $ooc compiled_clock_source.sv]]} {error "OOC/short source differs"}
set props [proof_text [file join $ooc primitive_post_opt.rpt]]
if {![regexp -line {^COMPENSATION\s+string\s+false\s+ZHOLD\s*$} $props] ||
    ![regexp -line {^CLKOUT0_PHASE\s+double\s+false\s+22.500\s*$} $props]} {error "Normal RX lowering/phase not proved"}
file mkdir $out
cd $out
file copy [info script] executed_mmcm_trim_eco.tcl
file copy [file join $proof native_rx_clock.sv] experimental_clock_source.sv
set_param general.maxThreads 8
open_checkpoint $dcp
set frozen [dict create]
foreach cell [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}] {
    dict set frozen $cell [list [get_property LOC $cell] [get_property BEL $cell]]
}
set mmcm [get_cells u_eth_clk_wiz/inst/mmcme4_adv_inst]
set pll [get_cells native_rx_pll]
if {[get_property COMPENSATION $mmcm] ne "ZHOLD" || [get_property CLKOUT0_PHASE $mmcm]!=0 ||
    [get_property COMPENSATION $pll] ne "INTERNAL"} {error "Unexpected parent CMT roles"}
foreach pin {u_eth_clk_wiz/inst/mmcme4_adv_inst/CLKIN1 native_rx_pll/CLKIN} driver {
    rx_clock_pad/IBUFCTRL_INST/O u_ddr/inst/u_ddr4_infrastructure/u_bufg_divClk/O
} {
    set actual [get_pins -leaf -of_objects [get_nets -segments -of_objects [get_pins $pin]] -filter {DIRECTION == OUT}]
    if {$actual ne $driver} {error "Wrong CMT input lineage: $pin $actual"}
}
set raw [get_cells u_eth_clk_wiz/inst/clkout1_buf]
set gate [get_cells u_soc/nativeBank/gmac/txManaged_gate/buffer]
if {[get_property CE_TYPE $gate] ne "SYNC"} {error "CMU gate lost glitchless CE"}
set input [get_nets -of_objects [get_pins $gate/I]]
set rawInput [get_nets -of_objects [get_pins $raw/I]]
set rawOutput [get_nets -of_objects [get_pins $raw/O]]
set gateOutput [get_nets -of_objects [get_pins $gate/O]]
set inputDriver [get_pins -leaf -of_objects [get_nets -segments $input] -filter {DIRECTION == OUT}]
if {$inputDriver ne "native_rx_pll/CLKOUT0" || $rawInput ni [get_nets -segments $input]} {error "Parent TX clocks not parallel PLL outputs"}
set mutable [get_nets -segments [concat $input $rawOutput $gateOutput]]
set saved [dict create]
foreach net $mutable {dict set saved $net [get_property DONT_TOUCH $net]; set_property DONT_TOUCH FALSE $net}
route_design -unroute -nets [list $rawOutput $gateOutput]
disconnect_net -net $input -objects [get_pins $gate/I]
connect_net -hier -net $rawOutput -objects [get_pins $gate/I]
# Vivado does not support reset_property on CLOCK_DELAY_GROUP. Give the serial
# gate its own singleton group; never ask it to match the upstream raw tree.
set_property CLOCK_DELAY_GROUP VALENCE_MAC_TX_SERIAL $gateOutput
set_property CLKOUT0_PHASE 22.5 $mmcm
dict for {net value} $saved {if {$value ne ""} {set_property DONT_TOUCH $value $net}}
puts "RX_MMCM_LEGAL_PHASE_22_5_DEG_HALF_NS TX_CMU_GATE_SERIAL_CE_RESET_UNCHANGED"
write_checkpoint modified.dcp
update_clock_routing
route_design -preserve
dict for {name expected} $frozen {
    if {[list [get_property LOC [get_cells $name]] [get_property BEL [get_cells $name]]] ne $expected} {error "Placement changed: $name"}
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
puts "NATIVE_MMCM_TRIM_COMPLETE NO_BIT_GENERATED"
close_design
