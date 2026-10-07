# Read-only CURRENT routed-netlist truth check of the CDC-1 txConfig bit3.
# Complements, not replaces, held-data timing/skew and independent CDC tests.
# No exception changes, net edits, waiver command, synthesis or bit generation.
if {$argc != 2} {error "Expected ROUTED_DCP FRESH_OUTPUT_DIRECTORY"}
lassign $argv checkpoint output
set checkpoint [file normalize $checkpoint]
set output [file normalize $output]
if {![file exists $checkpoint] || [file exists $output]} {error "Missing checkpoint or non-fresh output"}
file mkdir $output
source [file join [file dirname [info script]] native_mailbox_truth.tcl]
set_param general.maxThreads 8
open_checkpoint $checkpoint
if {[get_property PART [current_design]] ne "xczu15eg-ffvb1156-2-i"} {error "Wrong board part"}
if {[llength [get_cells -quiet -hier -filter {REF_NAME == FloatingPointSystem}]] != 1} {error "Expected actual RV64GC FPU"}
set native_mbox_cone {}
proc native_mbox_one_pin {name} {
    set pin [get_pins -quiet $name]
    if {[llength $pin] != 1 || [get_property NAME $pin] ne $name} {error "Missing exact mailbox pin $name"}
    return $name
}
proc native_mbox_resolve {pin} {
    global native_mbox_cone
    set pin [native_mbox_one_pin $pin]
    set pinObjects [get_pins -quiet $pin]
    set direction [get_property DIRECTION $pinObjects]
    if {$direction eq "IN"} {
        set nets [get_nets -quiet -segments -of_objects $pinObjects]
        if {[llength $nets] == 0} {error "Unconnected mailbox input $pin"}
        set types [lsort -unique [get_property TYPE $nets]]
        if {$types eq "GROUND"} {return [dict create type CONST value 0]}
        if {$types eq "POWER"} {return [dict create type CONST value 1]}
        set drivers [get_pins -quiet -leaf -of_objects $nets -filter {DIRECTION == OUT}]
        if {[llength $drivers] != 1} {error "Mailbox input has non-single driver $pin: $drivers"}
        return [dict create type LUT width 1 init 2 inputs [list [get_property NAME $drivers]]]
    }
    set cells [get_cells -quiet -of_objects $pinObjects]
    if {[llength $cells] != 1} {error "Missing mailbox gate $pin"}
    set cell $cells
    set cellName [get_property NAME $cells]
    set ref [get_property REF_NAME $cell]
    set leaf [get_property REF_PIN_NAME $pinObjects]
    set record [dict create ref $ref output $leaf]
    if {$ref in {GND VCC}} {
        return [dict create type CONST value [expr {$ref eq "VCC"}]]
    } elseif {[regexp {^LUT([1-6])$} $ref -> width] || $ref eq "LUT6_2"} {
        if {$ref eq "LUT6_2"} {
            if {$leaf ni {O5 O6}} {error "Unknown LUT6_2 output $pin"}
            set width [expr {$leaf eq "O5" ? 5 : 6}]
        } elseif {$leaf ne "O"} {error "Unknown LUT output $pin"}
        set initText [get_property INIT $cell]
        if {![regexp {^[0-9]+'[hH]([0-9a-fA-F]+)$} $initText -> hex]} {error "Unparseable LUT INIT $cell $initText"}
        # hex is strictly validated above; assemble the numeric token before
        # Tcl expr parsing, then mask O5 of a LUT6_2 to its actual 32 entries.
        set init [expr [format {0x%s} $hex]]
        set init [expr {$init & ((1 << (1 << $width)) - 1)}]
        set inputs {}
        for {set n 0} {$n < $width} {incr n} {lappend inputs [native_mbox_one_pin $cellName/I$n]}
        dict set record init $initText
        dict set record inputs $inputs
        set result [dict create type LUT width $width init $init inputs $inputs]
    } elseif {$ref eq "INV" && $leaf eq "O"} {
        set result [dict create type INV inputs [list [native_mbox_one_pin $cellName/I]]]
    } elseif {$ref in {MUXF7 MUXF8 MUXF9} && $leaf eq "O"} {
        set result [dict create type MUX inputs [list [native_mbox_one_pin $cellName/I0] [native_mbox_one_pin $cellName/I1] [native_mbox_one_pin $cellName/S]]]
    } else {error "Unmodelled mailbox leaf $cell ($ref)/$leaf; requires explicit review"}
    dict set native_mbox_cone $cellName $record
    return $result
}
set facts [open [file join $output mailbox_next_state.txt] w]
puts $facts "CHECKPOINT=$checkpoint"
foreach {label hier bit} {TXCONFIG_BIT3 u_soc/nativeBank/gmac/txConfig/mailbox {[3]}
                         RXSTOP u_soc/nativeBank/gmac/rxStop/command {}} {
set native_mbox_cone {}
set roles [dict create held "${hier}/held_reg${bit}/Q" captured "${hier}/captured_reg${bit}/Q" \
    valid $hier/valid_reg/Q request "$hier/requestSync/stages_reg\[1\]/Q" ack $hier/ackToggle_reg/Q]
dict for {role pin} $roles {
    native_mbox_one_pin $pin
    set cell [get_cells -of_objects [get_pins $pin]]
    if {![get_property IS_SEQUENTIAL $cell]} {error "Mailbox role is not a register: $role"}
    set clock [get_clocks -quiet -of_objects [get_pins -of_objects $cell -filter {REF_PIN_NAME == C}]]
    set expected [expr {$role eq "held" ? 10.0 : 8.0}]
    if {[llength $clock] != 1 || abs([get_property PERIOD $clock]-$expected)>0.001} {error "Mailbox role uses wrong clock: $role"}
}
set captured [get_cells -of_objects [get_pins [dict get $roles captured]]]
set capturedName [get_property NAME $captured]
set capturedClock [get_pins -of_objects $captured -filter {REF_PIN_NAME == C}]
# Vivado 2025.1 leaves the cell parameter IS_C_INVERTED empty after routing.
# The actual clock pin's IS_INVERTED property remains an explicit boolean.
if {[get_property REF_NAME $captured] ne "FDRE" || [get_property IS_INVERTED $capturedClock] ne "0"} {
    error "Unreviewed capture primitive or clock inversion"
}
set resetNet [get_nets -segments -of_objects [get_pins -of_objects $captured -filter {REF_PIN_NAME == R}]]
if {[lsort -unique [get_property TYPE $resetNet]] ne "GROUND"} {error "Unexpected captured-data synchronous reset"}
set d [native_mbox_one_pin $capturedName/D]
set ce [native_mbox_one_pin $capturedName/CE]
set count [native_mbox_check_next $d $ce $roles native_mbox_resolve]
puts $facts "MAILBOX=$label"
dict for {role pin} $roles {puts $facts "ROLE $role $pin"}
dict for {cell record} $native_mbox_cone {puts $facts "ACTUAL_CONE $cell $record"}
puts $facts "PASS_${label}_ACTUAL_NEXT_STATE_${count}_CASES_RESET_INACTIVE"
}
puts $facts "No timing exception or CDC waiver added; protocol/timing/skew/reset review still required."
close $facts
close_design
puts "PASS_TXCONFIG_BIT3_AND_RXSTOP_ACTUAL_NEXT_STATE_32_CASES_RESET_INACTIVE NO_CONSTRAINTS_CHANGED NO_BIT"
