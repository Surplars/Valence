# Verify the targets already loaded BEFORE synthesis, without silently applying
# missing constraints after the expensive run. A relaxed synthesis must fail.
# These generated clocks are stress requirements, never hardware operating rates.
proc native_dynamic_clock_summary {clocks} {
    set result {}
    foreach clock $clocks {lappend result "[get_property NAME $clock](period=[get_property PERIOD $clock])"}
    if {![llength $result]} {return {<none>}}
    return [join $result ,]
}

# Shared, read-only AON/UART proof for synthesis/opt and the final board audit.
# The top/intermediate rawUartClock ports can be redundant, grounded hierarchy
# aliases after synthesis. They are not functional clock anchors. Prove the
# surviving raw ingress, physical gate, and every console FF clock instead.
proc native_fixed_uart_clock_check {{tag DYNAMIC_TARGET}} {
    set uart u_soc/peripherals/uart
    set aon_driver u_clk_wiz/inst/clkout1_buf/O
    set gate $uart/gatedClock_gate/buffer
    set gate_cell [get_cells -quiet $gate]
    if {[llength $gate_cell]!=1 || [get_property NAME $gate_cell] ne $gate ||
        [get_property REF_NAME $gate_cell] ne "BUFGCE" || [get_property CE_TYPE $gate_cell] ne "SYNC"} {
        error "$tag UART expected exact synchronous BUFGCE $gate"
    }
    set anchors [list u_clk_wiz/clk_out1 $aon_driver u_soc/alwaysOnClock $aon_driver \
        $uart/rawClock $aon_driver $uart/gatedClock_gate/rawClock $aon_driver \
        $gate/I $aon_driver $uart/sampledRx_meta_reg/C $aon_driver \
        $gate/O $gate/O $uart/uart/clock $gate/O]
    set registers [get_cells -quiet -hier -filter {REF_NAME =~ FD* && NAME =~ u_soc/peripherals/uart/uart/*}]
    if {![llength $registers]} {error "$tag UART missing console FF clock endpoints"}
    # Fetch only the scoped cells' C pins, then retain every pin's association.
    # A collective get_clocks result can hide an unclocked individual FF.
    set register_pins {}
    foreach cell $registers {
        set name [get_property NAME $cell]
        if {[string first "$uart/uart/" $name]!=0 || [string length $name]<=[string length "$uart/uart/"] ||
            ![string match FD* [get_property REF_NAME $cell]]} {
            error "$tag UART unexpected console FF cell $name"
        }
        set pin $name/C
        if {[dict exists $register_pins $pin]} {error "$tag UART duplicate console FF clock pin $pin"}
        dict set register_pins $pin {}; lappend anchors $pin $gate/O
    }
    foreach object [get_pins -quiet -of_objects $registers -filter {REF_PIN_NAME == C}] {
        set pin [get_property NAME $object]
        if {![dict exists $register_pins $pin]} {error "$tag UART unexpected console FF clock pin $pin"}
        dict lappend register_pins $pin $object
    }
    set reference {}; set reference_name {}; set net_drivers {}
    foreach {pin expected_driver} $anchors {
        if {[dict exists $register_pins $pin]} {
            set object [dict get $register_pins $pin]
        } else {
            set pattern [regsub -all {[][{}().+*?^$|\\]} $pin {\\&}]
            set object [get_pins -quiet -hierarchical -regexp "^${pattern}$"]
        }
        if {[llength $object]!=1 || [get_property NAME $object] ne $pin} {
            error "$tag UART missing exact clock pin $pin; found=$object"
        }
        set clocks [get_clocks -quiet -of_objects $object]
        set actual [native_dynamic_clock_summary $clocks]
        if {[llength $clocks]!=1 || ![string is double -strict [get_property PERIOD $clocks]] ||
            abs([get_property PERIOD $clocks]-20.0)>0.002} {
            error "$tag UART expected unique 20 ns clock at $pin; actual=$actual"
        }
        if {$reference eq ""} {
            set reference $clocks; set reference_name [get_property NAME $clocks]
        }
        if {[get_property NAME $clocks] ne $reference_name ||
            [get_property SOURCE_PINS $clocks] ne "u_clk_wiz/inst/mmcme4_adv_inst/CLKOUT0" ||
            [get_property MASTER_CLOCK $clocks] ne [get_property MASTER_CLOCK $reference]} {
            error "$tag UART wrong AON clock at $pin; actual=$actual expected=$reference_name source=[get_property SOURCE_PINS $clocks] master=[get_property MASTER_CLOCK $clocks]"
        }
        if {[get_property IS_INVERTED $object] ni {0 FALSE false}} {
            error "$tag UART inverted/unknown clock pin $pin; actual=$actual"
        }
        set nets [get_nets -quiet -segments -of_objects $object]
        set drivers {}
        if {[llength $nets]} {
            # Share only the leaf-driver query for the exact complete segment
            # collection. Each pin still proves its own clocks and net binding;
            # no result survives this invocation or aliases a partial net set.
            set net_key [lsort $nets]
            if {![dict exists $net_drivers $net_key]} {
                foreach driver [get_pins -quiet -leaf -of_objects $nets -filter {DIRECTION == OUT}] {
                    lappend drivers [get_property NAME $driver]
                }
                dict set net_drivers $net_key [lsort -unique $drivers]
            }
            set drivers [dict get $net_drivers $net_key]
        }
        if {$drivers ne [list $expected_driver]} {
            error "$tag UART wrong physical clock driver at $pin; actual=$drivers expected=$expected_driver clock=$actual"
        }
    }
    set ui_pin [get_pins -quiet u_ddr/c0_ddr4_ui_clk]
    set ui [get_clocks -quiet -of_objects $ui_pin]
    if {[llength $ui_pin]!=1 || [get_property NAME $ui_pin] ne "u_ddr/c0_ddr4_ui_clk" ||
        [llength $ui]!=1 || ![string is double -strict [get_property PERIOD $ui]] || abs([get_property PERIOD $ui]-4.0)>0.002} {
        error "$tag UART missing exact UI250 master; actual=[native_dynamic_clock_summary $ui]"
    }
    set ancestor $reference; set visited {}
    while {[get_property NAME $ancestor] ne [get_property NAME $ui]} {
        set name [get_property NAME $ancestor]
        if {[lsearch -exact $visited $name]>=0} {error "$tag UART fixed master cycle at $name; clock=[native_dynamic_clock_summary $reference]"}
        lappend visited $name
        set parent [get_property MASTER_CLOCK $ancestor]
        if {[llength $parent]!=1} {error "$tag UART fixed clock lost UI master at $name; actual=[native_dynamic_clock_summary $ancestor] master=$parent"}
        set ancestor [get_clocks -quiet $parent]
        if {[llength $ancestor]!=1} {error "$tag UART missing fixed master $parent; actual=[native_dynamic_clock_summary $ancestor]"}
    }
    puts "$tag UART50_FUNCTIONAL_CLOCKS_PASS CLOCK=$reference_name PERIOD_NS=20 CONSOLE_FF_CLOCK_PINS=[llength $registers] INDIVIDUAL_CLOCK_AND_DRIVER_CHECKS"
}

proc native_dynamic_performance_targets {} {
    set source [get_pins -quiet u_ddr/c0_ddr4_ui_clk]
    set masters [get_clocks -quiet -of_objects $source]
    if {[llength $source]!=1 || [llength $masters]!=1 || abs([get_property PERIOD $masters]-4.0)>0.002} {
        error "DYNAMIC_TARGET missing exact UI250 master; actual=[native_dynamic_clock_summary $masters]"
    }
    foreach {root name period} {cpu_clock cpu_target300 3.333333333333 fabric_clock fabric_target250 4.0} {
        foreach pin [list $root/mmcm/CLKOUT0 $root/managed_buffer/O] {
            set clocks [get_clocks -quiet -of_objects [get_pins -quiet $pin]]
            if {[llength $clocks]!=1 || [get_property NAME $clocks] ne $name ||
                abs([get_property PERIOD $clocks]-$period)>0.002 ||
                [get_property MASTER_CLOCK $clocks] ne [get_property NAME $masters]} {
                error "DYNAMIC_TARGET missing or relaxed pre-synthesis target $pin; actual=[native_dynamic_clock_summary $clocks] expected=${name}(period=$period)"
            }
        }
    }
    # These clocks are checked, not recreated or regrouped. Preserve the fixed
    # peripheral rates and their UI-rooted master relationships.
    foreach {pin period} {
        u_ddr/c0_ddr4_ui_clk 4.0 u_clk_wiz/clk_out1 20.0
        u_soc/alwaysOnClock 20.0
        u_soc/ddrClock 4.0 u_soc/fixedTimer/timer/clock 4.0 u_soc/debugSequence/boundary/crossing/requests/sourceClock 4.0
        network_clock/tx_source 8.0 network_clock/tx_pad_source 4.0 network_clock/delay_source 2.0
    } {
        set clocks [get_clocks -quiet -of_objects [get_pins -quiet $pin]]
        if {[llength $clocks]!=1 || abs([get_property PERIOD $clocks]-$period)>0.002} {
            error "DYNAMIC_TARGET fixed clock changed $pin; actual=[native_dynamic_clock_summary $clocks] expected_period=$period"
        }
        set ancestor $clocks;set visited {}
        while {[get_property NAME $ancestor] ne [get_property NAME $masters]} {
            set name [get_property NAME $ancestor]
            if {[lsearch -exact $visited $name]>=0} {error "DYNAMIC_TARGET fixed master cycle $pin; actual=[native_dynamic_clock_summary $clocks] ancestor=$name"}
            lappend visited $name
            set parent [get_property MASTER_CLOCK $ancestor]
            if {[llength $parent]!=1} {error "DYNAMIC_TARGET fixed clock lost UI master $pin; actual=[native_dynamic_clock_summary $clocks] ancestor=$name master=$parent"}
            set ancestor [get_clocks -quiet $parent]
            if {[llength $ancestor]!=1} {error "DYNAMIC_TARGET missing fixed master $pin; actual=[native_dynamic_clock_summary $clocks] master=$parent"}
        }
    }
    native_fixed_uart_clock_check
    report_clocks -file dynamic-performance-target-clocks.rpt
    puts "DYNAMIC_TARGET_CPU300_FABRIC250 PRE_SYNTH_REQUIREMENTS NOT_ACTUAL_RUNTIME_RATES NO_BITSTREAM"
}
