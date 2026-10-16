# Actual Vivado object spelling: enabled.<instance>, not enabled/<instance>.
# Adapt only the five bound topology/control procedures; no timing budget or
# exception changes. Preserve complete before/after procedure evidence.
set before [open network-scope-r10-before.tcl w]
set after [open network-scope-r10-after.tcl w]
foreach name {valence_quarter_tx_clocks v_reset_release v_clock_placement v_control_constraints valence_trispeed_clock_reset_audit} {
    set body [info body $name]
    set arguments {}
    foreach argument [info args $name] {
        if {[info default $name $argument default]} {lappend arguments [list $argument $default]} else {lappend arguments $argument}
    }
    puts $before [list proc $name $arguments $body]
    set adapted [string map [list {network_clock/enabled/} {network_clock/enabled.}] $body]
    if {$name eq {valence_quarter_tx_clocks}} {
        set adapted [string map [list {set h $hier/enabled} {set h $hier/enabled.} {$h/} {${h}}] $adapted]
    }
    puts $after [list proc $name $arguments $adapted]
    proc $name $arguments $adapted
}
close $before;close $after
# Vivado's actual synthesis log explicitly optimized this INTERNAL feedback
# net away. Accept only both empty feedback pins on this exact retained PLL;
# every external clock ownership pair still uses the original strict check.
rename valence_trispeed_same_net valence_trispeed_same_net_original_r10
proc valence_trispeed_same_net {left right label} {
    if {$left eq {network_clock/enabled.pll/CLKFBOUT} && $right eq {network_clock/enabled.pll/CLKFBIN}} {
        set pll [get_cells -quiet network_clock/enabled.pll]
        if {[llength $pll]!=1 || [get_property REF_NAME $pll] ne {PLLE4_ADV} || [get_property COMPENSATION $pll] ne {INTERNAL}} {error {Unproved internal PLL feedback topology}}
        set a [get_pins -quiet $left];set b [get_pins -quiet $right]
        if {[llength $a]!=1 || [llength $b]!=1} {error {Missing actual PLL feedback pin}}
        if {![llength [get_nets -quiet -segments -of_objects $a]] && ![llength [get_nets -quiet -segments -of_objects $b]]} {
            puts {ACTUAL_VENDOR_INTERNAL_PLL_FEEDBACK_OPTIMIZED_AWAY_BOTH_PINS_EMPTY_NO_TIMING_EXCEPTION}
            return
        }
    }
    return [valence_trispeed_same_net_original_r10 $left $right $label]
}
diag_event network_clock generated_scope_adapted {ACTUAL_ENABLED_DOT_INSTANCE_AND_INTERNAL_FEEDBACK_ONLY}
