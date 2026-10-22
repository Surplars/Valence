# Exact additional dynamic-backend CDC endpoints only. No blanket asynchronous
# clock group and no false-path to CE, DRP, owner resets or architectural state.
# The default50 generated clocks do not establish the unchanged300/250 targets.
proc native_dynamic_exact {command name} {
    set quoted [regsub -all {[][{}().+*?^$|\\]} $name {\\&}]
    set result [$command -quiet -hierarchical -regexp "^${quoted}$"]
    if {[llength $result]!=1 || [get_property NAME $result] ne $name} {
        error "DYNAMIC_CLOCK missing exact object $name"
    }
    return $result
}
proc native_dynamic_clock_constraints {} {
    set bootEvidence {}
    set uiClock [get_clocks -quiet -of_objects [get_pins -quiet u_ddr/c0_ddr4_ui_clk]]
    if {[llength $uiClock]!=1 || abs([get_property PERIOD $uiClock]-4.0)>0.002} {
        error "DYNAMIC_CLOCK missing boot configuration UI250 reference"
    }
    foreach root {cpu_clock fabric_clock} {
        set mmcm [get_cells -quiet $root/mmcm]
        if {[llength $mmcm]!=1 || [get_property REF_NAME $mmcm] ne "MMCME4_ADV"} {
            error "DYNAMIC_CLOCK missing exact MMCME4 $root"
        }
        foreach {attribute expected} {DIVCLK_DIVIDE 10 CLKFBOUT_MULT_F 40.000 CLKOUT0_DIVIDE_F 20.000} {
            set actual [get_property $attribute $mmcm]
            if {![string is double -strict $actual] || abs($actual-$expected)>0.0001} {
                error "DYNAMIC_CLOCK unexpected boot primitive $root $attribute=$actual"
            }
        }
        set inputClock [get_clocks -quiet -of_objects [get_pins -quiet $root/mmcm/CLKIN1]]
        if {[llength $inputClock]!=1 || [get_property NAME $inputClock] ne [get_property NAME $uiClock]} {
            error "DYNAMIC_CLOCK MMCM input is not the unchanged UI250 master"
        }
        lappend bootEvidence "$root INITIAL_PARAMETER_FREQUENCY=50000000 D=10 M=40 O=20 UI_PERIOD_NS=4.0 NOT_A_RUNTIME_MEASUREMENT NOT_THE_STA_TARGET"
        set gate [get_cells -quiet $root/managed_buffer]
        if {[llength $gate]!=1 || [get_property REF_NAME $gate] ne "BUFGCE" || [get_property CE_TYPE $gate] ne "SYNC"} {
            error "DYNAMIC_CLOCK unreviewed gate primitive $root"
        }
        foreach chain {gate/enable_sync gate/token_sync gate/closed_sync gate/token_ack_sync gate/open_sync gate/resumed_sync lock_sync} {
            set stages {}
            for {set n 0} {$n<3} {incr n} {
                set name [format {%s/%s_reg[%d]} $root $chain $n]
                set cell [native_dynamic_exact get_cells $name]
                if {[llength $cell]!=1 || [get_property ASYNC_REG $cell] ni {1 TRUE true}} {
                    error "DYNAMIC_CLOCK missing synchronizer $name"
                }
                lappend stages $cell
            }
            set endpoint [native_dynamic_exact get_pins [lindex $stages 0]/D]
            if {$chain eq "lock_sync"} {
                set starts [get_pins -quiet $root/mmcm/LOCKED]
            } else {
                set starts [filter [all_fanin -flat -startpoints_only -to $endpoint] {REF_PIN_NAME == C || REF_PIN_NAME == CLK}]
            }
            if {![llength $starts] || [llength $endpoint]!=1} {error "DYNAMIC_CLOCK missing bounded CDC $root/$chain"}
            # Conservative fastest retained CPU300 period, not relaxed boot50.
            set_max_delay -datapath_only 3.333 -from $starts -to $endpoint
        }
        # Real half-cycle source-FF -> BUFGCE CE path must exist and remain timed.
        set ce [get_pins -quiet $root/managed_buffer/CE]
        set ce_source [get_pins -quiet $root/gate/ce_reg/Q]
        if {[llength $ce]!=1 || [llength $ce_source]!=1} {error "DYNAMIC_CLOCK missing actual CE path"}
        set paths [get_timing_paths -from $ce_source -to $ce -max_paths 1]
        if {[llength $paths]!=1} {error "DYNAMIC_CLOCK CE timing path absent or excepted"}
        report_timing -from $ce_source -to $ce -delay_type min_max -max_paths 2 -file $root-ce-timing.rpt
    }
    set file [open dynamic-boot-parameters.txt w]
    puts $file [join $bootEvidence \n];close $file
    puts "DYNAMIC_CLOCK_SCOPED_CDC_ONLY NATIVE_AND_ROUTED_QUALIFICATION_REQUIRED"
}
