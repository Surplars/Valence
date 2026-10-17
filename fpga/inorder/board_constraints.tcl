# REAL board post-link constraints; never load network_ooc.xdc here.
set i1_script_dir [file dirname [file normalize [info script]]]
source [file join $i1_script_dir trispeed_board_constraints.tcl]
source [file join $i1_script_dir network_cdc.tcl]
source [file join $i1_script_dir bscan_timing_i1.tcl]
source [file join $i1_script_dir check_jtag_chain.tcl]

proc i1_board_clock {pin ns} {
    set p [get_pins -quiet $pin]
    if {[llength $p] != 1} {error "Missing real board clock pin: $pin"}
    set c [get_clocks -of_objects $p]
    if {[llength $c] != 1 || abs([get_property PERIOD $c] - $ns) > 0.002} {
        error "Real generated clock mismatch: $pin expected=$ns got=$c"
    }
    puts "I1_REAL_BOARD_CLOCK $pin [get_property NAME $c] [get_property PERIOD $c]"
    return $c
}

proc i1_board_parallel_roots {pattern extra expected mmcm_pin group} {
    set members [get_cells -quiet -hier -filter "REF_NAME == BUFGCE && NAME =~ $pattern"]
    if {[llength $members] != $expected} {error "Managed clock topology changed: $pattern $members"}
    set outputs {}
    set common {}
    foreach cell [concat $members [get_cells -quiet $extra]] {
        set input [get_nets -segments -of_objects [get_pins $cell/I]]
        set driver [get_pins -quiet -leaf -of_objects $input -filter {DIRECTION == OUT}]
        if {[llength $driver] != 1 ||
            [get_property REF_NAME [get_cells -of_objects $driver]] ne "MMCME4_ADV" ||
            [get_property REF_PIN_NAME $driver] ne $mmcm_pin} {
            error "Managed leaf is not on the real unbuffered MMCM root: $cell $driver"
        }
        if {$common eq ""} {set common $driver}
        if {$common ne $driver} {error "Managed clock roots differ: $cell"}
        lappend outputs [get_nets -of_objects [get_pins $cell/O]]
    }
    if {[llength $outputs] != $expected+1} {error "Missing parallel board clock buffer: $extra"}
    set_property CLOCK_DELAY_GROUP $group $outputs
    puts "I1_REAL_BOARD_PARALLEL_ROOT $group driver=$common leaves=[llength $outputs] NO_BUFG_CASCADE"
}

proc i1_real_board_constraints {mbps} {
    i1_board_clock u_soc/io_clockIn [expr {10.0/3.0}]
    i1_board_clock u_soc/io_alwaysOnClock 20.0
    i1_board_clock u_axi_cdc/s_axi_aclk [expr {10.0/3.0}]
    i1_board_clock u_axi_cdc/m_axi_aclk 4.0
    i1_board_clock u_rgmii/delay_clock 2.0
    i1_board_clock u_rgmii/tx_pad_clock 4.0
    i1_board_clock tx_word_clock_buffer/O 8.0
    i1_board_parallel_roots u_soc/bank/uart/* aon_clock_buffer 2 CLKOUT1 I1_BOARD_UART50
    i1_board_parallel_roots u_soc/bank/gmac/* tx_word_clock_buffer 3 CLKOUT2 I1_BOARD_MAC125
    set mmcms [get_cells -quiet -hier -filter {NAME =~ u_clk_wiz/* && REF_NAME == MMCME4_ADV}]
    if {[llength $mmcms] != 1} {error "CPU/word/pad clocks must share ONE actual MMCM"}
    foreach pair {{CLKOUT0_DIVIDE_F 5} {CLKOUT1_DIVIDE 30} {CLKOUT2_DIVIDE 12}
                  {CLKOUT3_DIVIDE 6} {CLKOUT4_DIVIDE 3}} {
        lassign $pair property expected
        if {abs([get_property $property $mmcms]-$expected)>0.001} {
            error "Actual MMCM output divider changed: $property"
        }
    }
    # Direct PHY-recovered RXC; no fixed-frequency RX MMCM at 10/100Mbps.
    valence_trispeed_rx_constraints $mbps
    i1_board_clock rx_clock_buffer/O [valence_trispeed_period $mbps]
    valence_trispeed_quarter_tx_constraints u_rgmii $mbps
    i1_network_cdc [expr {10.0/3.0}] [dict create u_soc/irq GND]
    set uart [get_cells -quiet u_soc/bank/uart/sampledRx_meta_reg]
    if {[llength $uart] != 1} {error "Missing real UART pad first synchronizer"}
    set_property ASYNC_REG TRUE $uart
    set_max_delay -datapath_only 3.333 -from [get_ports uart_rxd] -to [get_pins $uart/D]
    # Only asynchronous-assert synchronizer PRE/CLR pins. Functional reset
    # sinks and every synchronizer D/Q path remain STA-timed.
    set async_cells [get_cells -quiet -hier -filter {ASYNC_REG == TRUE && REF_NAME =~ FD*}]
    set async_controls [get_pins -quiet -of_objects $async_cells \
        -filter {REF_PIN_NAME == PRE || REF_PIN_NAME == CLR}]
    if {![llength $async_controls]} {error "Reset synchronizer endpoints missing"}
    set_false_path -to $async_controls
    puts "I1_BOARD_ASYNC_RESET_SYNC_CONTROL_ONLY [llength $async_controls] NO_FUNCTIONAL_RESET_WAIVER"
    # UART/LED/MDIO/reset are asynchronous low-speed pad protocols, not
    # fabricated synchronous interfaces. Bound their real output routing.
    foreach port [get_ports {uart_txd led eth_mdc eth_mdio eth_reset_gate}] {
        set launches [filter [all_fanin -flat -startpoints_only -to $port] \
            {CLASS == pin && (REF_PIN_NAME == C || REF_PIN_NAME == CLK)}]
        if {![llength $launches]} {error "Missing registered asynchronous output source: $port"}
        set_max_delay -datapath_only 10.0 -from $launches -to $port
        puts "I1_BOARD_ASYNC_PAD_BOUND $port launch_pins=[llength $launches] budget=10.0"
    }
    set primitive [get_cells -quiet -hier -filter {REF_NAME == BSCANE2 && JTAG_CHAIN == 2}]
    if {[llength $primitive] != 1} {error "One real USER2 BSCAN transport required"}
    set primitive [get_property NAME $primitive]
    if {![regsub {([/.])user_scan$} $primitive {\1transport} engine]} {
        error "USER2 transport sibling hierarchy changed"
    }
    set cpu [i1_board_clock u_soc/io_clockIn [expr {10.0/3.0}]]
    valence_apply_bscan_timing $primitive $engine [get_property NAME $cpu] \
        zu15eg-user2-tck50-halfcycle-i1-v2
    valence_assert_jtag_chain 2 $primitive
    set missing {}
    foreach port [get_ports] {
        if {[get_property PACKAGE_PIN $port] eq "" ||
            [get_property IOSTANDARD $port] in {"" DEFAULT}} {lappend missing $port}
    }
    if {[llength $missing]} {error "Real board I/O pin/electrical constraints missing: $missing"}
    puts "I1_REAL_BOARD_CONSTRAINTS_APPLIED CPU300 MIG_UI250 DDR2GiB PHY_RATE=$mbps NO_OOC_XDC"
}

i1_real_board_constraints 1000
