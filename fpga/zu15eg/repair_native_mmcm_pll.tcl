# RX global-feedback MMCM / UI frequency PLL / parallel managed clock roots.
# Reuse the original two CMT cells and all CPU/data placements. No bit.
if {$argc != 6} {error "Expected PARENT_DCP SHORT RX_OOC ETH_OOC PARALLEL_SHORT FRESH_OUT"}
lassign $argv dcp proof rxOoc ethOoc parallel out
if {[file exists $out]} {error "Preserve existing evidence"}
set here [file dirname [info script]]
proc read_proof {file} {set f [open $file r]; set value [read $f]; close $f; return $value}
set receipt [read_proof [file join $proof receipt.json]]
foreach expected {{"status": "PASS_NATIVE_RX_DESKEW_SHORT"} {"delay_ps": 0} {"rx_primitive": "MMCME4_ADV"} {"eth_primitive": "PLLE4_ADV"} {"rx_phase_degrees": 0.0}} {
    if {![string match *$expected* $receipt]} {error "Required short evidence absent: $expected"}
}
foreach test {positive eye_early eye_late} {
    set log [read_proof [file join $proof $test.log]]
    if {![string match {*PASS_RGMII_DDR_BOUNDARY*} $log] || [string match {*Fatal:*} $log]} {error "PHY oracle failed: $test"}
}
if {![string match {*PASS_NATIVE_PARALLEL_CLOCK_SHORT*} [read_proof [file join $parallel receipt.json]]]} {error "Managed CE/reset proof missing"}
set clockSource [read_proof [file join $proof native_rx_clock.sv]]
foreach {dir mode} [list $rxOoc ZHOLD $ethOoc INTERNAL] {
    if {[read_proof [file join $dir compiled_clock_source.sv]] ne $clockSource} {error "Normal OOC/short source mismatch"}
    if {![regexp -line [format {^COMPENSATION\s+string\s+false\s+%s\s*$} $mode] [read_proof [file join $dir primitive_post_opt.rpt]]]} {error "Normal lowering mode not proved: $mode"}
}
file mkdir $out
cd $out
file copy [info script] executed_mmcm_pll_eco.tcl
file copy [file join $here native_parallel_clocks.tcl] executed_parallel_helper.tcl
file copy [file join $proof native_rx_clock.sv] experimental_clock_source.sv
set_param general.maxThreads 8
open_checkpoint $dcp
# Instance names are historical ECO names; roles are changed explicitly below.
set rxMmcm [get_cells u_eth_clk_wiz/inst/mmcme4_adv_inst]
set ethPll [get_cells native_rx_pll]
set rxFb [get_cells native_rx_feedback_buffer]
set gates {u_soc/nativeBank/gmac/txManaged_gate/buffer u_soc/nativeBank/gmac/rxManaged_gate/buffer}
set frozen [dict create]
foreach cell [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}] {
    if {$cell ni $gates} {dict set frozen $cell [list [get_property LOC $cell] [get_property BEL $cell]]}
}
if {[get_property REF_NAME $rxMmcm] ne "MMCME4_ADV" || [get_property REF_NAME $ethPll] ne "PLLE4_ADV"} {error "Parent CMT mapping changed"}
set region [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AA7]]]
foreach cell [list $rxMmcm $ethPll] {
    if {[get_clock_regions -of_objects [get_sites [get_property LOC $cell]]] ne $region} {error "CMT not in PHY bank"}
}
proc pin_net {pin} {set net [get_nets -of_objects [get_pins $pin]]; if {[llength $net]!=1} {error "Missing parent connection: $pin"}; return $net}
set ui [pin_net $rxMmcm/CLKIN1]
set pad [pin_net $ethPll/CLKIN]
set cold [pin_net $rxMmcm/RST]
set pllCold [pin_net $ethPll/RST]
set coldDrivers [get_pins -leaf -of_objects [get_nets -segments $cold] -filter {DIRECTION == OUT}]
set pllColdDrivers [get_pins -leaf -of_objects [get_nets -segments $pllCold] -filter {DIRECTION == OUT}]
if {$pllColdDrivers ne $coldDrivers || [llength $coldDrivers]!=1} {error "PLL and MMCM do not share cold reset"}
set txSource [pin_net $rxMmcm/CLKOUT0]
set delaySource [pin_net $rxMmcm/CLKOUT1]
set rxSource [pin_net $ethPll/CLKOUT0]
set ethLock [pin_net $rxMmcm/LOCKED]
set rxLock [pin_net $ethPll/LOCKED]
set feedbackSource [pin_net $ethPll/CLKFBOUT]
set feedbackReturn [pin_net $ethPll/CLKFBIN]
set ground [pin_net $rxMmcm/CLKFBIN]
if {[get_property TYPE $ground] ne "GROUND" || [get_property COMPENSATION $rxMmcm] ne "INTERNAL"} {error "Expected original MMCM INTERNAL/GND parent"}
set clockNets [list $txSource $delaySource $rxSource $feedbackSource $feedbackReturn]
foreach buffer [concat {rx_clock_buffer u_eth_clk_wiz/inst/clkout1_buf u_eth_clk_wiz/inst/clkout2_buf} $gates] {
    lappend clockNets [pin_net $buffer/O]
}
# Never globally unroute UI/CPU, GND or reset; connection edits only remove/add
# the two CMT input leaves. route_design -preserve fills the modified branches.
set mutable [get_nets -segments [concat $clockNets [list $ui $pad $cold $ground $ethLock $rxLock]]]
set touches [dict create]
foreach net $mutable {dict set touches $net [get_property DONT_TOUCH $net]; set_property DONT_TOUCH FALSE $net}
route_design -unroute -nets $clockNets
foreach {pin net} [list $rxMmcm/CLKIN1 $ui $ethPll/CLKIN $pad \
    $rxMmcm/CLKOUT0 $txSource $rxMmcm/CLKOUT1 $delaySource $ethPll/CLKOUT0 $rxSource \
    $rxMmcm/LOCKED $ethLock $ethPll/LOCKED $rxLock \
    $ethPll/CLKFBOUT $feedbackSource $ethPll/CLKFBIN $feedbackReturn $rxMmcm/CLKFBIN $ground] {
    disconnect_net -net $net -objects [get_pins $pin]
}
foreach {pin net} [list $rxMmcm/CLKIN1 $pad $ethPll/CLKIN $ui \
    $rxMmcm/CLKOUT0 $rxSource $ethPll/CLKOUT0 $txSource $ethPll/CLKOUT1 $delaySource \
    $rxMmcm/LOCKED $rxLock $ethPll/LOCKED $ethLock \
    $rxMmcm/CLKFBOUT $feedbackSource $rxMmcm/CLKFBIN $feedbackReturn $ethPll/CLKFBIN $ground] {
    connect_net -hier -net $net -objects [get_pins $pin]
}
set_property -dict {CLKIN1_PERIOD 8.0 CLKFBOUT_MULT_F 8.0 DIVCLK_DIVIDE 1 CLKOUT0_DIVIDE_F 8.0 CLKOUT0_PHASE 0.0 COMPENSATION ZHOLD} $rxMmcm
set_property -dict {CLKIN_PERIOD 4.0 CLKFBOUT_MULT 4 DIVCLK_DIVIDE 1 CLKOUT0_DIVIDE 8 CLKOUT1_DIVIDE 2 CLKOUT0_PHASE 0.0 CLKOUT1_PHASE 0.0 COMPENSATION INTERNAL} $ethPll
set_property DONT_TOUCH TRUE $rxFb
foreach cell [get_cells -hier -filter {REF_NAME == IDELAYE3 && NAME =~ u_rgmii/*}] {
    if {[get_property DELAY_VALUE $cell]!=200 || [get_property DELAY_TYPE $cell] ne "FIXED"} {error "Parent RX delay changed"}
    if {[get_property TYPE [pin_net $cell/CLK]] ne "GROUND"} {error "FIXED CLK must remain unused"}
    set_property DELAY_VALUE 0 $cell
}
source [file join $here native_parallel_clocks.tcl]
# The parent predates RX deskew: synthesis already made its RX managed BUFG
# parallel to the original PAD, not to the later experimental PLL. Upgrade
# only this exactly-audited pad driver to the new raw MMCM source; CE/reset
# policy stays intact. The generic helper must still reject unknown drivers.
set rxGate [lindex $gates 1]
set managedInput [pin_net $rxGate/I]
set managedDriver [get_pins -leaf -of_objects [get_nets -segments $managedInput] -filter {DIRECTION == OUT}]
set padDriver [get_pins -leaf -of_objects [get_nets -segments $pad] -filter {DIRECTION == OUT}]
if {$managedDriver eq $padDriver && $padDriver eq "rx_clock_pad/IBUFCTRL_INST/O"} {
    disconnect_net -net $managedInput -objects [get_pins $rxGate/I]
    connect_net -hier -net $rxSource -objects [get_pins $rxGate/I]
    puts "RX_MANAGED_PAD_BYPASS_REMOVED $padDriver -> $rxMmcm/CLKOUT0"
}
valence_native_parallel_clocks
set clockOutputs [list $feedbackReturn]
foreach buffer [concat {rx_clock_buffer u_eth_clk_wiz/inst/clkout1_buf} $gates] {lappend clockOutputs [pin_net $buffer/O]}
set_property USER_CLOCK_ROOT $region $clockOutputs
set rxOutputs [get_nets -of_objects [get_pins [list rx_clock_buffer/O [lindex $gates 1]/O]]]
set_property CLOCK_DELAY_GROUP VALENCE_MAC_RX [concat $rxOutputs $feedbackReturn]
set_property UNAVAILABLE_DURING_CALIBRATION TRUE [get_ports {eth_txd[1]}]
set resetPort [get_ports c0_ddr4_reset_n]
set resetStarts [filter [all_fanin -flat -startpoints_only -to $resetPort] {REF_PIN_NAME == C}]
if {$resetStarts ne {u_ddr/inst/u_ddr4_mem_intfc/u_mig_ddr4_phy/u_ddr_cal_top/cal_RESET_n_reg[0]/C} && $resetStarts ne {u_ddr/inst/u_ddr4_mem_intfc/u_ddr_cal_top/cal_RESET_n_reg[0]/C}} {error "MIG reset output changed"}
set_max_delay -datapath_only 20.0 -from $resetStarts -to $resetPort
# Exclude the gates being relocated from the occupied track search. A fresh
# free track is only a heuristic: update_clock_routing is the routing authority.
set occupied {}
foreach cell [get_cells -hier -filter {REF_NAME == BUFGCE && LOC != ""}] {
    if {$cell ni $gates && [regexp {BUFGCE_X0Y([0-9]+)} [get_property LOC $cell] -> y]} {lappend occupied [expr {$y%24}]}
}
foreach gate $gates {
    set target ""
    foreach site [lsort -dictionary [get_sites -of_objects $region -filter {SITE_TYPE == BUFGCE}]] {
        if {[llength [get_cells -quiet -of_objects $site]]==0 && [regexp {BUFGCE_X0Y([0-9]+)} $site -> y] && [expr {$y%24}] ni $occupied} {
            set target $site; lappend occupied [expr {$y%24}]; break
        }
    }
    if {$target eq ""} {error "No peripheral track; preserve CPU"}
    puts "ONLY_PERIPHERAL_BUFG_MOVE $gate [get_property LOC [get_cells $gate]] -> $target"
    set_property IS_LOC_FIXED FALSE [get_cells $gate]
    place_cell [list $gate $target]
}
dict for {net value} $touches {if {$value ne ""} {set_property DONT_TOUCH $value $net}}
set actualTx [get_pins u_rgmii/tx_clock_ddr/CLK]
set txMasters [get_clocks -of_objects $actualTx]
if {[llength $txMasters]!=1 || abs([get_property PERIOD $txMasters]-8.0)>0.001} {error "TX master absent"}
create_generated_clock -name phy_tx_capture -source $actualTx -edges {1 2 3} -edge_shift {2.0 2.0 2.0} [get_ports eth_txc]
write_checkpoint modified.dcp
update_clock_routing
route_design -preserve
dict for {name expected} $frozen {
    if {[list [get_property LOC [get_cells $name]] [get_property BEL [get_cells $name]]] ne $expected} {error "Original data/CPU placement changed: $name"}
}
puts "ORIGINAL_PLACEMENTS_PRESERVED [dict size $frozen] ONLY_TWO_PERIPHERAL_BUFGS_MAY_MOVE"
foreach {pin period role} {
    u_rgmii/tx_clock_ddr/CLK 8.0 TX_RAW
    u_rgmii/receive[0].rx_ddr/C 8.0 RX_RAW
    u_rgmii/delay_control/REFCLK 2.0 CALIBRATION
} {
    set clocks [get_clocks -of_objects [get_pins $pin]]
    if {[llength $clocks]!=1 || abs([get_property PERIOD $clocks]-$period)>0.001} {error "Clock role/frequency mismatch: $role $clocks"}
    puts "ACTUAL_CLOCK_ROLE $role $clocks [get_property PERIOD $clocks]"
}
write_checkpoint routed.dcp
report_property -file rx_mmcm.rpt $rxMmcm
report_property -file eth_pll.rpt $ethPll
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
puts "NATIVE_MMCM_PLL_ECO_COMPLETE NO_BIT_GENERATED"
close_design
