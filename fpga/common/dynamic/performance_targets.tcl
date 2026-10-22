# Verify the targets already loaded BEFORE synthesis, without silently applying
# missing constraints after the expensive run. A relaxed synthesis must fail.
# These generated clocks are stress requirements, never hardware operating rates.
proc native_dynamic_performance_targets {} {
    set source [get_pins -quiet u_ddr/c0_ddr4_ui_clk]
    set masters [get_clocks -quiet -of_objects $source]
    if {[llength $source]!=1 || [llength $masters]!=1 || abs([get_property PERIOD $masters]-4.0)>0.002} {
        error "DYNAMIC_TARGET missing exact UI250 master"
    }
    foreach {root name period} {cpu_clock cpu_target300 3.333333333333 fabric_clock fabric_target250 4.0} {
        foreach pin [list $root/mmcm/CLKOUT0 $root/managed_buffer/O] {
            set clocks [get_clocks -quiet -of_objects [get_pins -quiet $pin]]
            if {[llength $clocks]!=1 || [get_property NAME $clocks] ne $name ||
                abs([get_property PERIOD $clocks]-$period)>0.002 ||
                [get_property MASTER_CLOCK $clocks] ne [get_property NAME $masters]} {
                error "DYNAMIC_TARGET missing or relaxed pre-synthesis target $pin"
            }
        }
    }
    # These clocks are checked, not recreated or regrouped. Preserve the fixed
    # peripheral rates and their UI-rooted master relationships.
    foreach {pin period} {
        u_ddr/c0_ddr4_ui_clk 4.0 u_clk_wiz/clk_out1 20.0
        u_soc/alwaysOnClock 20.0 u_soc/rawUartClock 20.0
        u_soc/ddrClock 4.0 u_soc/timebaseClock 4.0 u_soc/debugClock 4.0
        network_clock/tx_source 8.0 network_clock/tx_pad_source 4.0 network_clock/delay_source 2.0
    } {
        set clocks [get_clocks -quiet -of_objects [get_pins -quiet $pin]]
        if {[llength $clocks]!=1 || abs([get_property PERIOD $clocks]-$period)>0.002} {
            error "DYNAMIC_TARGET fixed clock changed $pin"
        }
        set ancestor $clocks;set visited {}
        while {[get_property NAME $ancestor] ne [get_property NAME $masters]} {
            set name [get_property NAME $ancestor]
            if {[lsearch -exact $visited $name]>=0} {error "DYNAMIC_TARGET fixed master cycle $pin"}
            lappend visited $name
            set parent [get_property MASTER_CLOCK $ancestor]
            if {[llength $parent]!=1} {error "DYNAMIC_TARGET fixed clock lost UI master $pin"}
            set ancestor [get_clocks -quiet $parent]
            if {[llength $ancestor]!=1} {error "DYNAMIC_TARGET missing fixed master $pin"}
        }
    }
    report_clocks -file dynamic-performance-target-clocks.rpt
    puts "DYNAMIC_TARGET_CPU300_FABRIC250 PRE_SYNTH_REQUIREMENTS NOT_ACTUAL_RUNTIME_RATES NO_BITSTREAM"
}
