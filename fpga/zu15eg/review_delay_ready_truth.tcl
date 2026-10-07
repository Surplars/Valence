if {$argc != 2} {error "Expected CHECKPOINT REPORT"}
lassign $argv checkpoint report
set_param general.maxThreads 8
open_checkpoint $checkpoint
set cell [get_cells u_rgmii/u_rgmii/delay_control_TOP_AND]
set f [open $report w]
puts $f [report_property -all -return_string $cell]
foreach pin [get_pins -of_objects $cell] {
    set nets [get_nets -quiet -segments -of_objects $pin]
    puts $f "PIN=$pin NETS=$nets DRIVERS=[get_pins -quiet -leaf -of_objects $nets -filter {DIRECTION == OUT}]"
}
close $f
close_design
