# Read-only local Vivado command discovery; no project or design is opened.
puts "I1_AVAILABLE_CLOCK_COMMANDS [lsort [info commands *clock*]]"
puts "I1_AVAILABLE_TIMING_COMMANDS [lsort [info commands *timing*]]"
puts "I1_AVAILABLE_RESET_COMMANDS [lsort [info commands reset*]]"
puts [help create_clock]
puts [help create_generated_clock]
foreach command {delete_timing reset_timing} {
    if {[llength [info commands $command]]} {puts [help $command]}
}
foreach command {delete_clock delete_clocks remove_clock remove_clocks} {
    if {[llength [info commands $command]]} {help $command}
}
exit
