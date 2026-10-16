# Rename a tool-derived clock only at its actual SOURCE_PINS. The PAD clock
# originates at PLL/CLKOUT1 and merely propagates through the BUFGCE output.
set body [info body valence_quarter_tx_clocks]
set needle {create_generated_clock -name $name [get_pins $pin]}
if {[string first $needle $body]<0} {error {Expected bound clock rename expression changed}}
set replacement {
    if {[get_property IS_GENERATED $actual] ni {1 TRUE true} || [get_property IS_USER_GENERATED $actual] ni {0 FALSE false}} {error "Clock rename requires actual tool-derived clock: $pin"}
    set origin [get_pins -quiet [get_property SOURCE_PINS $actual]]
    if {[llength $origin]!=1} {error "Clock lacks unique actual derivation source: $pin"}
    create_generated_clock -name $name $origin
}
set body [string map [list $needle $replacement] $body]
proc valence_quarter_tx_clocks {hier} $body
set f [open network-clock-rename-r11-procedure.tcl w];puts $f [list proc valence_quarter_tx_clocks {hier} $body];close $f
diag_event network_clock rename_origin_adapted {ACTUAL_TOOL_DERIVED_SOURCE_PINS_NO_NEW_INDEPENDENT_CLOCK}
