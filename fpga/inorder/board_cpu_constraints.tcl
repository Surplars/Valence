# Batch26 no-MAC REAL board. Keep CPU300/UI250/AON50/UART50, no OOC clocks.
set here [file dirname [file normalize [info script]]]
source [file join $here board_clock_helpers.tcl]
source [file join $here native-gmac-cdc-constraints.tcl]
source [file join $here bscan_timing_i1.tcl]
source [file join $here check_jtag_chain.tcl]
i1_board_clock u_soc/io_clockIn [expr {10.0/3.0}]
i1_board_clock u_soc/io_alwaysOnClock 20.0
i1_board_clock u_soc/io_uartClockIn 20.0
i1_board_clock u_axi_cdc/s_axi_aclk [expr {10.0/3.0}]
i1_board_clock u_axi_cdc/m_axi_aclk 4.0
i1_board_parallel_roots u_soc/bank/uart/* aon_clock_buffer 2 CLKOUT1 I1_BOARD_UART50
set mac [get_cells -quiet -hier -filter {
    REF_NAME =~ *Gmac* || REF_NAME =~ EthernetPacketDma* || NAME =~ *u_rgmii*}]
if {[llength $mac]} {error "MAC/DMA/physical RGMII must be absent: $mac"}
set mmcms [get_cells -quiet -hier -filter {NAME =~ u_clk_wiz/* && REF_NAME == MMCME4_ADV}]
if {[llength $mmcms]!=1} {error "Real clock MMCM missing"}
foreach pair {{CLKOUT0_DIVIDE_F 5} {CLKOUT1_DIVIDE 30}
              {CLKOUT2_DIVIDE 12} {CLKOUT3_DIVIDE 6} {CLKOUT4_DIVIDE 3}} {
    lassign $pair property expected
    if {abs([get_property $property $mmcms]-$expected)>0.001} {
        error "Existing MMCM divider changed: $property"
    }
}
set bridges [get_cells -hier -filter {REF_NAME =~ RegisterClockDomainBridge*}]
if {[llength $bridges]!=2} {error "Require independent UART and CMU CDC bridges"}
foreach bridge $bridges {valence_register_cdc_constraints [get_property NAME $bridge] 3.333}
set levels 0
set constants 0
foreach cell [get_cells -hier -filter {REF_NAME =~ CdcLevel*}] {
    set name [get_property NAME $cell]
    set captures [get_cells -quiet "$name/stages_reg?0?"]
    if {[llength $captures]!=1} {error "CDC first stage missing: $name"}
    set ends [get_pins -of_objects $captures -filter {REF_PIN_NAME == D}]
    set drivers [get_pins -quiet -leaf -of_objects [get_nets -segments -of_objects $ends] \
        -filter {DIRECTION == OUT}]
    set isGround 0
    if {[llength $drivers]==1} {
        set owner [get_cells -of_objects $drivers]
        if {[get_property REF_NAME $owner] eq "GND"} {set isGround 1}
    }
    if {$name eq "u_soc/irq" && $isGround} {
        incr constants
        puts "I1_CPU_CDC_CONSTANT exact=$name direct=GND no_exception"
    } else {
        if {$isGround} {error "Unexpected constant CDC endpoint: $name"}
        valence_level_cdc_constraint $name 3.333
        incr levels
    }
}
if {$levels<2 || $constants!=1} {error "Missing no-MAC CMU/UART CDC composition"}
set uart [get_cells -quiet u_soc/bank/uart/sampledRx_meta_reg]
if {[llength $uart]!=1} {error "Actual UART pad synchronizer missing"}
set_property ASYNC_REG TRUE $uart
set_max_delay -datapath_only 3.333 -from [get_ports uart_rxd] -to [get_pins $uart/D]
set async_cells [get_cells -quiet -hier -filter {ASYNC_REG == TRUE && REF_NAME =~ FD*}]
set async_controls [get_pins -quiet -of_objects $async_cells \
    -filter {REF_PIN_NAME == PRE || REF_PIN_NAME == CLR}]
if {![llength $async_controls]} {error "Actual asynchronous reset synchronizers missing"}
set_false_path -to $async_controls
foreach port [get_ports {uart_txd led}] {
    set launches [filter [all_fanin -flat -startpoints_only -to $port] \
        {CLASS == pin && (REF_PIN_NAME == C || REF_PIN_NAME == CLK)}]
    if {![llength $launches]} {error "Missing actual low-speed output launch: $port"}
    set_max_delay -datapath_only 10.0 -from $launches -to $port
}
set primitive [get_cells -quiet -hier -filter {REF_NAME == BSCANE2 && JTAG_CHAIN == 2}]
if {[llength $primitive]!=1} {error "One real USER2 BSCAN required"}
set primitive [get_property NAME $primitive]
if {![regsub {([/.])user_scan$} $primitive {\1transport} engine]} {
    error "USER2 transport sibling changed"
}
set cpu [i1_board_clock u_soc/io_clockIn [expr {10.0/3.0}]]
# Strengthen only CPU->CPU HOLD by 50ps. No setup relaxation, false path,
# clock-frequency change, or blanket CDC exemption. Final slack includes it.
set_clock_uncertainty -from $cpu -to $cpu -hold 0.050
puts "I1_CPU_INTRACLOCK_HOLD_GUARD_NS=0.050"
valence_apply_bscan_timing $primitive $engine [get_property NAME $cpu] \
    zu15eg-user2-tck50-halfcycle-i1-v2
valence_assert_jtag_chain 2 $primitive
foreach port [get_ports] {
    if {[get_property PACKAGE_PIN $port] eq "" ||
        [get_property IOSTANDARD $port] in {"" DEFAULT}} {
        error "Unassigned real package/electrical pin: $port"
    }
}
puts "I1_CPU_BOARD_CONSTRAINTS CPU300 UI250 AON50 UART50 bridges=2 levels=$levels PHY_RESET_HELD MAC_ABSENT NO_OOC_XDC"
