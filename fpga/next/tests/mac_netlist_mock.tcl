# Synthetic Vivado query model v1. Host Tcl contract tests ONLY.
# Deliberately implements the exact command/option surface the collector uses;
# unknown switches/properties fail rather than succeeding as permissive mocks.
proc opt {args name {default {}}} {
    set i [lsearch -exact $args $name]
    if {$i<0} {return $default}; return [lindex $args [expr {$i+1}]]
}
proc check_opts {args allowed flags} {
    for {set i 0} {$i<[llength $args]} {incr i} {
        set a [lindex $args $i]
        if {[string index $a 0] ne "-"} {continue}
        if {$a ni $allowed} {error "Unsupported mock command option $a"}
        if {$a ni $flags} {incr i}
    }
}
proc get_property {key objects} {
    global MODEL
    if {[llength $objects]!=1 || ![dict exists $MODEL [lindex $objects 0] $key]} {
        error "Missing mock property $key on $objects"
    }
    return [dict get $MODEL [lindex $objects 0] $key]
}
proc mock_reindex {} {
    global MODEL INDEX
    set INDEX [dict create]
    dict for {name props} $MODEL {
        dict lappend INDEX [dict get $props KIND] $name
        if {[dict get $props KIND] eq "pin"} {
            dict lappend INDEX cellpins:[dict get $props CELL] $name
            dict lappend INDEX netpins:[dict get $props NET] $name
        }
    }
}
proc mock_select {kind args} {
    global MODEL INDEX
    check_opts $args {-quiet -hier -hierarchical -regexp -filter -of_objects -leaf} {-quiet -hier -hierarchical -regexp -leaf}
    set of [opt $args -of_objects]; set filter [opt $args -filter]
    if {$of eq "" && $filter eq "" && [lsearch -exact $args -regexp]<0} {
        set name [lindex [lindex $args end] 0]
        if {[dict exists $MODEL $name] && [dict get $MODEL $name KIND] eq $kind} {return [list $name]}
        return {}
    }
    set possible [dict get $INDEX $kind]
    if {$of ne ""} {
        set possible {}
        foreach item $of {
            set ik [dict get $MODEL $item KIND]
            if {$kind eq "cell" && $ik eq "pin"} {lappend possible [dict get $MODEL $item CELL]}
            if {$kind eq "pin" && $ik in {cell net} && [dict exists $INDEX ${ik}pins:$item]} {
                lappend possible {*}[dict get $INDEX ${ik}pins:$item]
            }
        }
    }
    set candidates {}
    foreach name [lsort -unique $possible] {
        set props [dict get $MODEL $name]
        if {[dict get $props KIND] ne $kind} {continue}
        if {[lsearch -exact $args -leaf]>=0 && ![dict get $props LEAF]} {continue}
        if {$of ne ""} {
            set include 0
            foreach item $of {
                if {$kind eq "cell" && [dict get $MODEL $item KIND] eq "pin" && [dict get $props NAME] eq [dict get $MODEL $item CELL]} {set include 1}
                if {$kind eq "pin" && [dict get $MODEL $item KIND] eq "cell" && [dict get $props CELL] eq $item} {set include 1}
                if {$kind eq "pin" && [dict get $MODEL $item KIND] eq "net" && [dict get $props NET] eq $item} {set include 1}
            }
            if {!$include} {continue}
        }
        if {$filter ne ""} {
            if {![regexp {^(REF_NAME|REF_PIN_NAME|DIRECTION) (==|=~) (.+)$} $filter ignored key op value]} {error "Unsupported mock filter: $filter"}
            if {$op eq "==" && [dict get $props $key] ne $value} {continue}
            if {$op eq "=~" && ![string match $value [dict get $props $key]]} {continue}
        }
        if {$of eq "" && $filter eq ""} {
            set pattern [lindex $args end]
            if {[lsearch -exact $args -regexp]>=0} {
                if {![regexp $pattern $name]} {continue}
            } elseif {$name ne $pattern} {continue}
        }
        lappend candidates $name
    }
    return [lsort $candidates]
}
proc get_cells {args} {return [mock_select cell {*}$args]}
proc get_pins {args} {return [mock_select pin {*}$args]}
proc get_nets {args} {
    global MODEL
    check_opts $args {-segments -of_objects -quiet} {-segments -quiet}
    set out {}; foreach pin [opt $args -of_objects] {lappend out [get_property NET $pin]}
    return [lsort -unique $out]
}
proc get_clocks {args} {
    check_opts $args {-of_objects -quiet} {-quiet}
    set out {}; set of [opt $args -of_objects]
    if {$of ne ""} {foreach pin $of {lappend out [get_property CLOCK $pin]}} else {set out [lindex $args end]}
    return [lsort -unique $out]
}
proc mock_fanin {pin seen} {
    global MODEL
    if {$pin in $seen} {return {}}; lappend seen $pin
    if {[dict exists $MODEL $pin STARTPOINTS]} {return [dict get $MODEL $pin STARTPOINTS]}
    set result {}
    foreach driver [get_pins -leaf -of_objects [get_nets -segments -of_objects $pin] -filter {DIRECTION == OUT}] {
        set cell [get_property CELL $driver]
        if {[get_property IS_SEQUENTIAL $cell]} {lappend result $driver} else {
            foreach input [get_pins -of_objects $cell -filter {DIRECTION == IN}] {lappend result {*}[mock_fanin $input $seen]}
        }
    }
    return [lsort -unique $result]
}
proc all_fanin {args} {
    check_opts $args {-flat -startpoints_only -to} {-flat -startpoints_only}
    return [mock_fanin [opt $args -to] {}]
}
proc mock_fanout {pin seen} {
    if {$pin in $seen} {return {}}; lappend seen $pin
    set result {}
    foreach load [get_pins -leaf -of_objects [get_nets -segments -of_objects $pin] -filter {DIRECTION == IN}] {
        set cell [get_property CELL $load]
        if {[get_property IS_SEQUENTIAL $cell]} {lappend result $load} else {
            foreach output [get_pins -of_objects $cell -filter {DIRECTION == OUT}] {lappend result {*}[mock_fanout $output $seen]}
        }
    }
    return [lsort -unique $result]
}
proc all_fanout {args} {
    check_opts $args {-flat -endpoints_only -from} {-flat -endpoints_only}
    return [mock_fanout [opt $args -from] {}]
}
proc get_timing_paths {args} {
    global MODEL TIMING_CALLS
    check_opts $args {-quiet -from -to -delay_type -max_paths -nworst} {-quiet}
    set end [lindex [opt $args -to] 0]; set starts [opt $args -from]; set type [opt $args -delay_type]
    if {$end eq ""} {error "Mock requires a nonempty timing endpoint scope"}
    foreach start $starts {
        if {![dict exists $MODEL $start] || [get_property REF_PIN_NAME $start] ni {C CLK WCLK}} {error "Illegal mock startpoint $start"}
    }
    lappend TIMING_CALLS [list $starts $end $type]
    if {[dict exists $MODEL $end CUT] && [dict get $MODEL $end CUT]} {return {}}
    set req [expr {$type eq "max" ? 8.0 : 0.0}]
    if {[dict exists $MODEL $end REQUIREMENT]} {set req [dict get $MODEL $end REQUIREMENT]}
    set target $end
    if {[dict exists $MODEL $end BAD_ENDPOINT]} {set target [dict get $MODEL $end BAD_ENDPOINT]}
    set slack 0.5
    if {[dict exists $MODEL $end SLACK]} {set slack [dict get $MODEL $end SLACK]}
    dict set MODEL timing_path [dict create KIND path NAME timing_path ENDPOINT_PIN $target REQUIREMENT $req SLACK $slack]
    return timing_path
}
proc mock_report {command args} {
    global REPORT_CALLS
    set switches [dict get [dict create \
        report_timing {-from -to -delay_type -max_paths -nworst -input_pins -file} \
        report_exceptions {-from -to -coverage -ignored -file} \
        report_bus_skew {-cells -max_paths -nworst -input_pins -warn_on_violation -file} \
        report_cdc {-details -file} report_clock_interaction {-file} \
        report_timing_summary {-report_unconstrained -file}] $command]
    check_opts $args $switches {-input_pins -coverage -ignored -details -report_unconstrained -warn_on_violation}
    lappend REPORT_CALLS [list $command $args]
    set f [open [opt $args -file] w]; puts $f "SYNTHETIC_MOCK_REPORT_NOT_VIVADO $command $args"; close $f
}
foreach command {report_timing report_exceptions report_bus_skew report_cdc report_clock_interaction report_timing_summary} {
    proc $command {args} "mock_report $command {*}\$args"
}
set TIMING_CALLS {}; set REPORT_CALLS {}
