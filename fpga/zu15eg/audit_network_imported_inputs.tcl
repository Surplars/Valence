# Read-only bounded input audit: batch hierarchical segments, leaf-local sinks.
if {$argc!=2} {error "Expected OWN_PATCHED_CHECKPOINT FRESH_REPORT"}
lassign $argv checkpoint output
if {[file exists $output]} {error "Preserve prior input audit"}
set_param general.maxThreads 8
open_checkpoint $checkpoint
set f [open $output w]
puts $f "CHECKPOINT=[file normalize $checkpoint]"
set total 0
set dangling 0
foreach {leaf top} {u_soc/platform/privateCache CoherentLineCache u_soc/platform/packetDma EthernetPacketDma} {
    set cell [get_cells -quiet $leaf]
    if {[llength $cell]!=1 || [get_property REF_NAME $cell] ne $top} {error "Wrong input-audit partition"}
    foreach pin [get_pins -of_objects $cell -filter {DIRECTION == IN}] {
        incr total
        set nets [get_nets -quiet -segments -of_objects $pin]
        set drivers [get_pins -quiet -leaf -of_objects $nets -filter {DIRECTION == OUT}]
        set sinks [get_pins -quiet -leaf -of_objects $nets -filter "DIRECTION == IN && NAME =~ $leaf/*"]
        set types {}
        if {[llength $nets]} {set types [lsort -unique [get_property TYPE $nets]]}
        set constant [expr {$types eq "GROUND" || $types eq "POWER"}]
        puts $f "PIN=$pin DRIVERS=[lsort -unique $drivers] TYPES={$types} LOCAL_SINKS=[llength $sinks] CONSTANT=$constant"
        if {[llength $sinks] && ![llength $drivers] && !$constant} {
            incr dangling
            puts $f "DANGLING_USED_INPUT=$pin"
        }
    }
    puts "BOUNDED_IMPORTED_INPUTS_REVIEWED $leaf"
}
puts $f "INPUT_COUNT=$total DANGLING_COUNT=$dangling"
close $f
close_design
puts "IMPORTED_INPUT_BOUNDARY_RESULT inputs=$total dangling=$dangling"
if {$dangling} {error "Used partition inputs lack a driver/constant; require actual RTL proof"}
