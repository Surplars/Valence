# Adapt only the legacy clock-tree portion of the semantic role audit to the
# actual reviewed BOTH topology: PLL REF500, direct PAD250, PAD250/2 RAW125.
set body [info body ::valence_mac_roles::clocks]
set lines [split $body \n]
set start [lsearch -glob $lines {*file dirname*driver*tx_pad_clock*/I*}]
set finish [lsearch -glob $lines {*foreach *c period fall*}]
if {$start<0 || $finish<=$start} {error {Bound legacy clock profile changed; refuse patch}}
set replacement {
    # Every source/period/waveform/reset-divider invariant is independently
    # checked against actual BOTH objects, without adding timing exceptions.
    ::valence_quarter_tx_clocks network_clock
    set pad [file dirname [driver $hier/tx_pad_clock]]
    set raw [file dirname [driver $rawpin]]
    if {$pad ne {network_clock/enabled.pad_buffer} || $raw ne {network_clock/enabled.raw_div}} {error "Wrong actual BOTH PAD/RAW clock drivers"}
    if {[property get_cells $pad REF_NAME] ne {BUFGCE} || [property get_cells $raw REF_NAME] ne {BUFGCE_DIV} || [property get_cells $raw BUFGCE_DIVIDE]!=2} {error {Unproved BOTH PAD buffer/RAW divider}}
    foreach c [list $pad $raw] {
        if {[driver $c/O] ne "$c/O" || ![constant $c/CE 1]} {error "Wrong BOTH clock output/enable: $c"}
        foreach pin {I CE} {if {![bit [property get_pins $c/$pin IS_INVERTED] 0]} {error "Inverted BOTH clock buffer input $c/$pin"}}
    }
    if {![same $pad/I $raw/I] || ![same $pad/I network_clock/enabled.pll/CLKOUT1]} {error {BOTH PAD/RAW must share the actual PLL250 source}}
    if {[llength [get_clocks -quiet -of_objects [get_pins $pad/I]]]!=1 || abs([get_property PERIOD [get_clocks -of_objects [get_pins $pad/I]]]-4.0)>0.001} {error {BOTH common source must be250MHz}}
    if {![bit [property get_pins $raw/CLR IS_INVERTED] 0] || ![same $raw/CLR {network_clock/enabled.phase_reset_reg[1]/Q}]} {error {BOTH divider reset epoch mismatch}}
}
set changed [join [lrange $lines 0 [expr {$start-1}]] \n]
append changed \n $replacement \n [join [lrange $lines $finish end] \n]
proc ::valence_mac_roles::clocks {hier {require_raw_handoff 0}} $changed
set f [open mac-clock-profile-r13-procedure.tcl w];puts $f [list proc ::valence_mac_roles::clocks {hier {require_raw_handoff 0}} $changed];close $f
