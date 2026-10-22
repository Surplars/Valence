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
# LOCKED is asynchronous status, not a sequential launch clock. A max-delay
# -from LOCKED segments the path and does not establish a synchronous 3.333 ns
# bound. Do not remove -from while keeping -datapath_only (UG835 requires it):
# https://docs.amd.com/r/2025.2-English/ug835-vivado-tcl-commands/set_max_delay
# These helpers deliberately do not depend on common_cdc.tcl being loaded.
namespace eval native_dynamic_lock {}
proc native_dynamic_lock::require {condition reason} {
    if {![uplevel 1 [list expr $condition]]} {error "DYNAMIC_LOCK $reason"}
}
proc native_dynamic_lock::names {objects} {
    set result {}; foreach object $objects {lappend result [get_property NAME $object]}
    return [lsort -unique $result]
}
proc native_dynamic_lock::pin {name direction refpin {noninverted 1}} {
    set pin [native_dynamic_exact get_pins $name]
    require {[get_property DIRECTION $pin] eq $direction &&
        [get_property REF_PIN_NAME $pin] eq $refpin} "wrong pin identity $name"
    if {$noninverted} {
        require {[get_property IS_INVERTED $pin] in {0 false FALSE}} "inverted/unknown pin $name"
    }
    return $pin
}
proc native_dynamic_lock::connections {name direction} {
    set pin [native_dynamic_exact get_pins $name]
    set nets [get_nets -quiet -segments -of_objects $pin]
    require {[llength $nets] > 0} "floating pin $name"
    return [names [get_pins -quiet -leaf -of_objects $nets -filter "DIRECTION == $direction"]]
}
proc native_dynamic_lock::clock {name} {
    set clocks [get_clocks -quiet -of_objects [native_dynamic_exact get_pins $name]]
    require {[llength $clocks] == 1} "missing/ambiguous clock $name"
    return [get_property NAME $clocks]
}
proc native_dynamic_lock::enabled {cell} {
    set nets [get_nets -quiet -segments -of_objects [pin $cell/CE IN CE]]
    require {[llength $nets] > 0} "floating enable $cell"
    foreach net $nets {require {[get_property TYPE $net] eq "POWER"} "enable is not constant one $cell"}
}
proc native_dynamic_lock::finite {value} {
    if {![string is double -strict $value]} {return 0}
    if {[catch {expr {$value > -Inf && $value < Inf}} result]} {return 0}
    return $result
}
proc native_dynamic_lock::interstage {stages aon} {
    set evidence {}
    for {set i 1} {$i < 3} {incr i} {
        set previous [lindex $stages [expr {$i - 1}]]; set next [lindex $stages $i]
        foreach kind {max min} {
            set start [pin $previous/C IN C]; set end [pin $next/D IN D]
            set paths [get_timing_paths -quiet -from $start -to $end -delay_type $kind -max_paths 1]
            require {[llength $paths] == 1} "missing/excepted interstage $kind $previous -> $next"
            set requirement [get_property REQUIREMENT $paths]; set slack [get_property SLACK $paths]
            require {[finite $requirement] && [finite $slack]} "nonfinite interstage $kind $previous -> $next"
            require {[get_property STARTPOINT_PIN $paths] eq "$previous/C" &&
                [get_property ENDPOINT_PIN $paths] eq "$next/D"} "wrong interstage endpoints $kind $next"
            require {[get_property STARTPOINT_CLOCK $paths] eq $aon &&
                [get_property ENDPOINT_CLOCK $paths] eq $aon} "wrong interstage timing clock $kind $next"
            set exception [string tolower [string trim [get_property EXCEPTION $paths]]]
            require {$exception in {{} none}} "interstage exception $kind $next: $exception"
            set expected [expr {$kind eq "max" ? 20.0 : 0.0}]
            require {abs($requirement - $expected) < 0.002} "changed interstage requirement $kind $next: $requirement"
            # A diagnostic measurement may have negative slack. Preserve and
            # report it; finite normal timing is not a claim that timing passes.
            lappend evidence "$previous/C->$next/D $kind requirement=$requirement slack=$slack"
        }
    }
    return $evidence
}
proc native_dynamic_lock::constrain {root} {
    require {$root in {cpu_clock fabric_clock}} "unreviewed root $root"
    set mmcm [native_dynamic_exact get_cells $root/mmcm]
    require {[get_property REF_NAME $mmcm] eq "MMCME4_ADV"} "unreviewed LOCKED primitive $root"
    set locked [pin $root/mmcm/LOCKED OUT LOCKED 0]
    require {![llength [get_clocks -quiet -of_objects $locked]]} "LOCKED has unexpected launch clock $root"
    set aon [clock u_clk_wiz/clk_out1]
    set period [get_property PERIOD [get_clocks -quiet $aon]]
    require {[finite $period] && abs($period - 20.0) < 0.002} "AON clock is not 50 MHz $root"
    set stages {}
    for {set i 0} {$i < 3} {incr i} {lappend stages [format {%s/lock_sync_reg[%d]} $root $i]}
    set pattern [format {^%s/lock_sync_reg\[[0-9]+\]$} $root]
    require {[names [get_cells -quiet -hierarchical -regexp $pattern]] eq [lsort $stages]} "lock_sync stage census changed $root"
    set reset [format {%s/aon_reset_pipe_reg[2]} $root]
    set reset_cell [native_dynamic_exact get_cells $reset]
    require {[get_property REF_NAME $reset_cell] eq "FDPE" &&
        [get_property ASYNC_REG $reset_cell] in {1 true TRUE} &&
        [string tolower [get_property INIT $reset_cell]] in {1 1'b1 1'h1 0x1}} "unreviewed local reset source $reset"
    pin $reset/Q OUT Q 0
    foreach refpin {C D CE PRE} {pin $reset/$refpin IN $refpin}
    enabled $reset
    require {[clock $reset/C] eq $aon} "reset source not AON clocked $reset"
    foreach cell $stages {
        set object [native_dynamic_exact get_cells $cell]
        require {[get_property REF_NAME $object] eq "FDCE" &&
            [get_property ASYNC_REG $object] in {1 true TRUE} &&
            [string tolower [get_property INIT $object]] in {0 1'b0 1'h0 0x0}} "unreviewed zero-reset synchronizer $cell"
        foreach refpin {C D CE CLR} {pin $cell/$refpin IN $refpin}
        pin $cell/Q OUT Q 0
        enabled $cell
        require {[clock $cell/C] eq $aon} "wrong synchronizer clock $cell"
        require {[connections $cell/CLR OUT] eq [list $reset/Q]} "wrong/shared reset driver $cell"
    }
    set first [lindex $stages 0]
    require {[connections $first/D OUT] eq [list $root/mmcm/LOCKED]} "LOCKED is not unique direct first-stage driver $root"
    require {[connections $root/mmcm/LOCKED IN] eq [list $first/D]} "LOCKED leaf fanout changed $root"
    for {set i 1} {$i < 3} {incr i} {
        set previous [lindex $stages [expr {$i - 1}]]; set next [lindex $stages $i]
        require {[connections $next/D OUT] eq [list $previous/Q]} "non-direct interstage $next"
        require {[connections $previous/Q IN] eq [list $next/D]} "early synchronizer fanout changed $previous"
    }
    # Validate before and after the exact first-D-only exception. No reset/CE,
    # later D, whole-cell, clock-group, -through or fabricated -from exception.
    interstage $stages $aon
    set_false_path -to [pin $first/D IN D]
    set timing [interstage $stages $aon]
    set evidence "DYNAMIC_LOCK_ASYNC_FIRST_D_ONLY root=$root source=$locked destination=$first/D clock=$aon reset=$reset/Q NO_LEGITIMATE_SYNCHRONOUS_LOCKED_LAUNCH OLD_LOCKED_3.333_NOT_A_VALID_BOUND INTERSTAGE_NORMALLY_TIMED_NOT_SIGNOFF"
    puts $evidence
    foreach row $timing {puts "DYNAMIC_LOCK_INTERSTAGE root=$root $row"}
    return $evidence
}

# The UI buffer feeds independent CPU/fabric/AON MMCMs and the network PLL.
# UltraScale+ SAME_CMT_COLUMN keeps dedicated global routing while permitting
# non-adjacent CMT rows. Never substitute FALSE or import the legacy board XDC.
# Native placed/routed evidence used this exact MIG buffer output successfully.
proc native_dynamic_ui_route {} {
    set name u_ddr/inst/u_ddr4_infrastructure/u_bufg_divClk
    set buffer [get_cells -quiet $name]
    set pin [get_pins -quiet $name/O]
    if {[llength $buffer]!=1 || [get_property NAME $buffer] ne $name ||
        [get_property REF_NAME $buffer] ne "BUFGCE" || [llength $pin]!=1 ||
        [get_property NAME $pin] ne "$name/O" || [get_property DIRECTION $pin] ne "OUT"} {
        error "DYNAMIC_CLOCK missing exact MIG UI BUFGCE output"
    }
    set net [get_nets -quiet -of_objects $pin]
    if {[llength $net]!=1} {error "DYNAMIC_CLOCK missing unique MIG UI buffer output net"}
    set prior [get_property CLOCK_DEDICATED_ROUTE $net]
    if {$prior ni {{} TRUE SAME_CMT_COLUMN}} {error "DYNAMIC_CLOCK unexpected UI routing policy $prior"}
    set_property CLOCK_DEDICATED_ROUTE SAME_CMT_COLUMN $net
    if {[get_property CLOCK_DEDICATED_ROUTE $net] ne "SAME_CMT_COLUMN"} {error "DYNAMIC_CLOCK UI dedicated routing property not retained"}
    puts "DYNAMIC_CLOCK_UI_SAME_CMT_COLUMN net=[get_property NAME $net] source=$name/O DEDICATED_ONLY NOT_TIMING_SIGNOFF"
}

proc native_dynamic_clock_constraints {} {
    set bootEvidence {}
    set uiClock [get_clocks -quiet -of_objects [get_pins -quiet u_ddr/c0_ddr4_ui_clk]]
    if {[llength $uiClock]!=1 || abs([get_property PERIOD $uiClock]-4.0)>0.002} {
        error "DYNAMIC_CLOCK missing boot configuration UI250 reference"
    }
    native_dynamic_ui_route
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
                lappend bootEvidence [native_dynamic_lock::constrain $root]
                continue
            }
            set starts [filter [all_fanin -flat -startpoints_only -to $endpoint] {REF_PIN_NAME == C || REF_PIN_NAME == CLK}]
            if {![llength $starts] || [llength $endpoint]!=1} {error "DYNAMIC_CLOCK missing bounded CDC $root/$chain"}
            # Conservative fastest retained CPU300 period, not relaxed boot50.
            set_max_delay -datapath_only 3.333 -from $starts -to $endpoint
        }
        # Real rising-edge source-FF -> BUFGCE CE path must remain timed.
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
