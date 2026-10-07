open_checkpoint [lindex $argv 0]
foreach hier {gmac/txFifo/fifo gmac/rxFifo/fifo} {
    puts "FIFO $hier captures=[llength [get_cells -quiet $hier/output_0_reg*]]"
    foreach c [get_cells -hier -filter "NAME =~ $hier/storage_ext/* && IS_PRIMITIVE == 1"] {
        puts "RAM $c [get_property REF_NAME $c]"
    }
    set ends [get_pins -of_objects [get_cells -quiet $hier/output_0_reg*] -filter {REF_PIN_NAME == D}]
    set drivers [all_fanin -flat -startpoints_only -to $ends]
    puts "RAM_DRIVERS $drivers"
}
foreach c [get_cells -hier -filter {REF_NAME =~ CdcLevel*}] {
    set ends [get_pins -of_objects [get_cells -quiet $c/stages_reg?0?] -filter {REF_PIN_NAME == D}]
    puts "LEVEL $c [all_fanin -flat -startpoints_only -to $ends]"
}
puts "UART_META [get_cells -hier *sampledRx_meta*]"
exit
