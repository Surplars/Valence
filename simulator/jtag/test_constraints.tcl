# Syntax/collection-count tests using mocked Vivado commands. Not physical signoff.
source [file join [file dirname [info script]] ../../fpga/constraints/jtag-reservation.xdc.example]
set created 0
set maxdelays 0
set skews 0
set fail_select 0
proc get_ports {args} {return tck}
proc get_clocks {args} { if {[llength $args]>1} {return {}};return debug_clock }
proc create_clock {args} {incr ::created}
proc get_pins {args} {
    if {$::fail_select} {return {}}
    set expression [lindex $args end]
    set list {}
    foreach {name count pin} {request_sync 2 D response_sync 2 D request_held 41 Q dest_request 41 D response_held 34 Q s_rsp_payload 34 D} {
        for {set i 0} {$i<$count} {incr i} {
            set namepin [format {soc/debug/transport/enabled/bridge/%s_reg[%d]/%s} $name $i $pin]
            if {[regexp $expression $namepin]} {lappend list $namepin}
        }
    }
    return $list
}
proc set_false_path {args} {}
proc set_max_delay {args} {incr ::maxdelays}
proc set_bus_skew {args} {incr ::skews}
constrain_valence_jtag soc/debug/transport/enabled tck debug_clock 100 10 7
if {$created!=1 || $maxdelays!=2 || $skews!=2} {error "Missing scoped constraints"}
set fail_select 1
if {![catch {constrain_valence_jtag soc/debug/transport/enabled tck debug_clock 100 10 7} failure]} {
    error "Missing hierarchy did not fail closed"
}
if {![string match {*expected 1*} $failure]} {error "Wrong collection failure: $failure"}
puts "PASS constraint template syntax, scoped paths and fail-closed collections (mock only)"
