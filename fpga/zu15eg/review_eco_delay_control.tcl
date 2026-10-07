# Read-only inspection of RGMII calibration connectivity before/after ECO place.
if {$argc == 0} {
    place_design -help
    route_design -help
    exit
}
if {$argc != 3} {error "Expected CHECKPOINT REPORT LABEL"}
lassign $argv checkpoint report label
set_param general.maxThreads 8
open_checkpoint $checkpoint
set f [open $report w]
puts $f "LABEL=$label CHECKPOINT=$checkpoint"
foreach c [get_cells -hier -filter {REF_NAME == IDELAYCTRL || REF_NAME == IDELAYE3}] {
    puts $f "CELL=$c REF=[get_property REF_NAME $c] LOC=[get_property LOC $c] BEL=[get_property BEL $c] GROUP=[get_property IODELAY_GROUP $c]"
    foreach p [get_pins -of_objects $c] {
        set segments [get_nets -quiet -segments -of_objects $p]
        puts $f " PIN=$p NETS=$segments DRIVERS=[get_pins -quiet -leaf -of_objects $segments -filter {DIRECTION == OUT}]"
    }
}
foreach pattern {u_rgmii/delay_ready phy_reset_pipe* rx_reset_pipe* software_phy.tx_release_i_1} {
    if {$pattern eq "u_rgmii/delay_ready"} {
        set nets [get_nets -quiet -segments $pattern]
        puts $f "DELAY_READY_SEGMENTS=$nets DRIVERS=[get_pins -quiet -leaf -of_objects $nets -filter {DIRECTION == OUT}] SINKS=[get_pins -quiet -leaf -of_objects $nets -filter {DIRECTION == IN}]"
    } else {
        foreach c [get_cells -quiet $pattern] {
            puts $f "RESET_CELL=$c REF=[get_property REF_NAME $c]"
            foreach p [get_pins -of_objects $c -filter {DIRECTION == IN}] {
                puts $f " PIN=$p NET=[get_nets -quiet -of_objects $p]"
            }
        }
    }
}
close $f
puts "READ_ONLY_DELAY_CONTROL_REVIEW_COMPLETE $report"
close_design
