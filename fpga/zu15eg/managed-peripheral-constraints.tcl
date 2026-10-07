# Fail-closed, scoped CDC bounds. NO clock groups or broad false paths.
source [file join [file dirname [info script]] native-gmac-cdc-constraints.tcl]
proc valence_managed_peripheral_constraints {} {
    foreach hier {cmu/bridge uart/bridge} { valence_register_cdc_constraints $hier 8.0 }
    foreach hier {gmac/txConfig/mailbox gmac/rxConfig/mailbox gmac/txStats/mailbox gmac/rxStats/mailbox
                  gmac/rxStop/command} {
        valence_mailbox_cdc_constraints $hier 8.0
    }
    foreach hier {gmac/txFifo/fifo gmac/rxFifo/fifo} {
        valence_stream_cdc_constraints $hier 8.0
        set ends [get_pins -of_objects [get_cells -quiet "$hier/output_0_reg*"] -filter {REF_PIN_NAME == D}]
        # Trace expanded RAM leaf clocks, never composite RAM32M16 WCLK
        # (an invalid segmented startpoint before checkpoint expansion).
        set starts [filter [all_fanin -flat -startpoints_only -to $ends] {REF_PIN_NAME == CLK}]
        set width 38
        if {[llength $starts] == 0 || [llength $ends] != $width} { error "FIFO payload changed $hier" }
        set_max_delay -datapath_only 8.0 -from $starts -to $ends
        set_bus_skew 8.0 -from $starts -to $ends
        if {[llength [get_timing_paths -quiet -from $starts -to $ends -max_paths 100 -nworst 1]] != $width} {
            error "FIFO payload incomplete coverage $hier"
        }
        puts "MANAGED_RAM_BOUND $hier captures=$width budget=8.0"
    }
    foreach cell [get_cells -hier -filter {REF_NAME =~ CdcLevel*}] {
        set hier [get_property NAME $cell]
        set ends [get_pins -of_objects [get_cells -quiet "$hier/stages_reg?0?"] -filter {REF_PIN_NAME == D}]
        set drivers [all_fanin -flat -startpoints_only -to $ends]
        set starts [get_pins -of_objects [get_cells -quiet -of_objects $drivers] -filter {REF_PIN_NAME == C}]
        if {[llength $starts] == 1} {
            valence_level_cdc_constraint $hier 8.0
        } elseif {$hier eq "gmac/csr_io_ports_0_linkUp_sync" && "$drivers" eq "linkUp"} {
            # Actual asynchronous PHY link indication, not synchronous data.
            set_max_delay -datapath_only 8.0 -from [get_ports linkUp] -to $ends
            puts "MANAGED_EXTERNAL_LEVEL $hier linkUp"
        } else { error "Unclassified/nonregistered level source $hier drivers=$drivers" }
    }
    set padEnds [get_pins -of_objects [get_cells -quiet uart/sampledRx_meta_reg] -filter {REF_PIN_NAME == D}]
    if {[llength $padEnds] != 1} { error "UART raw pad capture changed" }
    set_max_delay -datapath_only 20.0 -from [get_ports uartRx] -to $padEnds
    # Reproducible ZERO delay OOC boundary budgets, NOT board I/O signoff.
    foreach port [get_ports -filter {DIRECTION == IN}] {
        set name [get_property NAME $port]
        if {$name in {sourceClock alwaysOnClock rawUartClock rawTxClock rawRxClock commonReset uartRx linkUp}} { continue }
        if {[string match "gmiiRx*" $name]} { set clk rx_raw } else { set clk cpu }
        set_input_delay 0.0 -clock [get_clocks $clk] $port
    }
    foreach port [get_ports -filter {DIRECTION == OUT}] {
        set name [get_property NAME $port]
        if {$name in {uartClock txClock rxClock}} { continue }
        if {$name eq "uartTx"} { set clk uart_raw } elseif {[string match "gmiiTx*" $name]} { set clk tx_raw } elseif {$name in {enabled quiesce isolate}} {
            set clk aon
        } else { set clk cpu }
        set_output_delay 0.0 -clock [get_clocks $clk] $port
    }
}
