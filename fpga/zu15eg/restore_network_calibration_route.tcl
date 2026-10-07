# UltraScale+ supported recovery: reuse own already-placed two-leaf design.
# Restore ONLY the two exact IDELAYCTRL AND LUTs removed by repeat placement.
# Driver identities, truth tables and original LOC/BEL are rechecked. No READY
# tie-off, clock/timing exception, PHY budget or functional RTL is changed.
if {$argc != 2} {error "Expected PRIVATE_ROOT DONOR_ROOT"}
lassign $argv root donor
foreach name {root donor} {set $name [file normalize [set $name]]}
set out [file join $root implementation-report-recovery-r1]
if {[file exists [file join $out routed.dcp]] || [file exists [file join $out eco_placed_restored.dcp]]} {
    error "Preserve prior recovery output"
}
set_param general.maxThreads 8
set f [open [file join $root scripts route_network_eco_r2.tcl] r]
set definition [read $f]; close $f
set start [string first {proc actual_ready_inputs} $definition]
set end [string first "\nreview_real_delay_ready\n" $definition $start]
if {$start < 0 || $end < $start} {error "Missing frozen exact ready-cone checker"}
eval [string range $definition $start [expr {$end - 1}]]
open_checkpoint [file join $out patched_context.dcp]
review_real_delay_ready
set snapshot [dict create]
foreach name {u_rgmii/u_rgmii/delay_control_TOP_AND u_rgmii/u_rgmii/delay_control_TOP_AND_1} {
    set c [get_cells -quiet $name]
    if {[llength $c] != 1 || [get_property REF_NAME $c] ne "LUT2" || [get_property INIT $c] ne "4'h8"} {
        error "Recovery must use the two actual donor AND truth tables"
    }
    set inputs [dict create]
    foreach pin [get_pins -of_objects $c -filter {DIRECTION == IN}] {
        set driver [get_pins -leaf -of_objects [get_nets -segments -of_objects $pin] -filter {DIRECTION == OUT}]
        if {[llength $driver] != 1} {error "Ambiguous donor AND input"}
        dict set inputs [get_property REF_PIN_NAME $pin] [get_property NAME $driver]
    }
    set net [get_nets -of_objects [get_pins $c/O]]
    if {[llength $net] != 1} {error "Ambiguous donor AND output"}
    dict set snapshot $name [dict create ref LUT2 init 4'h8 loc [get_property LOC $c] bel [get_property BEL $c] inputs $inputs output [get_property NAME $net]]
}
set f [open [file join $out original_calibration_gates.tcldict] w]
puts $f $snapshot; close $f
close_design
open_checkpoint [file join $out eco_placed.dcp]
dict for {name properties} $snapshot {
    set cell [get_cells -quiet $name]
    if {![llength $cell]} {
        create_cell -reference [dict get $properties ref] $name
        set cell [get_cells $name]
        set_property INIT [dict get $properties init] $cell
    } elseif {[llength $cell] != 1 || [get_property REF_NAME $cell] ne [dict get $properties ref] ||
              [get_property INIT $cell] ne [dict get $properties init]} {
        error "Do not modify a nonidentical surviving calibration LUT"
    }
    set output [dict get $properties output]
    if {![llength [get_nets -quiet $output]]} {create_net $output}
    set net [get_nets $output]
    set drivers [get_pins -quiet -leaf -of_objects [get_nets -segments $net] -filter {DIRECTION == OUT}]
    if {[llength $drivers] && $drivers ne [get_pins $name/O]} {
        error "Do not replace another calibration driver"
    }
    set oldNet [get_nets -quiet -of_objects [get_pins $name/O]]
    if {[llength $oldNet] && $oldNet ne $net} {
        if {[llength [get_pins -quiet -leaf -of_objects [get_nets -segments $oldNet] -filter {DIRECTION == IN}]]} {
            error "Do not disconnect a used calibration output"
        }
        disconnect_net -net $oldNet -objects [get_pins $name/O]
    }
    if {![llength $drivers]} {connect_net -net $net -objects [get_pins $name/O]}
}
dict for {name properties} $snapshot {
    dict for {pin source} [dict get $properties inputs] {
        set driver [get_pins -quiet $source]
        if {[llength $driver] != 1} {error "Missing actual original calibration input: $source"}
        set net [get_nets -of_objects $driver]
        if {[llength $net] != 1} {error "Ambiguous real RDY net"}
        set targetPin [get_pins $name/$pin]
        set connected [get_nets -quiet -of_objects $targetPin]
        if {[llength $connected]} {
            set actualDriver [get_pins -quiet -leaf -of_objects [get_nets -segments $connected] -filter {DIRECTION == OUT}]
            if {$actualDriver ne $driver} {error "Do not replace another calibration input driver"}
        } else {
            connect_net -net $net -objects $targetPin
        }
    }
    set loc [dict get $properties loc]
    set bel [lindex [split [dict get $properties bel] .] end]
    set target [get_bels -quiet $loc/$bel]
    set occupied [get_cells -quiet -of_objects $target]
    if {[llength $target] != 1 || ([llength $occupied] && $occupied ne [get_cells $name])} {
        error "Original calibration placement is unavailable: $loc/$bel"
    }
    if {![llength $occupied]} {place_cell [get_cells $name] $target}
    if {[get_property LOC [get_cells $name]] ne $loc ||
        [get_property BEL [get_cells $name]] ne [dict get $properties bel]} {error "Original calibration placement changed"}
}
review_real_delay_ready
report_drc -checks [get_drc_checks LUTOI-1] -file [file join $out restored_input_drc.rpt]
if {[llength [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]]} {
    error "Restored primitive connectivity DRC failed"
}
write_checkpoint [file join $out eco_placed_restored.dcp]
set f [open [file join $root scripts replace_network_candidate.tcl] r]
set body [read $f]; close $f
foreach {needle replacement} {
    {open_checkpoint [file join $out patched_boundary_pending.dcp]}
    {# Own restored placed checkpoint is already open.}
    {place_design -directive Quick}
    {# Reuse own placed leaves; exact calibration restoration was verified.}
    {write_checkpoint [file join $out eco_placed.dcp]}
    {# Own restored checkpoint already saved, preserve failed attempt too.}
    {route_design -directive Quick -preserve}
    {route_design -directive Explore
review_real_delay_ready}
} {
    set first [string first $needle $body]
    if {$first < 0 || [string first $needle $body [expr {$first + 1}]] >= 0} {error "Ambiguous route substitution: $needle"}
    set body [string replace $body $first [expr {$first + [string length $needle] - 1}] $replacement]
}
set argc 3
set argv [list $root $donor route]
eval $body
