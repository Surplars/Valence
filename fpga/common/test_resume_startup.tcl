# Targeted tripwires for standalone optimized-checkpoint resume startup.
set directory [file dirname [info script]]
source [file join $directory skew_scope.tcl]
source [file join $directory common_cdc.tcl]
foreach name {clock ff drivers loads one quote} {
 if {![llength [info commands common_cdc::$name]]} {error "Missing async IO gate helper $name"}
}
set f [open [file join $directory recovery_map_constraints.tcl]];set code [read $f];close $f
set start [string first { set alias_pin [get_pins} $code]
set stop [string first { source [file join $valence(root) fpga common debug_hub_clock.tcl]} $code $start]
if {$start<0 || $stop<0} {error {Missing exact UART alias guard}}
set guard [string range $code $start [expr {$stop-1}]]
proc get_pins args {return alias}
proc get_clocks args {return {}}
proc get_nets args {if {$::fixture eq {DISCONNECTED}} {return {}};return net}
proc get_property args {return $::fixture}
foreach ::fixture {DISCONNECTED GROUND} {eval $guard}
set ::fixture SIGNAL
if {![catch {eval $guard}]} {error {Connected unclocked functional alias incorrectly accepted}}
puts RAW_OPT_STARTUP_HELPERS_AND_UART_ALIAS_POSITIVE_NEGATIVE_PASS
