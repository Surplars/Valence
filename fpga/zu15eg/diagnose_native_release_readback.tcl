# Only read the selected routed netlist; no implementation or exceptions.
if {$argc != 2} {error "Expected ROUTED_DCP FRESH_REPORT"}
lassign $argv checkpoint report
if {[file exists $report]} {error "Preserve previous diagnostic"}
set_param general.maxThreads 8
open_checkpoint $checkpoint
set f [open $report w]
puts $f "CHECKPOINT=[file normalize $checkpoint]"
foreach name {
    software_phy.tx_release/tx_reset_pipe_reg[2]/Q
    u_rgmii/tx_clock_ddr/RST u_rgmii/tx_control_ddr/RST
    u_rgmii/quarter_tx_boundary.phase_high_reg/PRE
    u_soc/nativeBank/gmac/txConfig/mailbox/captured_reg[3]/C
} {
    set pin [get_pins -quiet $name]
    puts $f "PIN=$name FOUND=[llength $pin]"
    if {[llength $pin] != 1} {continue}
    puts $f "NETS=[get_nets -of_objects $pin]"
    puts $f "SEGMENTS=[get_nets -segments -of_objects $pin]"
    puts $f "DRIVERS=[get_pins -leaf -of_objects [get_nets -segments -of_objects $pin] -filter {DIRECTION == OUT}]"
    puts $f "STARTS=[all_fanin -flat -startpoints_only -to $pin]"
    puts $f "PIN_PROPERTIES=[list_property $pin]"
    foreach property {IS_INVERTED IS_CLOCK_INVERTED IS_C_INVERTED} {
        puts $f "$property=[get_property -quiet $property $pin]"
    }
    set cell [get_cells -of_objects $pin]
    puts $f "CELL=$cell REF=[get_property REF_NAME $cell]"
    foreach property [list_property $cell] {
        if {[string match *INVERT* $property]} {puts $f "$property=[get_property $property $cell]"}
    }
}
close $f
close_design
puts "PASS_READ_ONLY_RELEASE_DIAGNOSTIC"
