# Read-only donor interface review. No net edits, implementation or constraints.
if {$argc!=2} {error "Expected DONOR_CHECKPOINT OUTPUT"}
lassign $argv checkpoint output
set_param general.maxThreads 8
open_checkpoint $checkpoint
set f [open $output w]
foreach {leaf top} {u_soc/platform/privateCache CoherentLineCache u_soc/platform/packetDma EthernetPacketDma} {
    puts $f "LEAF=$leaf REF=[get_property REF_NAME [get_cells $leaf]]"
    foreach pin [get_pins -of_objects [get_cells $leaf]] {
        set name [get_property REF_PIN_NAME $pin]
        if {[string match "*alias*" $name]} {
            set nets [get_nets -quiet -segments -of_objects $pin]
            set drivers [get_pins -quiet -leaf -of_objects $nets -filter {DIRECTION == OUT}]
            set sinks [get_pins -quiet -leaf -of_objects $nets -filter {DIRECTION == IN}]
            puts $f "ALIAS $top [get_property DIRECTION $pin] {$name} DRIVERS={$drivers} SINKS={$sinks}"
        }
    }
}
close $f
puts "READ_ONLY_ECO_BOUNDARY_ALIAS_REVIEW_COMPLETE"
close_design
