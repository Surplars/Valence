# ECO placer retains implemented IDELAYCTRL RDY aggregation. The ECO router
# can move blocking routes; no constraint, clock or interface is relaxed.
if {$argc != 2} {error "Expected PRIVATE_ROOT DONOR_ROOT"}
lassign $argv root donor
foreach name {root donor} {set $name [file normalize [set $name]]}
set_param general.maxThreads 8
set out [file join $root implementation-report-recovery-r1]
if {[file exists [file join $out routed.dcp]] || [file exists [file join $out eco_placed_r3.dcp]]} {
    error "Preserve prior ECO output"
}
open_checkpoint [file join $out patched_context.dcp]
proc review_real_delay_ready {} {
    set net [get_nets -segments u_rgmii/delay_ready]
    set driver [get_pins -leaf -of_objects $net -filter {DIRECTION == OUT}]
    if {[llength $driver] != 1 || [get_property NAME $driver] ne "u_rgmii/u_rgmii/delay_control_TOP_AND/O"} {
        error "Lost implemented IDELAYCTRL ready aggregation"
    }
    set cell [get_cells -of_objects $driver]
    if {[get_property REF_NAME $cell] ne "LUT3" || [get_property INIT $cell] ne "8'h80"} {
        error "IDELAYCTRL RDY must be exact three-way AND"
    }
    set rdys {}
    foreach pin [get_pins -of_objects $cell -filter {DIRECTION == IN}] {
        set source [get_pins -leaf -of_objects [get_nets -segments -of_objects $pin] -filter {DIRECTION == OUT}]
        if {[llength $source] != 1 || [get_property REF_PIN_NAME $source] ne "RDY" ||
            [get_property REF_NAME [get_cells -of_objects $source]] ne "IDELAYCTRL"} {
            error "Calibration readiness cannot be tied off or disconnected"
        }
        lappend rdys [get_property NAME $source]
    }
    if {[llength [lsort -unique $rdys]] != 3} {error "Missing calibration RDY input"}
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
    {write_checkpoint [file join $out eco_placed_r3.dcp]}
    {route_design -directive Quick -preserve}
    {route_design -eco
review_real_delay_ready}
} {
    set first [string first $needle $body]
    if {$first < 0 || [string first $needle $body [expr {$first + 1}]] >= 0} {
        error "Ambiguous ECO command substitution: $needle"
    }
    set body [string replace $body $first [expr {$first + [string length $needle] - 1}] $replacement]
}
set argc 3
set argv [list $root $donor route]
eval $body
