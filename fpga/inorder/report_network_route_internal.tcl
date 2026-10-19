# Read-only same-routed-checkpoint CPU/core partition. NO constraint changes.
if {$argc != 2} { error "usage: report_network_route_internal.tcl ROUTED_DCP FRESH_OUTPUT" }
lassign $argv checkpoint output
set checkpoint [file normalize $checkpoint]
set output [file normalize $output]
if {[file exists $output]} { error "preserve existing read-only audit evidence" }
file mkdir $output
set_param general.maxThreads 8
open_checkpoint $checkpoint
if {[get_property TOP [current_design]] ne "I1NetworkFpgaShell" ||
    abs([get_property PERIOD [get_clocks orbital_i1_cpu]] - 3.333) > 0.0005} {
    error "wrong routed network checkpoint/clock"
}
set cpu [get_cells -quiet -hierarchical -filter {IS_SEQUENTIAL == 1 && NAME =~ soc/*}]
set core [get_cells -quiet -hierarchical -filter {IS_SEQUENTIAL == 1 && NAME =~ soc/core/*}]
set result [open [file join $output result.json] w]
puts $result "{"
set comma ""
foreach {name starts ends kind} [list \
    setup_cpu_internal $cpu $cpu max \
    setup_core_internal $core $core max \
    hold_core_internal $core $core min] {
    if {![llength $starts] || ![llength $ends]} { error "missing actual partition: $name" }
    set path [get_timing_paths -from $starts -to $ends -delay_type $kind -max_paths 1]
    if {[llength $path] != 1} { error "missing real routed timing: $name" }
    set slack [get_property SLACK $path]
    puts $result "$comma\"$name\":$slack"
    set comma ","
    report_timing -from $starts -to $ends -delay_type $kind -max_paths 20 -nworst 1 \
        -file [file join $output $name.rpt]
    puts "I1_NETWORK_ROUTED_INTERNAL scope=$name slack=$slack checkpoint=$checkpoint"
}
puts $result "}"
close $result
puts "I1_NETWORK_ROUTE_INTERNAL_AUDIT_DONE NO_SYNTHESIS_NO_IMPLEMENTATION_NO_CONSTRAINT_CHANGES"
close_design
