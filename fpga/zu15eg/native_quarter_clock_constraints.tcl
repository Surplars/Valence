# Actual dedicated ODDR250 topology. No setup/hold multicycle, source latency
# bias or PHY budget relaxation. A shared real CLK drives all six pad cells.
proc valence_quarter_tx_clocks {hier} {
    set source [get_pins $hier/pll/CLKOUT0]
    set ref [get_clocks -of_objects $source]
    if {[llength $ref]!=1 || abs([get_property PERIOD $ref]-2)>0.001} {error "Actual TX source must be REF500"}
    set sharedInput {}
    set sharedClear {}
    foreach {tail name ratio} {raw_div valence_tx_raw_div 4 quarter_div valence_tx_quarter_div 2} {
        set c [get_cells -quiet $hier/$tail]
        if {[llength $c]!=1 || [get_property REF_NAME $c] ne "BUFGCE_DIV" || [get_property BUFGCE_DIVIDE $c]!=$ratio} {error "Missing actual TX divider $tail"}
        set input [get_nets -of_objects [get_pins $c/I]]
        set clear [get_nets -of_objects [get_pins $c/CLR]]
        if {$tail eq "raw_div"} {set sharedInput $input; set sharedClear $clear}
        if {[llength $input]!=1 || [llength $clear]!=1 || $input ne $sharedInput || $clear ne $sharedClear ||
            [get_property TYPE [get_nets -of_objects [get_pins $c/CE]]] ne "POWER"} {error "Word/quarter dividers must share source, synchronous CLR and constant CE"}
        set pin [get_pins $c/O]
        set present [get_clocks -of_objects $pin]
        if {[llength $present]!=1} {error "Expected one actual clock at $pin"}
        if {[get_property NAME $present] ne $name} {create_generated_clock -name $name $pin}
        set named [get_clocks $name]
        lassign [get_property WAVEFORM $named] rise fall
        if {abs([get_property PERIOD $named]-2*$ratio)>0.001 || abs($rise)>0.001 || abs($fall-$ratio)>0.001} {error "Unproved word/quarter clock waveform: $name"}
    }
}
proc valence_quarter_data_pin {cell index} {
    set cell [get_cells -quiet $cell]
    if {[llength $cell]!=1} {error "Missing actual DDR cell"}
    set result {}
    foreach pin [get_pins -of_objects $cell] {
        if {[get_property REF_PIN_NAME $pin] eq [format {D[%d]} $index]} {lappend result $pin}
    }
    if {[llength $result]!=1} {error "Missing actual ODDR data pin"}
    return $result
}
proc valence_quarter_tx_audit {hier} {
    set clock [get_cells -quiet $hier/tx_clock_ddr]
    set data [get_cells -quiet $hier/tx_control_ddr]
    set lanes [get_cells -quiet "$hier/lanes*.tx_ddr"]
    if {[llength $clock]!=1 || [llength $data]!=1 || [llength $lanes]!=4} {error "Require all six actual TX DDR cells"}
    set data [concat $data $lanes]
    set clkNet [get_nets -of_objects [get_pins $clock/CLK]]
    set rstNet [get_nets -of_objects [get_pins $clock/RST]]
    foreach c [concat $clock $data] {
        if {[get_property REF_NAME $c] ne "OSERDESE3" || [get_property ODDR_MODE $c] ne "TRUE" ||
            [get_property OSERDES_D_BYPASS $c] ne "FALSE" || [get_property IS_CLK_INVERTED $c] ni {0 1'b0} ||
            [get_property IS_RST_INVERTED $c] ni {{} 0 1'b0} ||
            [get_nets -of_objects [get_pins $c/CLK]] ne $clkNet || [get_nets -of_objects [get_pins $c/RST]] ne $rstNet} {error "Not one shared dedicated ODDR clock/reset: $c"}
    }
    foreach c $data {
        set left [get_nets -of_objects [valence_quarter_data_pin $c 0]]
        set right [get_nets -of_objects [valence_quarter_data_pin $c 4]]
        if {[llength $left]!=1 || $left ne $right} {error "Unused-edge exemption invalid: D0/D4 differ at $c"}
    }
    set phase [get_cells -quiet $hier/quarter_tx_boundary.phase_high_reg]
    if {[llength $phase]!=1 || [get_property REF_NAME $phase] ne "FDPE" || [get_property INIT $phase] ne "1'b1" ||
        [get_property IS_C_INVERTED $phase] ni {{} 0 1'b0} ||
        [get_nets -of_objects [get_pins $phase/C]] ne $clkNet || [get_nets -of_objects [get_pins $phase/PRE]] ne $rstNet ||
        [get_property TYPE [get_nets -of_objects [get_pins $phase/CE]]] ne "POWER"} {error "Unproved same-clock preset-high TX phase"}
    set phaseQ [get_nets -of_objects [get_pins $phase/Q]]
    set inverse [get_nets -of_objects [get_pins $phase/D]]
    if {[get_nets -of_objects [valence_quarter_data_pin $clock 0]] ne $phaseQ ||
        [get_nets -of_objects [valence_quarter_data_pin $clock 4]] ne $inverse} {error "TXC real phase/inverse wiring changed"}
    set driver [get_pins -leaf -of_objects [get_nets -segments $inverse] -filter {DIRECTION == OUT}]
    if {[llength $driver]!=1} {error "TX phase inverse must have one driver"}
    set c [get_cells -of_objects $driver]
    if {[get_property REF_NAME $c] eq "INV"} {
        set input [get_pins $c/I]
    } elseif {[get_property REF_NAME $c] eq "LUT1" && [get_property INIT $c] in {2'h1 2'b01}} {
        set input [get_pins $c/I0]
    } else {error "TX phase feedback must be exact inversion"}
    if {[get_nets -of_objects $input] ne $phaseQ} {error "TX phase feedback must invert its own Q"}
    set actual [get_clocks -of_objects [get_pins $clock/CLK]]
    if {[llength $actual]!=1 || abs([get_property PERIOD $actual]-4)>0.001} {error "Actual pad clock is not 250MHz"}
    puts "PASS_NATIVE_QUARTER_TX_TOPOLOGY SIX_COMMON_CLK250_RESET FIVE_EXACT_D0_D4_PAIRS PHASE_FEEDBACK"
    return $data
}
