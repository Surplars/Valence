# Experimental physical recipe; NOT a timing result. Run one rate per STA
# scenario on the complete board. Never combine this with legacy TX constraints.
# The inherited 1.250ns PHY+PCB setup/hold budget is unchanged at every rate.
source [file join [file dirname [info script]] native_quarter_clock_constraints.tcl]

# Optional expected mode lets qualification require a retained T1 FF explicitly.
# Auto keeps the default board recipe compatible with either source parameter;
# it still audits the detected circuit and never adds a reset exception.
proc valence_trispeed_quarter_audit {hier {localResetRelease auto}} {
    if {![info exists ::valence_native_mac_mode::selected]} {
        error "Source the bound native-mac-mode.tcl before granting any pad exception"
    }
    if {$localResetRelease ne "auto" && $localResetRelease != $::valence_native_mac_mode::t1} {
        error "Reset mode conflicts with the bound synthesis contract"
    }
    valence_native_mac_assert_mode $hier
    # Fresh semantic role proof is mandatory for both modes. The ON proof has
    # no fixed twelve-register condition. It returns only the actual five lanes.
    return $::valence_mac_roles::last_lanes
}
# Retained for diagnostic comparison only; never called by the timing recipe.
proc valence_trispeed_quarter_legacy_diagnostic {hier {localResetRelease auto}} {
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
        [get_property INIT $carry] ne "1'b0" || [get_property IS_INVERTED [get_pins $carry/C]] ni {0 1'b0} ||
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
        [get_property INIT $phase] ne "1'b1" || [get_property IS_INVERTED [get_pins $phase/C]] ni {0 1'b0} ||
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
    # All twelve falling-edge payload/clock registers share the phase/carry/DDR
    # reset epoch. Proving the DDR resets alone would miss a bypassed bank.
    set symbols [concat [get_cells -quiet "$hier/low_symbol_reg*"] \
        [get_cells -quiet "$hier/high_symbol_reg*"] \
        [get_cells -quiet $hier/low_clock_reg] [get_cells -quiet $hier/high_clock_reg]]
    if {[llength $symbols]!=12} {error "Require twelve tri-speed symbol/clock registers"}
    foreach c $symbols {
        if {[get_property REF_NAME $c] ne "FDCE" || [get_property INIT $c] ne "1'b0" ||
            [get_property IS_INVERTED [get_pins $c/C]] ni {1 1'b1} ||
            [get_nets -of_objects [get_pins $c/C]] ne $clkNet ||
            [get_nets -of_objects [get_pins $c/CLR]] ne $rstNet} {
            error "Unproved falling-edge symbol/shared reset epoch: $c"
        }
    }
    set localRelease [get_cells -quiet $hier/pad_release.pad_release_reset_reg]
    if {$localResetRelease eq "auto"} {set localResetRelease [expr {[llength $localRelease]!=0}]}
    if {$localResetRelease ni {0 1}} {error "Use reset-release mode auto, 0 or 1"}
    set upstream [get_pins -quiet $hier/tx_pad_reset]
    if {[llength $upstream]!=1} {error "Missing common RAW word-reset input"}
    set upstreamNet [get_nets -of_objects $upstream]
    if {$localResetRelease} {
        if {[llength $localRelease]!=1 || [get_property REF_NAME $localRelease] ne "FDPE" ||
            [get_property INIT $localRelease] ne "1'b1" ||
            [get_property IS_INVERTED [get_pins $localRelease/C]] ni {1 1'b1} ||
            [get_nets -of_objects [get_pins $localRelease/C]] ne $clkNet ||
            [get_nets -of_objects [get_pins $localRelease/Q]] ne $rstNet ||
            [get_property TYPE [get_nets -of_objects [get_pins $localRelease/D]]] ne "GROUND" ||
            [get_property TYPE [get_nets -of_objects [get_pins $localRelease/CE]]] ne "POWER"} {
            error "Unproved falling-PAD async-preset local reset release"
        }
        set localPre [get_nets -of_objects [get_pins $localRelease/PRE]]
        if {[lsort [get_nets -segments $localPre]] ne [lsort [get_nets -segments $upstreamNet]] ||
            [lsort [get_nets -segments $rstNet]] eq [lsort [get_nets -segments $upstreamNet]]} {
            error "Local PRE must use common RAW word reset; all serializer sinks must use local Q"
        }
    } elseif {[llength $localRelease]!=0 ||
        [lsort [get_nets -segments $rstNet]] ne [lsort [get_nets -segments $upstreamNet]]} {
        error "Default mode must preserve the direct common word-reset epoch"
    }
    set actual [get_clocks -of_objects [get_pins $clock/CLK]]
    if {[llength $actual]!=1 || abs([get_property PERIOD $actual]-4.0)>0.001} {error "Pad clock is not250MHz"}
    puts "TRISPEED_QUARTER_TOPOLOGY six_common_clock_reset five_exact_D0_D4_pairs previous_clock_carry twelve_shared_reset_symbols local_reset_release=$localResetRelease"
    return $lanes
}

proc valence_trispeed_quarter_tx_constraints {hier mbps {localResetRelease auto}} {
    set lanes [valence_trispeed_quarter_audit $hier $localResetRelease]
    switch -- $mbps {
        1000 {set edges {2 4 6}; set period 8.0}
        100  {set edges {2 12 22}; set period 40.0}
        10   {set edges {2 102 202}; set period 400.0}
        default {error "Use one explicit10/100/1000 STA scenario"}
    }
    if {[llength [get_clocks -quiet phy_tx_capture]]} {error "Do not overwrite a legacy/existing capture clock"}
    set sourceName $::valence_mac_roles::last_clock/CLK
    set source [get_pins -quiet $sourceName]
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
    set padClock [get_clocks -of_objects [get_pins -quiet $sourceName]]
    foreach c $lanes {
        set oq [get_pins -of_objects [get_cells -quiet $c] -filter {REF_PIN_NAME == OQ}]
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
