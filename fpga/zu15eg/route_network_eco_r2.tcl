# Native ECO place/route. Verify the actual two-level calibration AND cone,
# rather than assuming one LUT3. No timing constraints or logic are changed.
if {$argc != 2} {error "Expected PRIVATE_ROOT DONOR_ROOT"}
lassign $argv root donor
foreach name {root donor} {set $name [file normalize [set $name]]}
set_param general.maxThreads 8
set out [file join $root implementation-report-recovery-r1]
if {[file exists [file join $out routed.dcp]] || [file exists [file join $out eco_placed_r4.dcp]]} {
    error "Preserve prior ECO output"
}
open_checkpoint [file join $out patched_context.dcp]
proc actual_ready_inputs {driver depth} {
    if {$depth > 3 || [llength $driver] != 1} {error "Invalid calibration ready cone"}
    set cell [get_cells -of_objects $driver]
    set ref [get_property REF_NAME $cell]
    if {$ref eq "IDELAYCTRL" && [get_property REF_PIN_NAME $driver] eq "RDY"} {
        return [list [get_property NAME $driver]]
    }
    if {![regexp {^LUT([23])$} $ref -> width]} {error "Not an exact calibration AND gate: $ref"}
    set init [get_property INIT $cell]
    if {![regexp {^([0-9]+)'h([0-9A-Fa-f]+)$} $init -> bits digits]} {error "Unparsed ready LUT INIT"}
    scan $digits %x value
    if {$bits != (1 << $width) || $value != (1 << ((1 << $width) - 1))} {
        error "Calibration RDY must be an exact AND truth table: $init"
    }
    set pins [get_pins -of_objects $cell -filter {DIRECTION == IN}]
    if {[llength $pins] != $width} {error "Missing AND input"}
    set rdys {}
    foreach pin $pins {
        set nets [get_nets -segments -of_objects $pin]
        set source [get_pins -leaf -of_objects $nets -filter {DIRECTION == OUT}]
        set rdys [concat $rdys [actual_ready_inputs $source [expr {$depth + 1}]]]
    }
    return $rdys
}
proc review_real_delay_ready {} {
    set driver [get_pins -leaf -of_objects [get_nets -segments u_rgmii/delay_ready] -filter {DIRECTION == OUT}]
    if {[llength $driver] != 1 || [get_property NAME $driver] ne "u_rgmii/u_rgmii/delay_control_TOP_AND/O"} {
        error "Lost implemented IDELAYCTRL ready aggregation"
    }
    set rdys [actual_ready_inputs $driver 0]
    set expected {u_rgmii/delay_control/RDY u_rgmii/delay_control_REPLICATED_0/RDY u_rgmii/delay_control_REPLICATED_0_1/RDY}
    if {[llength $rdys] != 3 || [lsort $rdys] ne [lsort $expected]} {error "Missing or duplicated calibration controller RDY"}
    puts "PASS_REAL_THREE_CONTROLLER_CALIBRATION_READINESS $rdys"
}
review_real_delay_ready
set f [open [file join $root scripts replace_network_candidate.tcl] r]
set body [read $f]; close $f
foreach {needle replacement} {
    {open_checkpoint [file join $out patched_boundary_pending.dcp]}
    {# Own context-specialized checkpoint is already open.}
    {place_design -directive Quick}
    {place_design -eco
review_real_delay_ready}
    {write_checkpoint [file join $out eco_placed.dcp]}
    {write_checkpoint [file join $out eco_placed_r4.dcp]}
    {route_design -directive Quick -preserve}
    {route_design -eco
review_real_delay_ready}
} {
    set first [string first $needle $body]
    if {$first < 0 || [string first $needle $body [expr {$first + 1}]] >= 0} {error "Ambiguous ECO command substitution: $needle"}
    set body [string replace $body $first [expr {$first + [string length $needle] - 1}] $replacement]
}
set argc 3
set argv [list $root $donor route]
eval $body
