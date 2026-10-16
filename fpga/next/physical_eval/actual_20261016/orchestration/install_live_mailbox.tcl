# Source-bound external proposal; runtime checks remain mandatory. No constraints changed.
proc valence_mac::live_bank_v1 {prefix width} {
    variable root
    set relative [string range $prefix [expr {[string length $root]+1}] end]
    if {$relative ni {txConfig/mailbox/held_reg txConfig/mailbox/captured_reg rxConfig/mailbox/held_reg rxConfig/mailbox/captured_reg}} {return [bank $prefix $width]}
    if {$width != 52 || [valence_native_mac_verify_export] ne {a25f9cb85ef22c6c50df514ac2986f5e597e19e5743fd0e606d14263e759c615}} {error {Live mailbox requires exact source identity and logical width}}
    set indices {3}
    if {[string match rxConfig/* $relative]} {set indices {0 1 2}; for {set i 4} {$i<52} {incr i} {lappend indices $i}}
    set expected {}; foreach i $indices {lappend expected [format {%s[%d]} $prefix $i]}
    set found [names [cells [format {^%s(\[[0-9]+\])?$} [quote $prefix]]]]
    if {$found ne [lsort $expected]} {error "MAC exact live mailbox indices differ: $prefix actual=$found"}
    return $expected
}
proc valence_mac::live_tie_v1 {pin ref port} {
    set ds [drivers $pin]
    if {[llength $ds]!=1 || [file tail [lindex $ds 0]] ne $port} {error "MAC constant driver mismatch: $pin"}
    set c [one get_cells [file dirname [lindex $ds 0]]]
    if {[get_property REF_NAME $c] ne $ref} {error "MAC constant primitive mismatch: $pin"}
}
proc valence_mac::live_capture_v1 {path reg launch input} {
    variable root
    if {$input eq [list $launch/Q]} {return}
    set h $root/txConfig/mailbox
    if {$path ne {txConfig/mailbox} || $reg ne [format {%s/captured_reg[3]} $h] || $launch ne [format {%s/held_reg[3]} $h]} {error "MAC unreviewed capture mapping: $reg"}
    if {[valence_native_mac_verify_export] ne {a25f9cb85ef22c6c50df514ac2986f5e597e19e5743fd0e606d14263e759c615}} {error {Capture mux source identity mismatch}}
    set lut [format {%s/captured[3]_i_1} $h]
    if {$input ne [list $lut/O] || [get_property REF_NAME [one get_cells $lut]] ne {LUT5} || [string tolower [get_property INIT [one get_cells $lut]]] ne {32'hffeb0028}} {error {MAC capture mux truth table mismatch}}
    set wanted [list $launch/Q [format {%s/requestSync/stages_reg[1]/Q} $h] $h/ackToggle_reg/Q $h/valid_reg/Q $reg/Q]
    for {set i 0} {$i<5} {incr i} {if {[drivers $lut/I$i] ne [list [lindex $wanted $i]]} {error "MAC capture mux wrong input: I$i"}}
    foreach f [list $launch $reg] {
        if {[get_property REF_NAME [one get_cells $f]] ne {FDRE}} {error {MAC capture mux payload must be FDRE}}
        foreach p {C R} {if {[get_property IS_INVERTED [one get_pins $f/$p]] ni {0 FALSE false 1'b0}} {error {MAC capture mux FF polarity mismatch}}}
        live_tie_v1 $f/CE VCC P
        live_tie_v1 $f/R GND G
    }
}
set live_body [info body valence_mac::mailbox]
set live_edits [list \
    {set held [bank $h/held_reg $width]; set captured [bank $h/captured_reg $width]} \
    {set held [live_bank_v1 $h/held_reg $width]; set captured [live_bank_v1 $h/captured_reg $width]} \
    {if {$input ne [list $launch/Q]} {error "MAC held bundle has unreviewed combinational/multiple/wrong-bit source: $reg"}} \
    {live_capture_v1 $path $reg $launch $input} \
    {timed $path/payload [pins $held C] [pins $captured D] 8.0 [expr {$width>1}]} \
    {timed $path/payload [pins $held C] [pins $captured D] 8.0 [expr {[llength $held]>1}]}]
foreach {old new} $live_edits {if {[string first $old $live_body]<0 || [string first $old $live_body]!=[string last $old $live_body]} {error {Unknown/repeated mailbox collector form; refusing amendment}}}
proc valence_mac::mailbox {path width from to} [string map $live_edits $live_body]
unset live_body live_edits
