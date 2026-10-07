# CLR sequencing establishes real 0/0/+2ns DIV4 phases. Retain the clock
# buffer's rise/fall traversal when defining its 8ns waveform; {1 5 9}
# incorrectly disconnects the falling master traversal in this Vivado model.
proc valence_divided_tx_cells {pll raw pad forward} {
    set source [get_pins $pll/CLKOUT0]
    set ref [get_clocks -of_objects $source]
    if {[llength $ref]!=1 || abs([get_property PERIOD $ref]-2)>0.001} {error "Actual common source must be 500MHz"}
    foreach {path name offset} [list $raw valence_tx_raw_div 0 $pad valence_tx_pad_div 0 $forward valence_tx_forward_div 2] {
        set c [get_cells -quiet $path]
        if {[llength $c]!=1 || [get_property REF_NAME $c] ne "BUFGCE_DIV" || [get_property BUFGCE_DIVIDE $c]!=4} {error "Missing real DIV4 $path"}
        set pin [get_pins $c/O]
        set present [get_clocks -of_objects $pin]
        if {[llength $present]!=1} {error "Expected one real divider clock: $path"}
        # Rename the automatic clock before assigning the proved phase. This
        # retains references from IP/user constraints instead of overriding a
        # differently named clock and silently dropping its dependent budgets.
        if {[get_property NAME $present] ne $name} {
            create_generated_clock -name $name $pin
        }
        set named [get_clocks $name]
        if {$offset!=0 && [get_property WAVEFORM $named] ne {2.000 6.000}} {
            # Normal divide4 waveform {0 4}, with the proved +2ns start epoch.
            create_generated_clock -name $name -source $source -edges {1 2 3} -edge_shift {2 5 8} $pin
        }
        set named [get_clocks $name]
        lassign [get_property WAVEFORM $named] rise fall
        if {abs([get_property PERIOD $named]-8)>0.001 || abs($rise-$offset)>0.001 || abs($fall-$offset-4)>0.001} {error "Wrong real divider waveform: $name"}
    }
}
proc valence_divided_tx_clocks {hier} {
    valence_divided_tx_cells $hier/pll $hier/raw_div $hier/pad_div $hier/forward_div
}
