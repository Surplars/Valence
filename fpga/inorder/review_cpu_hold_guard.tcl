# Read-only uncertainty check on an existing DCP. No design/route/bit writes.
if {$argc != 2} {error "usage: review_cpu_hold_guard.tcl EXISTING_DCP FRESH_REPORT_DIR"}
set out [file normalize [lindex $argv 1]]
if {[file exists $out]} {error "Preserve previous hold-guard evidence"}
file mkdir $out
set_param general.maxThreads 8
open_checkpoint [file normalize [lindex $argv 0]]
set cpu [get_clocks -of_objects [get_pins u_soc/io_clockIn]]
if {[llength $cpu] != 1 || abs([get_property PERIOD $cpu] - 3.333) > 0.002} {
    error "Keep actual CPU300"
}
set before [get_property SLACK [get_timing_paths -from $cpu -to $cpu -delay_type min -max_paths 1]]
set setupBefore [get_property SLACK [get_timing_paths -from $cpu -to $cpu -delay_type max -max_paths 1]]
set_clock_uncertainty -from $cpu -to $cpu -hold 0.050
set after [get_property SLACK [get_timing_paths -from $cpu -to $cpu -delay_type min -max_paths 1]]
set setupAfter [get_property SLACK [get_timing_paths -from $cpu -to $cpu -delay_type max -max_paths 1]]
if {abs(($before-$after)-0.050) > 0.002 || abs($setupBefore-$setupAfter) > 0.002} {
    error "Extra hold budget must tighten exactly 50ps without changing setup"
}
report_timing -from $cpu -to $cpu -delay_type min -max_paths 5 -file [file join $out guarded_hold.rpt]
set f [open [file join $out result.txt] w]
puts $f "PASS_CPU_HOLD_GUARD_READ_ONLY before=$before after=$after extra_hold_ns=0.050 setup_before=$setupBefore setup_after=$setupAfter"
close $f
puts "PASS_CPU_HOLD_GUARD_READ_ONLY before=$before after=$after SETUP_UNCHANGED NO_DESIGN_CHANGES"
close_design
