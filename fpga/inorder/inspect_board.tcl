# Read-only linked-board endpoint audit; does not alter design or constraints.
if {$argc != 1} {error "usage: inspect_board.tcl BOARD_POST_SYNTH_DCP"}
open_checkpoint [lindex $argv 0]
foreach cell [get_cells -hier -filter {REF_NAME =~ CdcLevel*}] {
    set hier [get_property NAME $cell]
    puts "I1_LEVEL_CELL $hier REF=[get_property REF_NAME $cell]"
    foreach reg [get_cells -quiet "$hier/stages_reg*"] {
        set d [get_pins -quiet "$reg/D"]
        set nets [get_nets -segments -of_objects $d]
        set pins [get_pins -quiet -leaf -of_objects $nets -filter {DIRECTION == OUT}]
        puts "I1_LEVEL_STAGE $reg D=$d NET=$nets LEAF_DRIVER=$pins"
        foreach pin $pins {
            puts "I1_LEVEL_SOURCE $pin REF=[get_property REF_NAME [get_cells -of_objects $pin]]"
        }
    }
}
foreach clk [get_cells -hier -filter {REF_NAME == BUFGCE && NAME =~ u_soc/*}] {
    puts "I1_MANAGED_CLOCK [get_property NAME $clk]"
}
puts "I1_UART_META [get_cells -quiet -hier -filter {NAME =~ *sampledRx_meta_reg}]"
report_clocks
close_design
