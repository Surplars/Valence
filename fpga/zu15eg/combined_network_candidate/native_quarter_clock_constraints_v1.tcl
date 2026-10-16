# Versioned BOTH-only diagnostic topology. Legacy clock audit remains unchanged.
proc valence_quarter_tx_clocks {hier} {
    if {$hier ne "network_clock"} {error "Combined network expects exact board instance"}
    set h $hier/enabled
    set pll [get_cells -quiet $h/pll]
    if {[llength $pll]!=1 || [get_property REF_NAME $pll] ne "PLLE4_ADV"} {error "Missing PAD-domain PLL"}
    foreach {property expected} {CLKFBOUT_MULT 4 DIVCLK_DIVIDE 1 CLKOUT0_DIVIDE 2 CLKOUT1_DIVIDE 4 CLKOUT0_PHASE 0 CLKOUT1_PHASE 0 CLKOUT0_DUTY_CYCLE 0.5 CLKOUT1_DUTY_CYCLE 0.5} {
        if {abs([get_property $property $pll]-$expected)>0.001} {error "Unexpected PLL property $property"}
    }
    foreach {pin period name} [list $h/pll/CLKOUT0 2 {} $h/pll/CLKOUT1 4 {} $h/raw_div/O 8 valence_tx_raw_div $h/pad_buffer/O 4 valence_tx_quarter_div] {
        set actual [get_clocks -quiet -of_objects [get_pins -quiet $pin]]
        if {[llength $actual]!=1 || abs([get_property PERIOD $actual]-$period)>0.001} {error "Combined clock period mismatch $pin"}
        if {$name ne "" && [get_property NAME $actual] ne $name} {create_generated_clock -name $name [get_pins $pin]}
        set actual [get_clocks -of_objects [get_pins $pin]]
        lassign [get_property WAVEFORM $actual] rise fall
        if {abs($rise)>0.001 || abs($fall-$period/2)>0.001} {error "Combined clock waveform mismatch $pin"}
    }
    set div [get_cells -quiet $h/raw_div]
    if {[llength $div]!=1 || [get_property REF_NAME $div] ne "BUFGCE_DIV" || [get_property BUFGCE_DIVIDE $div]!=2} {error "RAW divider must be /2"}
    if {[get_property TYPE [get_nets -of_objects [get_pins $div/CE]]] ne "POWER"} {error "RAW CE must be constant high"}
    foreach pin {I CE CLR} {
        if {[get_property IS_INVERTED [get_pins $div/$pin]] ni {0 FALSE false 1'b0}} {error "RAW divider polarity mismatch $pin"}
    }
    foreach {a b} [list $h/pll/CLKOUT1 $h/raw_div/I $h/pll/CLKOUT1 $h/pad_buffer/I $h/pll/CLKOUT0 $h/delay_buffer/I $h/pll/CLKFBOUT $h/pll/CLKFBIN] {
        valence_trispeed_same_net $a $b "combined PLL clock ownership"
    }
    valence_trispeed_same_net $h/raw_div/CLR [format {%s/phase_reset_reg[1]/Q} $h] "PAD release stage1"
    foreach {buffer source} [list $h/pad_buffer $h/pll/CLKOUT1 $h/delay_buffer $h/pll/CLKOUT0 rx_clock_buffer rx_clock_buffer/I rx_capture_clock_buffer rx_clock_buffer/I] {
        set c [get_cells -quiet $buffer]
        if {[llength $c]!=1 || [get_property REF_NAME $c] ni {BUFG BUFGCE}} {error "Missing clock buffer $buffer"}
        if {[get_property REF_NAME $c] eq "BUFGCE"} {
            if {[get_property TYPE [get_nets -of_objects [get_pins $c/CE]]] ne "POWER"} {error "Unexpected gated clock $buffer"}
            foreach pin {I CE} {
                if {[get_property IS_INVERTED [get_pins $c/$pin]] ni {0 FALSE false 1'b0}} {error "Unexpected clock polarity $buffer/$pin"}
            }
        }
        valence_trispeed_same_net $buffer/I $source "sibling input ownership"
    }
    puts "COMBINED_NETWORK_CLOCK_TOPOLOGY_REF500_PAD250_RAW125_NO_TIMING_PASS"
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
