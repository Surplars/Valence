# Ephemeral read-only collect queries. No proof result or cross-stage cache.
# Raw native commands and all their options are preserved. This is a candidate,
# not a native performance qualification or a replacement for timing analysis.
if {[info exists ::common_collect_session::active] && $::common_collect_session::active} {
    ::common_collect_session::reject "cannot re-source helper during active collect"
}
namespace eval common_collect_session {
    variable enabled
    if {![info exists enabled]} {set enabled 1}
    variable active 0
    variable properties {}
    variable kinds {}
    variable ambiguous {}
    variable queries {}
    variable counters {}
    variable phases {}
    variable phaseStarts {}
    variable last {}
    variable guarded {}
    variable poisoned {}
}
proc common_collect_session::tick {} {return [::clock clicks -microseconds]}
proc common_collect_session::native {command args} {
    variable active; variable counters
    if {!$active} {return [uplevel 1 [list ::$command {*}$args]]}
    set start [tick]
    try {return [uplevel 1 [list ::$command {*}$args]]} finally {
        dict incr counters ${command}.calls
        dict incr counters ${command}.us [expr {[tick]-$start}]
    }
}
proc common_collect_session::forbid {command operation} {
    variable poisoned
    set poisoned "COMMON_COLLECT mutation during read-only collect: [lindex $command 0]"
    error $poisoned
}
proc common_collect_session::reject {message} {
    variable poisoned
    set poisoned "COMMON_COLLECT $message"
    error $poisoned
}
proc common_collect_session::remember {kind objects} {
    variable kinds; variable ambiguous
    foreach object $objects {
        if {[dict exists $kinds $object] && [dict get $kinds $object] ne $kind} {
            # Different native object classes may share a printed name. Never
            # reuse by that string thereafter; original typed objects go native.
            dict set ambiguous $object 1
        } else {dict set kinds $object $kind}
    }
}
proc common_collect_session::property {args} {
    variable active; variable enabled; variable properties; variable ambiguous; variable counters
    if {!$active || !$enabled || [llength $args]!=2} {return [native get_property {*}$args]}
    lassign $args key objects
    if {$key eq {CLASS} && [llength $objects]} {
        # Keep native object-type validation, including objects supplied by the
        # pre-existing lookup cache. Printed cell/pin/net names can coincide.
        set raw [native get_property CLASS $objects]
        set types $raw
        if {[llength $objects]==1} {set types [list $raw]}
        if {[llength $types]!=[llength $objects]} {reject "malformed bulk CLASS"}
        foreach object $objects type $types {remember $type [list $object]}
        return $raw
    }
    # Only immutable properties used by the structural checker. Timing values
    # are deliberately not cached, even if a caller asks during collection.
    if {$key ni {NAME CLASS REF_NAME IS_PRIMITIVE INIT ASYNC_REG IS_INVERTED TYPE DIRECTION IS_LEAF REF_PIN_NAME PERIOD CLKFBOUT_MULT DIVCLK_DIVIDE CLKOUT0_DIVIDE} || ![llength $objects]} {
        return [native get_property {*}$args]
    }
    foreach object $objects {
        if {[dict exists $ambiguous $object]} {return [native get_property {*}$args]}
    }
    set missing {}; set seen {}
    foreach object $objects {
        if {![dict exists $properties $key $object] && ![dict exists $seen $object]} {
            dict set seen $object 1; lappend missing $object
        }
    }
    if {[llength $missing]} {
        set values [native get_property $key $missing]
        if {[llength $missing]==1} {set values [list $values]}
        if {[llength $values]!=[llength $missing]} {reject "malformed bulk property $key: objects=[llength $missing] values=[llength $values]"}
        foreach object $missing value $values {dict set properties $key $object $value}
    }
    set values {}
    foreach object $objects {
        lappend values [dict get $properties $key $object]
        dict incr counters property.values
    }
    dict incr counters property.reused [expr {[llength $objects]-[llength $missing]}]
    if {[llength $objects]==1} {return [lindex $values 0]}
    return $values
}
proc common_collect_session::query {command args} {
    variable active; variable enabled; variable queries; variable counters
    if {!$active || !$enabled} {return [native $command {*}$args]}
    # Complete argument identity retains -quiet, endpoint/NET identity,
    # -trace_arcs, -startpoints_only and hierarchy options. No union queries.
    set targetClasses {}
    if {$command in {get_clocks all_fanin}} {
        set option [expr {$command eq {get_clocks} ? {-of_objects} : {-to}}]
        set pos [lsearch -exact $args $option]
        if {$pos>=0 && $pos+1<[llength $args]} {
            set targets [lindex $args [expr {$pos+1}]]
            if {[llength $targets]} {set targetClasses [property CLASS $targets]}
        }
    }
    set key [list $command $args $targetClasses]
    if {$command in {get_clocks all_fanin} && [dict exists $queries $key]} {
        dict incr counters ${command}.hits
        return [dict get $queries $key]
    }
    set result [native $command {*}$args]
    switch $command {
        get_cells {
            remember cell $result
            if {[llength $result]} {
                foreach key {NAME CLASS REF_NAME} {
                    set values [property $key $result]
                    if {[llength $result]==1} {set values [list $values]}
                    foreach object $result value $values {
                        if {$key eq {NAME} && $value ne $object} {reject "bulk cell NAME order/identity mismatch"}
                        if {$key eq {CLASS} && $value ne {cell}} {reject "non-cell in native get_cells collection"}
                    }
                }
            }
        }
        get_pins {remember pin $result}
        get_nets {remember net $result}
        get_clocks {remember clock $result}
        all_fanin {
            # Native cones can contain ports as well as pins. Record real
            # classes rather than assuming every returned object is a pin.
            if {[llength $result]} {
                set types [native get_property CLASS $result]
                if {[llength $result]==1} {set types [list $types]}
                if {[llength $types]!=[llength $result]} {reject "malformed native cone classes"}
                foreach object $result type $types {remember $type [list $object]}
            }
        }
    }
    if {$command in {get_clocks all_fanin}} {dict set queries $key $result}
    return $result
}
proc common_collect_session::phase {stage event detail} {
    variable active; variable phaseStarts; variable phases
    if {!$active} {return}
    if {$event eq {BEGIN}} {dict set phaseStarts $stage [list [tick] $detail]}
    if {$event in {COMPLETE FAILED} && [dict exists $phaseStarts $stage]} {
        lassign [dict get $phaseStarts $stage] start original
        lappend phases [list stage $stage detail $original final_detail $detail outcome $event us [expr {[tick]-$start}]]
        dict unset phaseStarts $stage
    }
}
proc common_collect_session::run {script} {
    variable active; variable properties; variable kinds; variable ambiguous; variable queries
    variable counters; variable phases; variable phaseStarts; variable last; variable guarded; variable poisoned
    if {$active} {error "COMMON_COLLECT nested lifecycle is forbidden"}
    set properties {}; set kinds {}; set ambiguous {}; set queries {}; set counters {}
    set phases {}; set phaseStarts {}; set guarded {}; set poisoned {}
    set active 1; set start [tick]; set outcome ERROR
    try {
        # Refuse mutation BEFORE it executes. A caught mutation still poisons
        # the entire collect, so callers cannot catch it and publish old scopes.
        foreach command {open_checkpoint open_run open_design close_design close_project read_checkpoint update_design link_design synth_design opt_design place_design phys_opt_design route_design read_verilog read_edif read_xdc read_ip create_cell create_net create_port connect_net disconnect_net remove_cell remove_net remove_port set_property reset_property create_clock create_generated_clock delete_clocks set_clock_groups set_clock_uncertainty set_clock_latency set_clock_transition set_input_delay set_output_delay set_max_delay set_min_delay set_false_path set_multicycle_path set_bus_skew set_case_analysis set_disable_timing reset_timing update_timing} {
            if {[llength [info commands ::$command]]} {
                trace add execution ::$command enter ::common_collect_session::forbid
                lappend guarded $command
            }
        }
        set result [uplevel 1 $script]
        if {$poisoned ne {}} {error $poisoned}
        set outcome COMPLETE
        return $result
    } finally {
        foreach command $guarded {trace remove execution ::$command enter ::common_collect_session::forbid}
        set last [dict create outcome $outcome elapsed_us [expr {[tick]-$start}] api $counters phases $phases incomplete_phases [dict keys $phaseStarts]]
        set active 0; set properties {}; set kinds {}; set ambiguous {}; set queries {}; set guarded {}
        puts [list COMMON_COLLECT_METRICS $last NATIVE_PERFORMANCE_UNQUALIFIED]
        flush stdout
    }
}
# Namespace-local adapters leave Vivado's global commands unchanged. The exact
# object cache and inactive-state helper share this one collect lifetime only.
foreach ns {common_cdc common_exact_cache common_zero} {
    namespace eval ::$ns {}
    proc ::${ns}::get_property {args} {return [::common_collect_session::property {*}$args]}
    foreach command {get_cells get_pins get_nets get_clocks all_fanin all_fanout} {
        proc ::${ns}::$command {args} [format {return [::common_collect_session::query %s {*}$args]} $command]
    }
}
