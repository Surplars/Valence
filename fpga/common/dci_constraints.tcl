# DS925 CFGMCLK=50 MHz typical +/-15%; constrain fastest 57.5 MHz.
# No false paths, CDC waivers or reset exceptions are introduced.
proc common_dci_clock {} {
    set pin [get_pins -quiet dci_startup/startup/CFGMCLK]
    if {[llength $pin] != 1} {error "COMMON_DCI missing exact STARTUPE3 CFGMCLK"}
    set clocks [get_clocks -quiet -of_objects $pin]
    if {![llength $clocks]} {
        create_clock -name common_dci_cfg -period 17.391 $pin
    } elseif {[llength $clocks] != 1 || [get_property PERIOD $clocks] > 17.3911} {
        error "COMMON_DCI configuration oscillator lacks fastest-corner constraint"
    }
    set cells [get_cells -quiet -hier -filter {REF_NAME == DCIRESET}]
    if {[llength $cells] != 1 || [get_property NAME $cells] ne "dci_startup/dci"} {
        error "COMMON_DCI expected exactly one sequenced DCIRESET"
    }
}
