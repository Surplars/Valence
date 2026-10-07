# Board-only candidate: RX PLL feedback deskew, 200ps data delay, lock guard.
# Keep the conservative PHY input/output budgets and every CPU/data placement.
if {$argc != 3} {error "Expected ROUTED_PARENT_DCP SHORT_PROOF_DIR FRESH_OUTPUT_DIR"}
lassign $argv dcp proof out
if {[file exists $out]} {error "Preserve existing evidence"}
set channel [open [file join $proof receipt.json] r]
set receipt [read $channel]
close $channel
if {![string match {*PASS_NATIVE_RX_DESKEW_SHORT*} $receipt] || ![regexp {"delay_ps": 200} $receipt]} {
    error "Required 200ps RX clock/DDR short proof missing"
}
file mkdir $out
cd $out
file copy [info script] executed_rx_eco.tcl
set_param general.maxThreads 8
open_checkpoint $dcp
set frozen [dict create]
foreach cell [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}] {
    dict set frozen $cell [list [get_property LOC $cell] [get_property BEL $cell]]
}
set region [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AA7]]]
if {[llength $region]!=1} {error "RX clock region missing"}
set pllSite ""
foreach site [get_sites -of_objects $region -filter {NAME =~ PLL_X*}] {
    if {[llength [get_cells -quiet -of_objects $site]]==0} {set pllSite $site; break}
}
if {$pllSite eq ""} {error "No free same-bank RX PLL"}
set fbSite ""
foreach site [get_sites -of_objects $region -filter {SITE_TYPE == BUFGCE}] {
    if {[llength [get_cells -quiet -of_objects $site]]==0} {set fbSite $site; break}
}
if {$fbSite eq ""} {error "No free same-bank feedback BUFGCE"}
set rawI [get_pins rx_clock_buffer/I]
set padNet [get_nets -of_objects $rawI]
set padDriver [get_pins -leaf -of_objects [get_nets -segments $padNet] -filter {DIRECTION == OUT}]
if {$padDriver ne "rx_clock_pad/IBUFCTRL_INST/O"} {error "Unexpected RX pad source: $padDriver"}
set rawNet [get_nets -of_objects [get_pins rx_clock_buffer/O]]
# Use the actual surviving board/UI reset net at the Ethernet MMCM input;
# synthesis removes the source-level board_reset alias. No PHY/RX lock loop.
set boardReset [get_nets -of_objects [get_pins u_eth_clk_wiz/inst/mmcme4_adv_inst/RST]]
set ground [get_nets -of_objects [get_pins {u_rgmii/receive_delay[0].data_delay/CLK}]]
puts "PARENT_RX_COLD_RESET $boardReset GROUND $ground TYPE [get_property TYPE $ground]"
if {[llength $boardReset]!=1 || [get_property TYPE $ground] ne "GROUND"} {error "Reset or constant mapping changed"}
set oldRequest [get_nets -of_objects [get_pins {rx_reset_pipe_reg[0]/PRE}]]
set oldRequestTouch [get_property DONT_TOUCH $oldRequest]
set_property DONT_TOUCH FALSE $oldRequest
set rawDontTouch [get_property DONT_TOUCH $rawNet]
set padDontTouch [get_property DONT_TOUCH $padNet]
set_property DONT_TOUCH FALSE [concat $rawNet $padNet]
route_design -unroute -nets [list $rawNet $padNet]
create_cell -reference PLLE4_ADV native_rx_pll
set_property -dict {CLKIN_PERIOD 8.0 CLKFBOUT_MULT 6 DIVCLK_DIVIDE 1 CLKOUT0_DIVIDE 6 CLKOUT0_PHASE 0.0 CLKOUT0_DUTY_CYCLE 0.5 COMPENSATION AUTO REF_JITTER 0.01 CLKOUTPHY_MODE VCO} [get_cells native_rx_pll]
create_cell -reference BUFGCE native_rx_feedback_buffer
set_property CE_TYPE SYNC [get_cells native_rx_feedback_buffer]
create_net native_rx_feedback
create_net native_rx_feedback_buffered
create_net native_rx_source
create_net native_rx_locked
create_net native_rx_guarded_request
create_cell -reference LUT2 native_rx_lock_guard
set_property INIT 4'hB [get_cells native_rx_lock_guard]
foreach pin [get_pins -of_objects [get_cells native_rx_pll] -filter {DIRECTION == IN}] {
    switch -- [get_property REF_PIN_NAME $pin] {
        CLKIN {connect_net -net $padNet -objects $pin}
        CLKFBIN {connect_net -net native_rx_feedback_buffered -objects $pin}
        RST {connect_net -hier -net $boardReset -objects $pin}
        default {connect_net -hier -net $ground -objects $pin}
    }
}
set power [get_nets -of_objects [get_pins rx_clock_buffer/CE]]
if {[get_property TYPE $power] ne "POWER"} {error "Raw RX CE not always enabled"}
connect_net -net $power -objects [get_pins native_rx_feedback_buffer/CE]
connect_net -net native_rx_feedback -objects [get_pins {native_rx_pll/CLKFBOUT native_rx_feedback_buffer/I}]
connect_net -net native_rx_feedback_buffered -objects [get_pins native_rx_feedback_buffer/O]
connect_net -net native_rx_locked -objects [get_pins {native_rx_pll/LOCKED native_rx_lock_guard/I1}]
connect_net -net $oldRequest -objects [get_pins native_rx_lock_guard/I0]
disconnect_net -net $padNet -objects $rawI
connect_net -net native_rx_source -objects [concat [get_pins native_rx_pll/CLKOUT0] $rawI]
set resetPins {}
set rxResetCells [get_cells {rx_reset_pipe_reg[0] rx_reset_pipe_reg[1] rx_reset_pipe_reg[2]}]
set_property ASYNC_REG FALSE $rxResetCells
for {set stage 0} {$stage<3} {incr stage} {
    set pin [get_pins [format {rx_reset_pipe_reg[%d]/PRE} $stage]]
    if {[get_nets -of_objects $pin] ne $oldRequest} {error "RX asynchronous guard not common"}
    disconnect_net -net $oldRequest -objects $pin
    lappend resetPins $pin
}
connect_net -net native_rx_guarded_request -objects [concat [get_pins native_rx_lock_guard/O] $resetPins]
foreach pin [get_pins -of_objects [get_cells native_rx_pll] -filter {DIRECTION == IN}] {
    if {[llength [get_nets -of_objects $pin]]!=1} {error "Unconnected experimental PLL input: $pin"}
}
set_property ASYNC_REG TRUE $rxResetCells
if {$oldRequestTouch ne ""} {set_property DONT_TOUCH $oldRequestTouch $oldRequest}
foreach cell [get_cells -hier -filter {REF_NAME == IDELAYE3 && NAME =~ u_rgmii/*}] {
    if {[get_property DELAY_VALUE $cell]!=1100 || [get_property DELAY_TYPE $cell] ne "FIXED"} {error "RX delay parent changed"}
    set_property DELAY_VALUE 200 $cell
}
place_cell [list native_rx_pll $pllSite native_rx_feedback_buffer $fbSite]
set lutTarget ""
foreach x {100 99 101 98 102} {
    foreach y {96 95 97 94 98} {
        foreach letter {A B C D E F G H} {
            set bel [get_bels -quiet SLICE_X${x}Y${y}/${letter}6LUT]
            set half [get_bels -quiet SLICE_X${x}Y${y}/${letter}5LUT]
            if {[llength $bel]==1 && [llength [get_cells -of_objects [concat $bel $half]]]==0} {
                set lutTarget $bel; break
            }
        }
        if {$lutTarget ne ""} {break}
    }
    if {$lutTarget ne ""} {break}
}
if {$lutTarget eq ""} {error "No free local RX guard LUT; preserve CPU placements"}
place_cell [list native_rx_lock_guard $lutTarget]
set feedbackNet [get_nets native_rx_feedback_buffered]
set_property USER_CLOCK_ROOT $region [concat $rawNet $feedbackNet]
set_property CLOCK_DELAY_GROUP VALENCE_RX_DESKEW [concat $rawNet $feedbackNet]
if {$rawDontTouch ne ""} {set_property DONT_TOUCH $rawDontTouch $rawNet}
if {$padDontTouch ne ""} {set_property DONT_TOUCH $padDontTouch $padNet}
# Retain the real TX model; unused CLKDIV must never hide output paths.
set txSource [get_pins u_rgmii/tx_clock_ddr/CLK]
set txMasters [get_clocks -of_objects $txSource]
if {[llength $txMasters]!=1 || abs([get_property PERIOD $txMasters]-8.0)>0.001} {error "TX clock coverage invalid"}
create_generated_clock -name phy_tx_capture -source $txSource -edges {1 2 3} -edge_shift {2.0 2.0 2.0} [get_ports eth_txc]
write_checkpoint modified.dcp
update_clock_routing
route_design -preserve
dict for {name expected} $frozen {
    if {[list [get_property LOC [get_cells $name]] [get_property BEL [get_cells $name]]] ne $expected} {error "Data/CPU placement changed: $name"}
}
puts "ORIGINAL_PLACEMENTS_PRESERVED [dict size $frozen]"
set rxClock [get_clocks -of_objects [get_pins {u_rgmii/receive[0].rx_ddr/C}]]
if {[llength $rxClock]!=1 || abs([get_property PERIOD $rxClock]-8.0)>0.001} {error "New RX sampling clock invalid"}
puts "VALID_RX_SAMPLING_CLOCK $rxClock [get_property PERIOD $rxClock]"
write_checkpoint routed.dcp
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_timing_summary -delay_type min_max -datasheet -input_pins -file timing_datasheet.rpt
report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file rx_io.rpt
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_io.rpt
report_timing -delay_type min -slack_lesser_than 0 -max_paths 30 -input_pins -file failing_hold.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_cdc -details -file cdc.rpt
report_route_status -file route_status.rpt
report_clocks -file clocks.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
puts "NATIVE_RX_DESKEW_ECO_COMPLETE NO_BIT_GENERATED"
close_design
