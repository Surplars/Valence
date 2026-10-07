# Board implementation lowering: identity raw BUFG -> parallel managed BUFGCE.
# Logical clocks/CE/reset policy are unchanged; only clock insertion is balanced.
# This explicit board backend is idempotent, and never touches CPU/DDR clocks.
proc valence_native_parallel_clocks {} {
    foreach {raw managed group} {
        u_eth_clk_wiz/inst/clkout1_buf u_soc/nativeBank/gmac/txManaged_gate/buffer VALENCE_MAC_TX
        rx_clock_buffer u_soc/nativeBank/gmac/rxManaged_gate/buffer VALENCE_MAC_RX
    } {
        foreach cell [list $raw $managed] {
            if {[llength [get_cells -quiet $cell]]!=1 || [get_property REF_NAME [get_cells $cell]] ne "BUFGCE"} {error "Missing native BUFGCE: $cell"}
        }
        if {[get_property CE_TYPE [get_cells $managed]] ne "SYNC"} {error "Managed gate is not glitchless SYNC"}
        set constant [get_nets -of_objects [get_pins $raw/CE]]
        if {[get_property TYPE $constant] ne "POWER"} {error "Raw clock is not always on"}
        set source [get_nets -of_objects [get_pins $raw/I]]
        set old [get_nets -of_objects [get_pins $managed/I]]
        set sourceDriver [get_pins -leaf -of_objects [get_nets -segments $source] -filter {DIRECTION == OUT}]
        set oldDriver [get_pins -leaf -of_objects [get_nets -segments $old] -filter {DIRECTION == OUT}]
        if {$oldDriver ne $sourceDriver} {
            if {$oldDriver ne "$raw/O"} {error "Unaudited managed clock input: $managed ($oldDriver)"}
            set mutable [get_nets -segments [list $source $old]]
            set saved [dict create]
            foreach net $mutable {
                dict set saved $net [get_property DONT_TOUCH $net]
                set_property DONT_TOUCH FALSE $net
            }
            disconnect_net -net $old -objects [get_pins $managed/I]
            connect_net -hier -net $source -objects [get_pins $managed/I]
            dict for {net value} $saved {if {$value ne ""} {set_property DONT_TOUCH $value $net}}
            puts "NATIVE_PARALLEL_CLOCK $managed/I: $raw/O -> $sourceDriver"
        }
        set outputs [get_nets -of_objects [get_pins [list $raw/O $managed/O]]]
        if {[llength $outputs]!=2} {error "Missing raw/managed clock pair"}
        set_property CLOCK_DELAY_GROUP $group $outputs
    }
}
