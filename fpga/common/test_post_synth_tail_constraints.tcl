# Mock-only driver. Native Vivado is deliberately not invoked.
# Usage: tclsh test_post_synth_tail_constraints.tcl fixture.xdc output-directory
set here [file dirname [file normalize [info script]]]
set ::fixture [file normalize [lindex $argv 0]]
cd [lindex $argv 1]
set ::exports 0
set ::live_calls 0
foreach command {set_max_delay set_bus_skew create_clock create_generated_clock
                 set_false_path set_clock_groups set_property read_xdc
                 get_pins get_ports get_clocks get_cells get_nets get_property
                 current_instance current_scope all_fanin all_fanout get_timing_paths get_timing_arcs report_exceptions} {
    proc $command args {
        incr ::live_calls
        error "Forbidden live mutation/query: [lindex [info level 0] 0]"
    }
}
proc write_xdc args {
    incr ::exports
    if {[lrange $args 0 3] ne {-constraints valid -type timing} || [llength $args] != 5} {
        error "Wrong native export options: $args"
    }
    file copy $::fixture [lindex $args 4]
}
source [file join $here post_synth_tail_constraints.tcl]
if {$::exports || $::live_calls || [file exists tail-retained-constraints.json]} {
    error "Sourcing the helper performed work"
}
set result [post_synth_tail_retained_constraints]
if {$::exports != 1 || $::live_calls || ![file exists $result]} {
    error "Read-only export contract violated"
}
# Repeat in the same interpreter: a scoped final statement must not leak its
# current_instance into the next independent read of the same immutable export.
set first_rows $::post_synth_tail_constraints::rows
if {[post_synth_tail_constraints::read_rows tail-retained.xdc 1] ne $first_rows} {
    error "Scope context leaked across read_rows invocations"
}
if {![catch {post_synth_tail_retained_constraints} message] ||
    ![string match {*outputs already exist*} $message] || $::exports != 1} {
    error "Existing evidence was not refused"
}
puts "TAIL_RETAINED_MOCK_PASS NOT_NATIVE_QUALIFIED"
