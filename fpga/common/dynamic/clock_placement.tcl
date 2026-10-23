# Pre-place physical candidate for the rising-edge CE implementation.
# UG949: Controlling and Synchronizing Device Startup; CLOCK_LOW_FANOUT.
# https://docs.amd.com/r/2025.2-English/ug949-vivado-design-methodology/Controlling-and-Synchronizing-Device-Startup
# https://docs.amd.com/r/2025.2-English/ug949-vivado-design-methodology/Using-the-CLOCK_LOW_FANOUT-Constraint
# Keep high-fanout managed+feedback trees balanced, but let the placer choose
# their root. Contain only the separate observer's small clock-control load.
# No clock definitions, LOCs, USER_CLOCK_ROOT, timing exceptions or RTL changes.
namespace eval native_dynamic_placement {}
proc native_dynamic_placement::one {command name} {
    set object [$command -quiet $name]
    if {[llength $object]!=1 || [get_property NAME $object] ne $name} {
        error "DYNAMIC_PLACEMENT missing exact $command $name"
    }
    return $object
}
proc native_dynamic_placement::net {name} {
    set object [get_nets -quiet -of_objects [one get_pins $name]]
    if {[llength $object]!=1} {error "DYNAMIC_PLACEMENT missing unique net $name"}
    return $object
}
proc native_dynamic_placement::driver {name expected} {
    set segments [get_nets -quiet -segments -of_objects [one get_pins $name]]
    set drivers [get_pins -quiet -leaf -of_objects $segments -filter {DIRECTION == OUT}]
    if {[llength $drivers]!=1 || [get_property NAME $drivers] ne $expected} {
        error "DYNAMIC_PLACEMENT wrong direct driver $name expected=$expected"
    }
}
proc native_dynamic_placement::inspect {} {
    set plan {}
    foreach {lane target period} {cpu_clock cpu_target300 3.333333333333 fabric_clock fabric_target250 4.0} {
        set mmcm [one get_cells $lane/mmcm]
        if {[get_property REF_NAME $mmcm] ne "MMCME4_ADV"} {error "DYNAMIC_PLACEMENT wrong MMCM $lane"}
        set nets {}
        foreach role {observer managed feedback} {
            set cell [one get_cells $lane/${role}_buffer]
            if {[get_property REF_NAME $cell] ne "BUFGCE"} {error "DYNAMIC_PLACEMENT wrong buffer $cell"}
            set input [one get_pins $lane/${role}_buffer/I]
            if {[get_property IS_INVERTED $input] ni {0 false FALSE}} {error "DYNAMIC_PLACEMENT inverted clock input $cell"}
            set source [expr {$role eq "feedback" ? "CLKFBOUT" : "CLKOUT0"}]
            driver $lane/${role}_buffer/I $lane/mmcm/$source
            set output [one get_pins $lane/${role}_buffer/O]
            set net [net $lane/${role}_buffer/O]
            driver $lane/${role}_buffer/O $lane/${role}_buffer/O
            if {$role ne "feedback"} {
                set clocks [get_clocks -quiet -of_objects $output]
                if {[llength $clocks]!=1 || [get_property NAME $clocks] ne $target ||
                    abs([get_property PERIOD $clocks]-$period)>0.002} {
                    error "DYNAMIC_PLACEMENT wrong unchanged performance target $cell"
                }
            }
            set group [get_property CLOCK_DELAY_GROUP $net]
            set desired [expr {$role eq "observer" ? "" : "valence_${lane}_managed_feedback"}]
            if {$group ne "" && $group ne $desired} {error "DYNAMIC_PLACEMENT conflicting existing group $cell"}
            # Never silently adopt/clear the previous all-local routed ECO.
            if {[get_property USER_CLOCK_ROOT $net] ne ""} {error "DYNAMIC_PLACEMENT pre-existing forced root $cell"}
            if {[get_property CLOCK_DEDICATED_ROUTE $net] ni {{} TRUE}} {error "DYNAMIC_PLACEMENT conflicting dedicated-route policy $cell"}
            set low [get_property CLOCK_LOW_FANOUT $net]
            if {($role eq "observer" && $low ni {{} 0 false FALSE 1 true TRUE}) ||
                ($role ne "observer" && $low ni {{} 0 false FALSE})} {
                error "DYNAMIC_PLACEMENT conflicting low-fanout policy $cell"
            }
            dict set nets $role $net
        }
        if {[llength [lsort -unique [dict values $nets]]]!=3} {error "DYNAMIC_PLACEMENT aliased buffer outputs $lane"}
        if {[get_property CE_TYPE [one get_cells $lane/managed_buffer]] ne "SYNC"} {
            error "DYNAMIC_PLACEMENT managed CE is not SYNC $lane"
        }
        driver $lane/mmcm/CLKFBIN $lane/feedback_buffer/O
        driver $lane/managed_buffer/CE $lane/gate/ce_reg/Q
        driver $lane/gate/ce_reg/C $lane/observer_buffer/O
        if {[get_property IS_INVERTED [one get_pins $lane/gate/ce_reg/C]] ni {0 false FALSE}} {
            error "DYNAMIC_PLACEMENT requires rising-edge CE source $lane"
        }
        set segments [get_nets -quiet -segments -of_objects [one get_pins $lane/observer_buffer/O]]
        set loads [get_pins -quiet -leaf -of_objects $segments -filter {DIRECTION == IN}]
        set names [get_property NAME $loads]; set refs [get_property REF_PIN_NAME $loads]
        if {[llength $loads]<1 || [llength $loads]>=2000 || [llength $names]!=[llength $loads] ||
            [llength $refs]!=[llength $loads]} {error "DYNAMIC_PLACEMENT observer load count changed $lane"}
        foreach name $names ref $refs {
            if {![string match $lane/gate/* $name] || $ref ne "C"} {
                error "DYNAMIC_PLACEMENT observer has non-control-clock load $name"
            }
        }
        lappend plan [list $lane $nets [llength $loads]]
    }
    return $plan
}
proc native_dynamic_placement::apply {} {
    set plan [inspect]
    # Preflight both lanes before any writes; this is exactly six net properties.
    foreach item $plan {
        lassign $item lane nets count
        set group valence_${lane}_managed_feedback
        foreach role {managed feedback} {
            set object [dict get $nets $role]
            set_property CLOCK_DELAY_GROUP $group $object
            if {[get_property CLOCK_DELAY_GROUP $object] ne $group} {error "DYNAMIC_PLACEMENT group readback failed $lane"}
        }
        set observer [dict get $nets observer]
        set_property CLOCK_LOW_FANOUT TRUE $observer
        if {[get_property CLOCK_LOW_FANOUT $observer] ni {1 true TRUE}} {error "DYNAMIC_PLACEMENT observer readback failed $lane"}
        puts "DYNAMIC_PLACEMENT_PREPLACE lane=$lane observer_loads=$count managed_feedback_group=$group NO_FORCED_ROOT NO_TIMING_EXCEPTION NATIVE_TIMING_PENDING"
    }
    return $plan
}
