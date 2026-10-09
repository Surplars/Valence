# Opt-in, scoped tri-speed integration recipe. NOT a routed/CDC signoff result.
# This must never be combined with native_board_constraints.tcl (legacy RX MMCM)
# or the fixed-rate timing section in native_gmac_pins.xdc. Preserve package pins.
source [file join [file dirname [info script]] trispeed_quarter_constraints.tcl]
source [file join [file dirname [info script]] native-gmac-cdc-constraints.tcl]

proc valence_trispeed_period {mbps} {
    switch -- $mbps {
        1000 {return 8.0}
        100 {return 40.0}
        10 {return 400.0}
        default {error "Use one explicit 10/100/1000 tri-speed scenario"}
    }
}

proc valence_trispeed_rx_constraints {mbps} {
    set period [valence_trispeed_period $mbps]
    if {[llength [get_clocks -quiet {phy_rx phy_rx_launch phy_tx_capture}]]} {
        error "Fresh tri-speed scenario required; refusing existing/legacy media clocks"
    }
    set rx [get_ports -quiet eth_rxc]
    set data [get_ports -quiet {eth_rxd[*] eth_rx_ctl}]
    if {[llength $rx]!=1 || [llength $data]!=5} {error "Missing real recovered-clock/RX pad endpoints"}
    create_clock -name phy_rx -period $period -waveform [list 0 [expr {$period/2}]] $rx
    set_clock_uncertainty 0.100 [get_clocks phy_rx]
    # Retain the original fixed RXDLY/PCB assumption, not 90 degrees at 25/2.5MHz.
    # Applying BOTH edges at every rate is conservative for repeated low-rate data.
    # The +/-0.25ns PCB component remains an assumption until measured on board.
    create_clock -name phy_rx_launch -period $period -waveform [list 2 [expr {$period/2+2}]]
    foreach fall {0 1} {
        set extra {}
        if {$fall} {set extra {-clock_fall -add_delay}}
        set_input_delay -clock phy_rx_launch {*}$extra -max 1.050 $data
        set_input_delay -clock phy_rx_launch {*}$extra -min -1.050 $data
    }
}

proc valence_trispeed_same_net {left right label} {
    set a [get_pins -quiet $left]
    set b [get_pins -quiet $right]
    if {[llength $a]!=1 || [llength $b]!=1} {error "Missing tri-speed topology pin: $label"}
    set leftNets [get_nets -segments -of_objects $a]
    set rightNets [get_nets -segments -of_objects $b]
    foreach net $leftNets {if {[lsearch -exact $rightNets $net]>=0} {return}}
    error "Tri-speed topology mismatch: $label"
}

proc valence_trispeed_clock_reset_audit {bank mbps} {
    set period [valence_trispeed_period $mbps]
    valence_quarter_tx_clocks network_clock
    foreach {pin expected} [list u_soc/clock 10.0 network_clock/raw_div/O 8.0 \
        network_clock/quarter_div/O 4.0 u_rgmii/delay_clock 2.0 rx_clock_buffer/O $period] {
        set clock [get_clocks -of_objects [get_pins -quiet $pin]]
        if {[llength $clock]!=1 || abs([get_property PERIOD $clock]-$expected)>0.001} {
            error "Tri-speed actual clock period mismatch: $pin"
        }
    }
    if {[llength [get_cells -quiet centered_rx_clock.clock_dut/mmcm]]} {
        error "Tri-speed RX must not use the fixed-frequency legacy RX MMCM"
    }
    set rxBuffer [get_cells -quiet rx_clock_buffer]
    if {[llength $rxBuffer]!=1 || [get_property REF_NAME $rxBuffer] ne "BUFG"} {
        error "Missing direct recovered-clock BUFG"
    }
    set roots [all_fanin -flat -startpoints_only -to [get_pins rx_clock_buffer/I]]
    if {[llength $roots]!=1 || $roots ne [get_ports eth_rxc]} {
        error "Recovered RX clock is not driven directly from the physical RXC pad"
    }
    foreach gate {txManaged_gate rxManaged_gate} {
        valence_trispeed_same_net network_clock/raw_div/O $bank/$gate/buffer/I "fixed125 source $gate"
    }
    valence_trispeed_same_net rx_clock_buffer/O $bank/decode/clock "recovered RX decoder"
    valence_trispeed_same_net network_clock/raw_div/O $bank/physicalIngress/destinationClock "fixed125 ingress drain"
    valence_trispeed_same_net $bank/rxManaged_gate/buffer/O $bank/rx/clock "fixed125 complete RX banks"
    # A hot speed/ingress epoch reset must never reach a complete packet owner.
    foreach pin {txFifo/commonReset rxFifo/commonReset txRelease/asyncReset rxRelease/asyncReset} {
        valence_trispeed_same_net $bank/commonReset $bank/$pin "cold-only retained owner $pin"
    }
    valence_trispeed_same_net $bank/physicalIngress/commonReset \
        $bank/physicalIngress/crossing/commonReset "both physical FIFO epoch endpoints"
    puts "TRISPEED_CLOCK_RESET_TOPOLOGY fixed125_packet_owners direct_RXC separate_physical_epoch"
}

proc valence_trispeed_packet_cdc_constraints {bank} {
    # Always use the fastest supported 8ns period, including the slow-rate STA
    # scenarios. Byte enables are not a reason to relax any crossing or timing.
    foreach path {txRate rxRate txConfig/mailbox rxConfig/mailbox txStats/mailbox rxStats/mailbox \
        rxDiagnostics/mailbox rawDiagnostics/mailbox rxStop/command} {
        valence_mailbox_cdc_constraints $bank/$path 8.0
    }
    foreach path {txFifo/fifo rxFifo/fifo physicalIngress/crossing/fifo} {
        valence_stream_cdc_constraints $bank/$path 8.0
        valence_fifo_payload_constraints $bank/$path 8.0
    }
    # Level controls, management and reset-release topology also require actual
    # netlist review. This packet recipe does not pretend to replace that gate.
    puts "TRISPEED_PACKET_CDC_BOUNDED nine_mailboxes three_gray_buses_and_payloads budget_ns=8"
}

proc valence_trispeed_board_constraints {mbps} {
    set bank u_soc/nativeBank/gmac
    valence_trispeed_rx_constraints $mbps
    valence_trispeed_clock_reset_audit $bank $mbps
    valence_trispeed_quarter_tx_constraints u_rgmii $mbps
    valence_trispeed_packet_cdc_constraints $bank
    puts "TRISPEED_SCOPED_RECIPE_APPLIED rate=$mbps COMPLETE_BOARD_CDC_RDC_STA_STILL_REQUIRED"
}
