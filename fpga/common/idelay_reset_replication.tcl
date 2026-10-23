# Explicit, one-shot post-place optimization. Sourcing never changes the design.
# No RTL, timing exceptions, clock properties, pin moves or manual unrouting.
namespace eval idelay_reset_replication {
    if {![info exists attempted]} {variable attempted 0}
    variable baseline
}
proc idelay_reset_replication::require {ok message} {
    if {!$ok} {error "IDELAY_RESET_REPLICATION $message"}
}
proc idelay_reset_replication::one {command args} {
    set xs [$command {*}$args]
    require [expr {[llength $xs] == 1}] "expected one $command $args; got $xs"
    return $xs
}
proc idelay_reset_replication::cell {name} {
    set c [one get_cells -hier -quiet -filter "NAME == \"$name\""]
    require [expr {[property NAME $c] eq $name}] "cell identity mismatch $name"
    return $c
}
proc idelay_reset_replication::pin {c ref} {
    return [one get_pins -quiet -of_objects $c -filter "REF_PIN_NAME == $ref"]
}
proc idelay_reset_replication::drivers {p} {
    set ns [get_nets -segments -of_objects $p]
    require [expr {[llength $ns] > 0}] "unconnected pin $p"
    return [lsort -unique [property NAME [get_pins -leaf -of_objects $ns -filter {DIRECTION == OUT}]]]
}
# IS_PLACED is not a portable mapped-cell property in Vivado 2025.2.
# Assigned LOC alone is insufficient: require actual cell-to-site/BEL binding.
proc idelay_reset_replication::property {name object} {
    set value [get_property $name $object]
    require [expr {[string trim $value] ne ""}] "empty required property $name on $object"
    return $value
}
proc idelay_reset_replication::placement {c} {
    set loc [property LOC $c]
    set bel [property BEL $c]
    set site [one get_sites -quiet -of_objects $c]
    set bound_bel [one get_bels -quiet -of_objects $c]
    require [expr {[property NAME $site] eq $loc}] "cell/site binding mismatch $c"
    # Vivado cell BEL may be type-qualified (e.g. SLICEM.CFF2), whereas
    # get_bels NAME is site-qualified (SLICE_X116Y157/CFF2).
    set parts [split $bel .]
    require [expr {[llength $parts] in {1 2}}] "malformed BEL property $c"
    set terminal [lindex $parts end]
    require [expr {$terminal ne ""}] "empty BEL terminal $c"
    if {[llength $parts] == 2 && [property REF_NAME $c] eq "FDPE"} {
        require [expr {[lindex $parts 0] in {SLICEL SLICEM}}] "unexpected FDPE BEL type $c"
    }
    require [expr {[property NAME $bound_bel] eq "$loc/$terminal"}] "cell/BEL binding mismatch $c"
    set occupant [one get_cells -quiet -of_objects $bound_bel]
    require [expr {[property NAME $occupant] eq [property NAME $c]}] "BEL occupant mismatch $c"
    return [list $loc $bel]
}
proc idelay_reset_replication::signature {c} {
    require [expr {[property REF_NAME $c] eq "FDPE"}] "reset driver is not FDPE"
    placement $c
    set result [dict create]
    dict set result INIT [property INIT $c]
    set inversion [property IS_INVERTED [pin $c C]]
    require [expr {$inversion in {0 1 false true FALSE TRUE}}] "invalid clock pin inversion"
    dict set result C_INVERTED $inversion
    foreach ref {C D PRE CE} {
        set p [pin $c $ref]
        set ds [drivers $p]
        require [expr {[llength $ds] == 1}] "ambiguous driver on $p"
        dict set result $ref $ds
    }
    set clock [one get_clocks -of_objects [pin $c C]]
    require [expr {abs([property PERIOD $clock] - 2.0) < 0.001}] "not REF500"
    dict set result clock [property NAME $clock]
    return $result
}
proc idelay_reset_replication::expected {} {
    set result [dict create]
    foreach suffix {{} _REPLICATED_0 _REPLICATED_0_1} {
        dict set result u_rgmii/delay_control${suffix} IDELAYCTRL
    }
    for {set n 0} {$n < 5} {incr n} {
        dict set result [format {u_rgmii/receive[%d].input_delay} $n] IDELAYE3
        dict set result [format {u_rgmii/receive[%d].extra_delay.output_delay} $n] ODELAYE3
    }
    return $result
}
proc idelay_reset_replication::inspect {expected_driver_signature expected_delay} {
    require [expr {$expected_delay in {450 475}}] "unsupported expected delay; select exactly 450 or 475"
    set sink_pins {}; set driver_cells {}; set identity [dict create]
    dict for {name primitive} [expected] {
        set c [cell $name]
        require [expr {[property REF_NAME $c] eq $primitive}] "wrong sink primitive $name"
        set placed [placement $c]
        set rst [pin $c RST]
        lappend sink_pins [property NAME $rst]
        dict set identity $name $placed
        if {$primitive ne "IDELAYCTRL"} {
            foreach {prop want} [list DELAY_VALUE $expected_delay DELAY_FORMAT TIME DELAY_TYPE FIXED IODELAY_GROUP VALENCE_RGMII] {
                require [expr {[property $prop $c] eq $want}] "changed $prop on $name"
            }
            require [expr {abs([property REFCLK_FREQUENCY $c]-500.0)<0.001}] "changed delay reference"
            set cascade [expr {$primitive eq "IDELAYE3" ? "MASTER" : "SLAVE_END"}]
            require [expr {[property CASCADE $c] eq $cascade}] "changed cascade $name"
        }
        set ds [drivers $rst]
        require [expr {[llength $ds] == 1}] "ambiguous reset source $rst"
        set q [one get_pins -hier -quiet -filter "NAME == \"[lindex $ds 0]\""]
        require [expr {[property REF_PIN_NAME $q] eq "Q"}] "reset not direct Q"
        set d [one get_cells -of_objects $q]
        require [expr {[signature $d] eq $expected_driver_signature}] "driver logic/reset/clock changed"
        lappend driver_cells [property NAME $d]
    }
    set driver_cells [lsort -unique $driver_cells]
    set all_loads {}
    foreach name $driver_cells {
        set q [pin [cell $name] Q]
        set ns [get_nets -segments -of_objects $q]
        foreach p [get_pins -leaf -of_objects $ns -filter {DIRECTION == IN}] {
            lappend all_loads [property NAME $p]
        }
    }
    require [expr {[lsort -unique $all_loads] eq [lsort $sink_pins]}] "reset load set is not exactly 13 reviewed RST pins"
    set rxnet [one get_nets -of_objects [pin [cell rx_clock_buffer] O]]
    set roots [list [property CLOCK_ROOT $rxnet] [property USER_CLOCK_ROOT $rxnet]]
    require [expr {$roots eq {X3Y2 X3Y2}}] "RX root changed"
    return [dict create sinks $sink_pins drivers $driver_cells identity $identity roots $roots]
}
proc idelay_reset_replication::apply {fresh_baseline_directory {expected_delay 475}} {
    variable attempted; variable baseline
    require [expr {!$attempted}] "already attempted; do not repeat or retry uncertain physical optimization"
    set guard [cell {delay_reset_guard_reg[63]}]
    set sig [signature $guard]
    require [expr {[dict get $sig D] eq {{delay_reset_guard_reg[62]/Q}}}] "guard predecessor changed"
    require [expr {[dict get $sig PRE] eq {{delay_reset_pipe_reg[2]/Q}}}] "guard reset changed"
    set baseline [inspect $sig $expected_delay]
    dict set baseline expected_delay $expected_delay
    require [expr {[dict get $baseline drivers] eq {{delay_reset_guard_reg[63]}}}] "baseline already replicated/unexpected source"
    dict set baseline signature $sig
    reports $baseline $fresh_baseline_directory
    set net [one get_nets -of_objects [pin $guard Q]]
    # Set BEFORE the mutating call: errors/uncertain outcomes cannot be retried.
    set attempted 1
    phys_opt_design -force_replication_on_nets $net
    set post [inspect $sig [dict get $baseline expected_delay]]
    require [expr {[dict get $post identity] eq [dict get $baseline identity]}] "sink LOC/BEL changed"
    dict set post status REQUIRES_ROUTE_AND_TIMING_VALIDATION
    return $post
}
proc idelay_reset_replication::postroute_reports {fresh_directory} {
    variable attempted; variable baseline
    require [expr {$attempted && [info exists baseline]}] "no same-session baseline"
    require [expr {![file exists $fresh_directory]}] "output directory already exists"
    set post [inspect [dict get $baseline signature] [dict get $baseline expected_delay]]
    require [expr {[dict get $post identity] eq [dict get $baseline identity]}] "sink LOC/BEL changed"
    reports $post $fresh_directory
    dict set post status REPORTS_ONLY_NOT_SIGNOFF
    return $post
}
proc idelay_reset_replication::reports {post fresh_directory} {
    require [expr {![file exists $fresh_directory]}] "output directory already exists"
    file mkdir $fresh_directory
    set driver_inputs {}
    foreach name [dict get $post drivers] {
        foreach ref {D PRE} {lappend driver_inputs [pin [cell $name] $ref]}
    }
    set sinks {}
    foreach name [dict get $post sinks] {
        lappend sinks [one get_pins -hier -quiet -filter "NAME == \"$name\""]
    }
    foreach corner {Fast Slow} {
        foreach mode {max min} {
            report_timing -to $driver_inputs -corner $corner -delay_type $mode -max_paths 100 -nworst 4 -path_type full_clock_expanded -file [file join $fresh_directory drivers-$corner-$mode.rpt]
            report_timing -to $sinks -corner $corner -delay_type $mode -max_paths 100 -nworst 4 -path_type full_clock_expanded -file [file join $fresh_directory rst-$corner-$mode.rpt]
        }
    }
    dict set post status REPORTS_ONLY_NOT_SIGNOFF
    return $post
}
