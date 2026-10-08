# Experimental physical recipe; NOT a timing result. Run one rate per STA
# scenario on the complete board. Never combine this with legacy TX constraints.
# The inherited 1.250ns PHY+PCB setup/hold budget is unchanged at every rate.
source [file join [file dirname [info script]] native_quarter_clock_constraints.tcl]

proc valence_trispeed_quarter_audit {hier} {
    set clock [get_cells -quiet $hier/tx_clock_ddr]
    set lanes [get_cells -quiet "$hier/transmit*.data_ddr"]
    if {[llength $clock]!=1 || [llength $lanes]!=5} {error "Require six real tri-speed ODDR cells"}
    set clkNet [get_nets -of_objects [get_pins $clock/CLK]]
    set rstNet [get_nets -of_objects [get_pins $clock/RST]]
    foreach c [concat $clock $lanes] {
        if {[get_property REF_NAME $c] ne "OSERDESE3" || [get_property ODDR_MODE $c] ne "TRUE" ||
            [get_property OSERDES_D_BYPASS $c] ne "FALSE" ||
            [get_property IS_CLK_INVERTED $c] ni {0 1'b0} ||
            [get_property IS_RST_INVERTED $c] ni {{} 0 1'b0} ||
            [get_nets -of_objects [get_pins $c/CLK]] ne $clkNet ||
            [get_nets -of_objects [get_pins $c/RST]] ne $rstNet} {
            error "Tri-speed pad DDRs do not share the actual250MHz clock/reset: $c"
        }
    }
    foreach c $lanes {
        set d0 [get_nets -of_objects [valence_quarter_data_pin $c 0]]
        set d4 [get_nets -of_objects [valence_quarter_data_pin $c 4]]
        if {[llength $d0]!=1 || $d0 ne $d4} {error "Tri-speed D0/D4 are not identical: $c"}
    }
    set carry [get_cells -quiet $hier/previous_clock_reg]
    if {[llength $carry]!=1 || [get_property REF_NAME $carry] ne "FDCE" ||
        [get_property INIT $carry] ne "1'b0" || [get_property IS_C_INVERTED $carry] ni {{} 0 1'b0} ||
        [get_nets -of_objects [get_pins $carry/C]] ne $clkNet ||
        [get_nets -of_objects [get_pins $carry/CLR]] ne $rstNet ||
        [get_property TYPE [get_nets -of_objects [get_pins $carry/CE]]] ne "POWER"} {
        error "Unproved positive-edge previous-clock carry"
    }
    if {[get_nets -of_objects [get_pins $carry/Q]] ne [get_nets -of_objects [valence_quarter_data_pin $clock 0]] ||
        [get_nets -of_objects [get_pins $carry/D]] ne [get_nets -of_objects [valence_quarter_data_pin $clock 4]]} {
        error "TXC D1 must repeat the previous D2 clock symbol exactly"
    }
    set phase [get_cells -quiet $hier/phase_high_reg]
    if {[llength $phase]!=1 || [get_property REF_NAME $phase] ne "FDPE" ||
        [get_property INIT $phase] ne "1'b1" || [get_property IS_C_INVERTED $phase] ni {{} 0 1'b0} ||
        [get_nets -of_objects [get_pins $phase/C]] ne $clkNet ||
        [get_nets -of_objects [get_pins $phase/PRE]] ne $rstNet} {
        error "Unproved preset-high quarter phase/reset alignment"
    }
    set phaseQ [get_nets -of_objects [get_pins $phase/Q]]
    set inverse [get_nets -of_objects [get_pins $phase/D]]
    set driver [get_pins -leaf -of_objects [get_nets -segments $inverse] -filter {DIRECTION == OUT}]
    if {[llength $driver]!=1} {error "Quarter phase feedback has multiple drivers"}
    set inversion [get_cells -of_objects $driver]
    if {[get_property REF_NAME $inversion] eq "INV"} {
        set input [get_pins $inversion/I]
    } elseif {[get_property REF_NAME $inversion] eq "LUT1" && [get_property INIT $inversion] in {2'h1 2'b01}} {
        set input [get_pins $inversion/I0]
    } else {error "Quarter phase feedback is not exact inversion"}
    if {[get_nets -of_objects $input] ne $phaseQ} {error "Quarter phase must invert its own Q"}
    set actual [get_clocks -of_objects [get_pins $clock/CLK]]
    if {[llength $actual]!=1 || abs([get_property PERIOD $actual]-4.0)>0.001} {error "Pad clock is not250MHz"}
    puts "TRISPEED_QUARTER_TOPOLOGY six_common_clock_reset five_exact_D0_D4_pairs previous_clock_carry"
    return $lanes
}

proc valence_trispeed_quarter_tx_constraints {hier mbps} {
    set lanes [valence_trispeed_quarter_audit $hier]
    switch -- $mbps {
        1000 {set edges {2 4 6}; set period 8.0}
        100  {set edges {2 12 22}; set period 40.0}
        10   {set edges {2 102 202}; set period 400.0}
        default {error "Use one explicit10/100/1000 STA scenario"}
    }
    if {[llength [get_clocks -quiet phy_tx_capture]]} {error "Do not overwrite a legacy/existing capture clock"}
    set source [get_pins -quiet $hier/tx_clock_ddr/CLK]
    set txc [get_ports -quiet eth_txc]
    set outputs [get_ports -quiet {eth_txd[*] eth_tx_ctl}]
    if {[llength $source]!=1 || [llength $txc]!=1 || [llength $outputs]!=5} {error "Missing real TX pin/source endpoints"}
    # Same +2ns edge placement at all speeds. No nominal source-latency bias.
    create_generated_clock -name phy_tx_capture -source $source -edges $edges $txc
    if {abs([get_property PERIOD [get_clocks phy_tx_capture]]-$period)>0.001} {error "Wrong generated TXC period"}
    foreach fall {0 1} {
        set extra {}
        if {$fall} {set extra {-clock_fall -add_delay}}
        set_output_delay -clock phy_tx_capture {*}$extra -max 1.250 $outputs
        set_output_delay -clock phy_tx_capture {*}$extra -min -1.250 $outputs
    }
    # Only the physically impossible falling DATA-output transition is removed,
    # after proving all five D0/D4 pairs are identical in the actual netlist.
    # Internal D/clock/reset, all rising data paths and all CDC buses stay timed.
    set padClock [get_clocks -of_objects $source]
    foreach c $lanes {
        set oq [get_pins -of_objects $c -filter {REF_PIN_NAME == OQ}]
        if {[llength $oq]!=1} {error "Missing actual pad-only OQ exception endpoint"}
        set_false_path -fall_from $padClock -through $oq -to $outputs
    }
    puts "TRISPEED_TX_SCENARIO mbps=$mbps period=$period setup_hold_budget_ns=1.250"
}

# RX: use8/40/400ns recovered-clock scenarios on direct IBUF/BUFG capture.
# Apply measured PHY RXDLY and board-skew min/max budgets at BOTH control edges;
# data also needs both edges at1G. Preserve the original pin/IDELAY calibration
# budget, and prove every DDR capture path. No global async clock groups,
# broad CDC false paths, unchecked multicycle paths or legacy RX-MMCM clocks.
