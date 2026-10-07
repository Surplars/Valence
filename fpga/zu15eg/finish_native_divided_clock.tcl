# Complete the saved two-DIV full-board candidate with the normally synthesized
# third pad-only DIV and registered rising-edge CLR releases. No CPU synthesis.
if {$argc!=5} {error "Expected SOURCE_DIR TWO_DIV_ROUTED CURRENT_SHORT NORMAL_OOC FRESH_OUT"}
lassign $argv src baseline proof normal out
if {[file exists $out]} {error "Preserve evidence"}
proc pad_read {p} {set f [open $p r]; set s [read $f]; close $f; return $s}
set receipt [pad_read [file join $proof receipt.json]]
foreach token {{"status": "PASS_NATIVE_TX90_SHORT"} {"pad_clock_isolated": true} {"hardware_phy_init_enabled": false}} {
    if {![string match *$token* $receipt]} {error "Missing current short proof: $token"}
}
set source [pad_read [file join $normal compiled_clock_source.sv]]
if {$source ne [pad_read [file join $proof native_gmac_divided_clock.sv]] || $source ne [pad_read [file join $src native_gmac_divided_clock.sv]]} {error "Normal/short/current clock source mismatch"}
file mkdir $out
cd $out
file copy [info script] executed_finish.tcl
file copy [file join $normal compiled_clock_source.sv] compiled_clock_source.sv
file copy [file join $src native_divided_clock_constraints.tcl] tested_clock_constraints.tcl
set_param general.maxThreads 8
open_checkpoint [file join $normal post_opt.dcp]
set normalPad [get_cells clock_dut/pad_div]
if {[get_property REF_NAME $normalPad] ne "BUFGCE_DIV" || [get_property BUFGCE_DIVIDE $normalPad]!=4} {error "Unproved pad divider"}
set props [dict create]
foreach key {BUFGCE_DIVIDE SIM_DEVICE IS_CE_INVERTED IS_CLR_INVERTED DONT_TOUCH} {
    set value [get_property $key $normalPad]
    if {$value ne ""} {dict set props $key $value}
}
set normalStages [get_cells {clock_dut/phase_reset_reg[*]}]
if {[llength $normalStages]!=3} {error "Missing normally synthesized release chain"}
foreach c $normalStages {
    # Normal synthesis omits the zero/default inversion parameter.
    if {[get_property REF_NAME $c] ne "FDPE" || [get_property IS_C_INVERTED $c] ni {{} 0 1'b0} || ![get_property ASYNC_REG $c]} {error "Release must be own rising-edge FDPE"}
}
set props [string range "${props} " 0 end-1]
close_design
open_checkpoint $baseline
if {[llength [get_cells -hier -filter {REF_NAME == BUFGCE_DIV}]]!=2} {error "Expected saved two-DIV candidate"}
set raw u_eth_clk_wiz/inst/clkout1_buf
set forward native_tx90_forward_buffer
set pad native_tx_pad_divider
proc pad_net {pin} {set n [get_nets -of_objects [get_pins $pin]]; if {[llength $n]!=1} {error "Missing $pin"}; return $n}
set rawNet [pad_net $raw/O]
set forwardNet [pad_net $forward/O]
set refNet [pad_net u_eth_clk_wiz/inst/clkout2_buf/O]
set controls [get_cells -hier -filter {NAME =~ native_tx_divider_* && REF_NAME == FDPE}]
if {[llength $controls]!=3} {error "Missing saved release chain"}
# Lock the existing placements in one native operation; route_design -preserve
# may only change routing. The third clock buffer is the sole added placement.
set existing [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}]
set_property IS_LOC_FIXED TRUE $existing
puts "EXISTING_PLACEMENTS_LOCKED [llength $existing] CPU_RX_NOT_REPLACED"
set saved [dict create]
foreach n [get_nets -segments [list $rawNet $forwardNet $refNet]] {
    dict set saved [get_property NAME $n] [get_property DONT_TOUCH $n]
    set_property DONT_TOUCH FALSE $n
}
route_design -unroute -nets [list $rawNet $forwardNet $refNet]
set_property IS_C_INVERTED 1'b0 $controls
create_cell -reference BUFGCE_DIV $pad
dict for {key value} $props {set_property $key $value [get_cells $pad]}
create_net native_tx_pad_clock
connect_net -hier -net $refNet -objects [get_pins $pad/I]
connect_net -hier -net [pad_net $raw/CE] -objects [get_pins $pad/CE]
connect_net -hier -net [pad_net $raw/CLR] -objects [get_pins $pad/CLR]
connect_net -hier -net native_tx_pad_clock -objects [get_pins $pad/O]
set dataPins [list [get_pins u_rgmii/tx_control_ddr/CLK]]
for {set i 0} {$i<4} {incr i} {lappend dataPins [get_pins [format {u_rgmii/lanes[%d].tx_ddr/CLK} $i]]}
if {[llength $dataPins]!=5} {error "Expected five real data/control CLK pins"}
foreach p $dataPins {
    set old [get_nets -of_objects $p]
    disconnect_net -net $old -objects $p
    connect_net -hier -net native_tx_pad_clock -objects $p
}
set region [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AC8]]]
set sites [lsort -dictionary [get_sites -of_objects $region -filter {SITE_TYPE == BUFGCE_DIV}]]
set site [lindex $sites 3]
if {[llength [get_cells -quiet -of_objects $site]]} {error "Pad divider site occupied: $site"}
place_cell [list $pad $site]
set_property USER_CLOCK_ROOT $region [get_nets native_tx_pad_clock]
# Vivado cannot reset CLOCK_DELAY_GROUP. Move the internal clock to its own
# group so that only the two pad-facing clocks are delay-balanced together.
set_property CLOCK_DELAY_GROUP VALENCE_TX_INTERNAL_RAW $rawNet
set_property CLOCK_DELAY_GROUP VALENCE_TX_PAD_PAIR [get_nets [list native_tx_pad_clock $forwardNet]]
dict for {name value} $saved {
    if {$value ne ""} {set_property DONT_TOUCH $value [get_nets $name]}
}
source [file join $src native_divided_clock_constraints.tcl]
valence_divided_tx_cells native_tx_ref_pll $raw $pad $forward
create_generated_clock -name phy_tx_capture -source [get_pins u_rgmii/tx_clock_ddr/CLK] -divide_by 1 [get_ports eth_txc]
foreach extra {{} {-clock_fall -add_delay}} {
    set_output_delay -clock phy_tx_capture -max 1.250 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
    set_output_delay -clock phy_tx_capture -min -1.250 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
}
puts "PAD_CLOCK_PLACED $site; THREE_RAW_PHASE_STAGES_RISING; IO_BUDGET_UNCHANGED"
write_checkpoint modified.dcp
update_clock_routing
route_design -preserve
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_io.rpt
report_timing -to [get_pins [list $raw/CLR $pad/CLR $forward/CLR]] -delay_type min_max -max_paths 12 -input_pins -file divider_clear.rpt
report_timing -from $controls -delay_type min_max -max_paths 12 -input_pins -file phase_release.rpt
report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file rx_io.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_timing -delay_type max -max_paths 20 -input_pins -file setup_paths.rpt
report_timing -delay_type min -max_paths 20 -input_pins -file hold_paths.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_cdc -details -file cdc.rpt
report_route_status -file route_status.rpt
report_clocks -file clocks.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
write_checkpoint routed.dcp
puts "NATIVE_PAD_PAIR_FULL_BOARD_ROUTED NO_CPU_SYNTHESIS_NO_BIT"
close_design
