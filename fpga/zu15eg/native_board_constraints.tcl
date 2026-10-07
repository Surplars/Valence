# Apply to the COMPLETE board netlist, never copy the OOC zero-I/O budgets.
source [file join [file dirname [info script]] native-gmac-cdc-constraints.tcl]
source [file join [file dirname [info script]] native_divided_clock_constraints.tcl]
source [file join [file dirname [info script]] native_quarter_clock_constraints.tcl]
proc valence_native_tx_constraints {} {
    # Use the actual forwarded DDR CLK, never unused CLKDIV.
    set forwardPin [get_pins -quiet u_rgmii/tx_clock_ddr/CLK]
    if {[llength $forwardPin]!=1} {error "Missing forwarded DDR CLK"}
    set centered [get_cells -quiet centered_tx_clock.clock_dut/mmcm]
    set pair [get_cells -quiet centered_tx_clock.clock_dut/tx_pll]
    if {[llength $pair]} {set centered $pair}
    set divided [get_cells -quiet centered_tx_clock.clock_dut/raw_div]
    set quarter [get_cells -quiet centered_tx_clock.clock_dut/quarter_div]
    if {[llength $quarter]} {
        valence_quarter_tx_clocks centered_tx_clock.clock_dut
        set lanes [valence_quarter_tx_audit u_rgmii]
        create_generated_clock -name phy_tx_capture -source $forwardPin -edges {2 4 6} [get_ports eth_txc]
        set padClock [get_clocks -of_objects $forwardPin]
        set outputs [get_ports {eth_txd[*] eth_tx_ctl}]
        foreach c $lanes {
            set oq [get_pins -of_objects $c -filter {REF_PIN_NAME == OQ}]
            # D0/D4 equality and the positive-edge-only functional oracle
            # justify ONLY falling pad-output transitions, not any D/RST/FF.
            set_false_path -fall_from $padClock -through $oq -to $outputs
        }
        set budget 1.250
    } elseif {[llength $divided]} {
        valence_divided_tx_clocks centered_tx_clock.clock_dut
        create_generated_clock -name phy_tx_capture -source $forwardPin -divide_by 1 [get_ports eth_txc]
        set budget 1.250
    } elseif {[llength $centered]==1} {
        if {[get_property CLKOUT1_PHASE $centered]!=90 || [get_property CLKOUT1_DIVIDE $centered]!=8} {error "Physical TX90 absent"}
        # UltraScale+ LATENCY mode would select the wrong DDR pad edge here.
        # Represent the real phase as waveform; hardware phase is unchanged.
        set_property PHASESHIFT_MODE WAVEFORM $centered
        create_generated_clock -name phy_tx_capture -source $forwardPin -divide_by 1 [get_ports eth_txc]
        # Software MUST read back PHY TXDLY=0, RXDLY=1 before MAC enable.
        # PHY 1ns setup/hold + original 0.25ns PCB skew, no PHY TXDLY term.
        set budget 1.250
    } else {
        # Legacy: FPGA TXC unshifted, PHY nominal TXDLY=2ns +/-0.5ns.
        create_generated_clock -name phy_tx_capture -source $forwardPin \
            -edges {1 2 3} -edge_shift {2.0 2.0 2.0} [get_ports eth_txc]
        set budget 1.750
    }
    set outputs [get_ports {eth_txd[*] eth_tx_ctl}]
    if {[llength $outputs]!=5} {error "Five TX data/control endpoints required"}
    set_output_delay -clock phy_tx_capture -max $budget $outputs
    set_output_delay -clock phy_tx_capture -min [expr {-$budget}] $outputs
    set_output_delay -clock phy_tx_capture -clock_fall -add_delay -max $budget $outputs
    set_output_delay -clock phy_tx_capture -clock_fall -add_delay -min [expr {-$budget}] $outputs
}
proc valence_native_board_constraints {} {
    valence_native_tx_constraints
    set bank u_soc/nativeBank
    # Physical clock resources belong next to the fixed Bank66 RGMII pads.
    # Derive the legal region/site from the package, never from a guessed LOC.
    set region [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AA7]]]
    set txRegion [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AC8]]]
    if {[llength $region] != 1 || $txRegion ne $region} {error "RGMII pads are not in a common clock region"}
    set mmcms [get_sites -of_objects $region -filter {NAME =~ MMCM*}]
    set centered [get_cells -quiet centered_tx_clock.clock_dut/mmcm]
    set pair [get_cells -quiet centered_tx_clock.clock_dut/tx_pll]
    if {[llength $pair]} {set centered $pair}
    set divided [get_cells -quiet centered_tx_clock.clock_dut/raw_div]
    set quarter [get_cells -quiet centered_tx_clock.clock_dut/quarter_div]
    if {[llength $divided]} {set centered [get_cells centered_tx_clock.clock_dut/pll]}
    if {[llength $centered] == 1} {
        set rxMmcm [get_cells -quiet centered_rx_clock.clock_dut/mmcm]
        if {[llength $mmcms]!=1 || [llength $rxMmcm]!=1} {error "Missing local RX MMCM"}
        set_property LOC $mmcms $rxMmcm
        if {[llength $divided]} {
            set ethRegion $region
            set pllSites [lsort -dictionary [get_sites -of_objects $region -filter {NAME =~ PLL_X*}]]
            set divSites [lsort -dictionary [get_sites -of_objects $region -filter {SITE_TYPE == BUFGCE_DIV}]]
            set requiredDivs [expr {[llength $quarter] ? 2 : 3}]
            if {[llength $pllSites]!=2 || [llength $divSites]<$requiredDivs} {error "Missing local REF PLL/DIV resources"}
            set_property LOC [lindex $pllSites 0] $centered
            # Let the complete-board placer choose legal DIV sites inside the
            # pad region. Fixed ordinal sites were marginal at BOTH TX edges;
            # drive-strength-only review could not close all lanes. Region,
            # common clock root and the pad/forward delay group below stay
            # constrained. Phase, CLR sequencing and PHY budgets are unchanged.
            set divNames {raw_div forward_div pad_div}
            if {[llength $quarter]} {set divNames {raw_div quarter_div}}
            foreach c $divNames {
                reset_property LOC [get_cells centered_tx_clock.clock_dut/$c]
            }
        } elseif {[llength $pair]} {
            # Integer TX clocks share a pad-local PLL. The second local PLL
            # provides calibration only, with combined lock in board RTL.
            set ethRegion $region
            set pllSites [lsort -dictionary [get_sites -of_objects $region -filter {NAME =~ PLL_X*}]]
            set delayPll [get_cells -quiet centered_tx_clock.clock_dut/delay_pll]
            if {[llength $pllSites]!=2 || [llength $delayPll]!=1} {error "Missing local calibration PLL"}
            foreach c [list $pair $delayPll] s $pllSites {set_property LOC $s $c}
        } else {
            # Older explicit-MMCM phase candidate remains reproducible.
            if {![regexp {^(X[0-9]+)Y([0-9]+)$} $region -> column row]} {error "Unknown I/O region"}
            set ethRegion [get_clock_regions -quiet ${column}Y[expr {$row+1}]]
            set ethSites [get_sites -of_objects $ethRegion -filter {NAME =~ MMCM*}]
            if {[llength $ethRegion]!=1 || [llength $ethSites]!=1} {error "Missing adjacent Ethernet CMT"}
            set_property LOC $ethSites $centered
        }
        # UI BUFG and ETH MMCM are in the same column but non-adjacent rows.
        # SAME_CMT_COLUMN retains GLOBAL CLOCK resources; never use FALSE.
        set uiBuffer [get_pins u_ddr/inst/u_ddr4_infrastructure/u_bufg_divClk/O]
        if {[llength $uiBuffer]!=1} {error "Missing real MIG UI BUFG"}
        set_property CLOCK_DEDICATED_ROUTE SAME_CMT_COLUMN [get_nets -of_objects $uiBuffer]
        set_property PHASESHIFT_MODE WAVEFORM $centered
        if {[llength $divided]} {
            set paths {centered_rx_clock.rx_clock_buffer centered_tx_clock.clock_dut/raw_div centered_tx_clock.clock_dut/pad_div centered_tx_clock.clock_dut/forward_div centered_tx_clock.clock_dut/delay_buffer centered_rx_clock.clock_dut/feedback_buffer}
            if {[llength $quarter]} {
                set paths {centered_rx_clock.rx_clock_buffer centered_tx_clock.clock_dut/raw_div centered_tx_clock.clock_dut/quarter_div centered_tx_clock.clock_dut/delay_buffer centered_rx_clock.clock_dut/feedback_buffer}
            }
            set stages [get_cells -quiet {centered_tx_clock.clock_dut/phase_reset_reg[*]}]
            if {[llength $stages]!=3} {error "Missing own-clock phase release chain"}
            set_false_path -to [get_pins -of_objects $stages -filter {REF_PIN_NAME == PRE}]
            # DIV CLR releases are synchronous full-cycle paths: NOT false paths.
        } else {
            set paths {centered_rx_clock.rx_clock_buffer centered_tx_clock.tx_buffer centered_tx_clock.forward_buffer centered_tx_clock.delay_buffer centered_rx_clock.clock_dut/feedback_buffer}
        }
    } else {
        set ethMmcm [get_cells -quiet u_eth_clk_wiz/inst/mmcme4_adv_inst]
        if {[llength $mmcms] != 1 || [llength $ethMmcm] != 1} {error "Missing local Ethernet MMCM"}
        set_property LOC $mmcms $ethMmcm
        set paths {rx_clock_buffer u_eth_clk_wiz/inst/clkout1_buf u_eth_clk_wiz/inst/clkout2_buf}
    }
    foreach path $paths {
        set cell [get_cells -quiet $path]
        if {[llength $cell] != 1} {error "Missing local Ethernet clock buffer: $path"}
        set bufferRegion $region
        if {[llength $centered] && [string match centered_tx_clock.* $path]} {set bufferRegion $ethRegion}
        set_property CLOCK_REGION $bufferRegion $cell
        # BUFG location alone does not choose a local clock-tree root. Pin
        # the immediate output segment to the I/O region as well. Routed
        # ECOs must unroute these nets and run update_clock_routing.
        set output [get_nets -of_objects [get_pins $path/O]]
        if {[llength $output] != 1} {error "Missing immediate clock output: $path"}
        set_property USER_CLOCK_ROOT $region $output
    }
    if {[llength $centered]} {
        set txPaths {centered_tx_clock.tx_buffer centered_tx_clock.forward_buffer}
        if {[llength $divided]} {set txPaths {centered_tx_clock.clock_dut/pad_div centered_tx_clock.clock_dut/forward_div}}
        if {[llength $quarter]} {set txPaths {centered_tx_clock.clock_dut/quarter_div}}
        foreach path $txPaths {
            set_property CLOCK_DELAY_GROUP VALENCE_TX_PHASE_PAIR [get_nets -of_objects [get_pins $path/O]]
        }
        # Keep the qualified serial TX CMU gate. RX raw and managed trees
        # instead share the same RX MMCM output (not the unshifted pad).
        set rxBuffer [get_cells centered_rx_clock.rx_clock_buffer]
        set rxGate [get_cells $bank/gmac/rxManaged_gate/buffer]
        set rxInput [get_nets -of_objects [get_pins $rxBuffer/I]]
        set gateInput [get_nets -of_objects [get_pins $rxGate/I]]
        set driver [get_pins -leaf -of_objects [get_nets -segments $gateInput] -filter {DIRECTION == OUT}]
        if {$driver eq "centered_rx_clock.rx_clock_buffer/O"} {
            disconnect_net -net $gateInput -objects [get_pins $rxGate/I]
            connect_net -hier -net $rxInput -objects [get_pins $rxGate/I]
        } elseif {$driver ne "centered_rx_clock.clock_dut/mmcm/CLKOUT0"} {error "Unexpected RX managed source: $driver"}
        foreach path [list centered_rx_clock.rx_clock_buffer $bank/gmac/rxManaged_gate/buffer centered_rx_clock.clock_dut/feedback_buffer] {
            set_property CLOCK_DELAY_GROUP VALENCE_MAC_RX [get_nets -of_objects [get_pins $path/O]]
        }
        set_property CLOCK_REGION $region $rxGate
        set_property CLOCK_DELAY_GROUP VALENCE_MAC_TX_SERIAL [get_nets -of_objects [get_pins $bank/gmac/txManaged_gate/buffer/O]]
    }
    # Cascaded CMU clocks must match the raw clock root; otherwise a local
    # raw clock ECO can introduce skew into the raw/managed synchronous cut.
    foreach path {gmac/txManaged_gate/buffer gmac/rxManaged_gate/buffer} {
        set buffer [get_cells -quiet $bank/$path]
        if {[llength $buffer] != 1} {error "Missing native managed clock buffer: $path"}
        set output [get_nets -of_objects [get_pins $bank/$path/O]]
        if {[llength $output] != 1} {error "Missing native managed clock output: $path"}
        set_property USER_CLOCK_ROOT $region $output
    }
    foreach hier {cmu/bridge uart/bridge} {valence_register_cdc_constraints $bank/$hier 8.0}
    foreach hier {gmac/txConfig/mailbox gmac/rxConfig/mailbox gmac/txStats/mailbox gmac/rxStats/mailbox} {
        valence_mailbox_cdc_constraints $bank/$hier 8.0
    }
    foreach hier {gmac/txFifo/fifo gmac/rxFifo/fifo} {
        set path $bank/$hier
        valence_stream_cdc_constraints $path 8.0
        set ends [get_pins -of_objects [get_cells -quiet "$path/output_0_reg*"] -filter {REF_PIN_NAME == D}]
        set starts [filter [all_fanin -flat -startpoints_only -to $ends] {REF_PIN_NAME == CLK}]
        if {[llength $starts] == 0 || [llength $ends] != 38} {error "FIFO payload mapping changed: $path"}
        set_max_delay -datapath_only 8.0 -from $starts -to $ends
        set_bus_skew 8.0 -from $starts -to $ends
    }
    foreach cell [get_cells -hier -filter "REF_NAME =~ CdcLevel* && NAME =~ $bank/*"] {
        valence_level_cdc_constraint [get_property NAME $cell] 8.0
    }
    set uart_meta [get_pins -of_objects [get_cells -quiet $bank/uart/sampledRx_meta_reg] -filter {REF_PIN_NAME == D}]
    set mdio_meta [get_pins -quiet mdio_meta_reg/D]
    if {[llength $uart_meta] != 1 || [llength $mdio_meta] != 1} {error "Missing asynchronous pad synchronizer"}
    set_max_delay -datapath_only 20.0 -from [get_ports uart_rxd] -to $uart_meta
    set_max_delay -datapath_only 10.0 -from [get_ports eth_mdio] -to $mdio_meta
    # Only async preset/clear on explicit reset-release chains. Functional
    # downstream reset nets, synchronizer D->Q, CPU and peripheral data stay timed.
    set resetCells [get_cells -quiet -hier -filter {NAME =~ *reset_pipe_reg*}]
    foreach release [get_cells -quiet -hier -filter {REF_NAME =~ CdcResetRelease*}] {
        set stages [get_cells -quiet "$release/release_0_reg*"]
        if {[llength $stages] != 3} {error "Reset release has non-three-stage topology: $release"}
        foreach stage $stages {
            if {![get_property ASYNC_REG $stage]} {error "Missing reset ASYNC_REG: $stage"}
            lappend resetCells $stage
        }
        set sharedPreset {}
        for {set n 0} {$n < 3} {incr n} {
            set stage [format {%s/release_0_reg[%d]} $release $n]
            set preset [get_nets -of_objects [get_pins $stage/PRE]]
            if {$n == 0} {set sharedPreset $preset}
            if {$preset ne $sharedPreset} {error "Reset assertion is not common: $release"}
            set drivers [get_pins -leaf -of_objects [get_nets -segments -of_objects [get_pins $stage/D]] -filter {DIRECTION == OUT}]
            if {$n == 0} {
                if {[get_property TYPE [get_nets -of_objects [get_pins $stage/D]]] ne "GROUND"} {error "Reset stage0 not grounded"}
            } elseif {$drivers ne [format {%s/release_0_reg[%d]/Q} $release [expr {$n-1}]]} {
                error "Reset release is not a direct shift: $release"
            }
        }
    }
    set resetPins [get_pins -quiet -of_objects $resetCells -filter {REF_PIN_NAME == PRE || REF_PIN_NAME == CLR}]
    if {[llength $resetPins] == 0} {error "Reset release boundary missing"}
    set_false_path -to $resetPins
    # Serial TX is asynchronous at the connector; budget one raw UART cycle,
    # not a CPU-cycle UART data timing claim. Receiver sampling is oversampled.
    set uartClock [get_clocks -of_objects [get_pins $bank/uart/uart/clock]]
    set cpuClock [get_clocks -of_objects [get_pins u_soc/clock]]
    set aonClock [get_clocks -of_objects [get_pins u_clk_wiz/clk_out2]]
    if {[llength $uartClock] != 1 || [llength $cpuClock] != 1 || [llength $aonClock] != 1} {error "Real board clocks missing"}
    set_output_delay -clock $uartClock -max 10.0 [get_ports uart_txd]
    set_output_delay -clock $uartClock -min 0.0 [get_ports uart_txd]
    # These ports do NOT have external 100/50MHz synchronous capture flops.
    # Clause22 MDC is <=2.5MHz (200ns half-cycle); MDIO changes on falling
    # edges. Bound EACH physical leg to 20ns, leaving >=160ns even with worst
    # differential insertion for the PHY's 10ns setup/hold. Packet/oracle
    # verification enforces edge/TA stability; this is not a CPU I/O period.
    # LED is asynchronous indication; reset_gate holds assertion for 10ms.
    foreach port {eth_mdc eth_mdio led eth_reset_gate} {
        set endpoint [get_ports $port]
        set starts [filter [all_fanin -flat -startpoints_only -to $endpoint] {REF_PIN_NAME == C || REF_PIN_NAME == CLK}]
        if {[llength $starts] == 0} {error "Missing registered management output: $port"}
        set_max_delay -datapath_only 20.0 -from $starts -to $endpoint
    }
    # Reset/button are truly asynchronous external assertion inputs, never
    # synchronous CPU data. Their scope is explicitly limited to reset controls.
    set_false_path -from [get_ports {sys_rst_n button_n}] -to $resetPins
    foreach {pin expected} {eth_mdc Y1 eth_reset_gate Y2 eth_mdio Y12} {
        if {[get_property PACKAGE_PIN [get_ports $pin]] ne $expected} {error "PHY pin mismatch: $pin"}
    }
}
