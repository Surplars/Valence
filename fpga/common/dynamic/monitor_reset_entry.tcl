# Explicit diagnostic-only RDC proof for monitor/domain{0,1}/sourceRelease.
# Exactly6 PRE recovery/removal exceptions, NOT assertion-only. All1038 final
# functional CLR and four interstage D endpoints remain normally timed.
# Source has no action; load dynamic_clock_constraints.tcl, inspect, review plan,
# then explicitly apply that exact plan on the same opened native graph.
namespace eval monitor_reset_entry {
    namespace path ::native_dynamic_lock
    variable cells {}; variable pins {}; variable links {}; variable refs {}; variable pininfo {}
    if {![info exists attempted]} {variable attempted 0}
}
proc monitor_reset_entry::expected_loads {root} {
    set result {}
    foreach prefix {gray gray_binary} {
        for {set bank 0} {$bank<8} {incr bank} {
            for {set bit 0} {$bit<32} {incr bit} {
                lappend result [format {%s/%s_%d_reg[%d]/CLR} $root $prefix $bank $bit]
            }
        }
    }
    for {set bit 0} {$bit<7} {incr bit} {lappend result [format {%s/gray_sampledEvents_reg[%d]/CLR} $root $bit]}
    return [lsort $result]
}
proc monitor_reset_entry::index {objects class} {
    set names [get_property NAME $objects]; set classes [get_property CLASS $objects]
    require {[llength $objects]==[llength $names] && [llength $objects]==[llength $classes]} "monitor object cardinality"
    set result {}
    foreach object $objects name $names kind $classes {
        require {$kind eq $class && ![dict exists $result $name]} "monitor object identity $name"
        dict set result $name $object
    }
    return $result
}
proc monitor_reset_entry::begin {} {
    variable cells; variable pins; variable links; variable refs; variable pininfo
    set cells {}; set pins {}; set links {}; set refs {}; set pininfo {}
    set objects [get_cells -quiet -hierarchical -filter {REF_NAME =~ FD* && (NAME =~ u_soc/monitor/domain0/* || NAME =~ u_soc/monitor/domain1/* || NAME =~ ui_reset_pipe_reg*)}]
    require {[llength $objects]>0} "monitor cells absent"
    set cells [index $objects cell]
    set values [get_property REF_NAME $objects]
    require {[llength $values]==[dict size $cells]} "monitor REF_NAME cardinality"
    foreach name [dict keys $cells] value $values {dict set refs $name $value}
    # Only selected exact release/load cells. Never cache across inspections.
    set selected [list [cell {ui_reset_pipe_reg[2]}]]
    foreach root {u_soc/monitor/domain0 u_soc/monitor/domain1} {
        foreach endpoint [expected_loads $root] {lappend selected [cell [file dirname $endpoint]]}
        for {set stage 0} {$stage<3} {incr stage} {lappend selected [cell [format {%s/sourceRelease/release_0_reg[%d]} $root $stage]]}
    }
    set pinobjects [get_pins -quiet -of_objects $selected]
    set pins [index $pinobjects pin]
    foreach property {DIRECTION REF_PIN_NAME IS_INVERTED} {
        set values [get_property $property $pinobjects]
        require {[llength $values]==[dict size $pins]} "monitor pin property cardinality $property"
        foreach name [dict keys $pins] value $values {dict set pininfo $name $property $value}
    }
}
proc monitor_reset_entry::clear {} {variable cells {}; variable pins {}; variable links {}; variable refs {}; variable pininfo {}}
proc monitor_reset_entry::cell {name} {
    variable cells
    require {[dict exists $cells $name]} "monitor missing exact cell $name"
    return [dict get $cells $name]
}
proc monitor_reset_entry::pin {name direction refpin {noninverted 1}} {
    variable pins; variable pininfo
    require {[dict exists $pins $name]} "monitor missing exact pin $name"
    set object [dict get $pins $name]
    require {[dict get $pininfo $name DIRECTION] eq $direction && [dict get $pininfo $name REF_PIN_NAME] eq $refpin} "monitor pin identity $name"
    if {$noninverted} {require {[dict get $pininfo $name IS_INVERTED] in {0 false FALSE}} "monitor inverted/unknown $name"}
    return $object
}
proc monitor_reset_entry::connections {name direction} {
    variable pins; variable links
    require {[dict exists $pins $name]} "monitor missing connected pin $name"
    set nets [get_nets -quiet -segments -of_objects [dict get $pins $name]]
    require {[llength $nets]>0} "monitor floating pin $name"
    set key [list [lsort [get_property NAME $nets]] $direction]
    if {![dict exists $links $key]} {
        dict set links $key [lsort -unique [get_property NAME [get_pins -quiet -leaf -of_objects $nets -filter "DIRECTION == $direction"]]]
    }
    return [dict get $links $key]
}
proc monitor_reset_entry::clock {object} {
    set clocks [get_clocks -quiet -of_objects $object]
    require {[llength $clocks]==1} "monitor missing/ambiguous clock"
    return [get_property NAME $clocks]
}
proc monitor_reset_entry::inspect_impl {} {
    variable cells; variable refs
    set source {ui_reset_pipe_reg[2]}
    require {[get_property REF_NAME [cell $source]] eq "FDPE" && [string tolower [get_property INIT [cell $source]]] in {1 1'b1 1'h1 0x1}} "monitor cold source changed"
    pin $source/Q OUT Q
    set ui [clock [pin $source/C IN C]]
    require {abs([get_property PERIOD [get_clocks -quiet $ui]]-4.0)<0.002} "monitor cold source not UI250"
    set plan {}
    foreach {root lane target} {u_soc/monitor/domain0 cpu_clock cpu_target300 u_soc/monitor/domain1 fabric_clock fabric_target250} {
        set stages {}; set census {}; set pres {}; set interstage {}
        for {set i 0} {$i<3} {incr i} {lappend stages [format {%s/sourceRelease/release_0_reg[%d]} $root $i]}
        dict for {name object} $cells {if {[string match "$root/sourceRelease/*" $name]} {lappend census $name}}
        require {[lsort $census] eq [lsort $stages]} "monitor three-stage census changed $root"
        set period [get_property PERIOD [get_clocks -quiet $target]]
        require {[finite $period] && $period>0} "monitor invalid target period"
        foreach name $stages {
            set ff [cell $name]
            require {[get_property REF_NAME $ff] eq "FDPE" && [get_property ASYNC_REG $ff] in {1 true TRUE} && [string tolower [get_property INIT $ff]] in {1 1'b1 1'h1 0x1}} "monitor release FF changed $name"
            foreach p {C D CE PRE} {pin $name/$p IN $p}; pin $name/Q OUT Q
            require {[clock [pin $name/C IN C]] eq $target && [connections $name/C OUT] eq [list $lane/managed_buffer/O]} "monitor release clock changed $name"
            set nets [get_nets -quiet -segments -of_objects [pin $name/CE IN CE]]
            require {[llength $nets]>0} "monitor floating CE"
            foreach net $nets {require {[get_property TYPE $net] eq "POWER"} "monitor CE not one"}
            require {[connections $name/PRE OUT] eq [list $source/Q]} "monitor PRE source changed $name"
            lappend pres $name/PRE
        }
        set first [lindex $stages 0]; set last [lindex $stages 2]
        set nets [get_nets -quiet -segments -of_objects [pin $first/D IN D]]
        require {[llength $nets]>0} "monitor floating stage0"
        foreach net $nets {require {[get_property TYPE $net] eq "GROUND"} "monitor stage0 D not zero"}
        for {set i 1} {$i<3} {incr i} {
            set prev [lindex $stages [expr {$i-1}]]; set next [lindex $stages $i]
            require {[connections $prev/Q IN] eq [list $next/D] && [connections $next/D OUT] eq [list $prev/Q]} "monitor early fanout/interstage changed"
            lappend interstage [list $prev/C [list $next/D]]
        }
        set loads [expected_loads $root]
        require {[connections $last/Q IN] eq $loads} "monitor exact519 final loads changed $root"
        foreach endpoint $loads {
            set owner [file dirname $endpoint]
            require {[dict get $refs $owner] eq "FDCE"} "monitor functional reset load not FDCE $endpoint"
            pin $endpoint IN CLR
            require {[clock [pin $owner/C IN C]] eq $target && [connections $owner/C OUT] eq [list $lane/managed_buffer/O]} "monitor foreign functional clock $endpoint"
            require {[connections $endpoint OUT] eq [list $last/Q]} "monitor functional driver changed $endpoint"
        }
        lappend plan [dict create root $root clock $target period $period pres $pres groups [concat $interstage [list [list $last/C $loads]]]]
    }
    return $plan
}
proc monitor_reset_entry::inspect {} {
    try {begin; return [inspect_impl]} finally {clear}
}
proc monitor_reset_entry::timing {plan phase} {
    set evidence {}
    foreach bank $plan {
        set target [dict get $bank clock]; set period [dict get $bank period]
        foreach group [dict get $bank groups] {
            lassign $group from ends
            set objects {}; foreach end $ends {lappend objects [pin $end IN [file tail $end]]}
            foreach kind {max min} {
                set paths [get_timing_paths -quiet -from [pin $from IN C] -to $objects -delay_type $kind -nworst 1 -max_paths [llength $ends]]
                require {[llength $paths]==[llength $ends]} "monitor retained path count $phase $kind $from"
                set columns {}
                foreach property {ENDPOINT_PIN STARTPOINT_PIN STARTPOINT_CLOCK ENDPOINT_CLOCK REQUIREMENT SLACK EXCEPTION} {
                    set values [get_property $property $paths]
                    require {[llength $values]==[llength $paths]} "monitor timing property cardinality $property"
                    dict set columns $property $values
                }
                set seen {}
                foreach end [dict get $columns ENDPOINT_PIN] start [dict get $columns STARTPOINT_PIN] \
                    sc [dict get $columns STARTPOINT_CLOCK] ec [dict get $columns ENDPOINT_CLOCK] \
                    req [dict get $columns REQUIREMENT] slack [dict get $columns SLACK] exception [dict get $columns EXCEPTION] {
                    require {$end in $ends && $end ni $seen && $start eq $from} "monitor wrong/duplicate timing endpoint"
                    require {$sc eq $target && $ec eq $target} "monitor retained path clock"
                    require {[finite $req] && [finite $slack] && abs($req-($kind eq "max" ? $period : 0.0))<0.002} "monitor nonfinite/changed requirement"
                    require {[string tolower [string trim $exception]] in {{} none}} "monitor functional/interstage exception"
                    lappend seen $end; lappend evidence [list $from $end $kind $req $slack]
                }
                require {[lsort $seen] eq [lsort $ends]} "monitor retained endpoint coverage"
                puts "MONITOR_RESET_RETAINED phase=$phase from=$from kind=$kind endpoints=[llength $seen]"
            }
        }
    }
    return [lsort $evidence]
}
proc monitor_reset_entry::apply {reviewedPlan} {
    variable attempted
    if {$attempted} {error "MONITOR_RESET one-shot apply already attempted"}
    try {
        begin
        set plan [inspect_impl]
        require {$plan eq $reviewedPlan} "monitor plan differs from reviewed inspect"
        set before [timing $plan before]
        set cuts {}; foreach bank $plan {foreach name [dict get $bank pres] {lappend cuts [pin $name IN PRE]}}
        require {[llength $cuts]==6} "monitor exact PRE count"
        set attempted 1
        set_false_path -to $cuts
        set after [timing $plan after]
        require {$before eq $after} "monitor retained timing changed"
        puts "MONITOR_RESET_ENTRY_PROVED exact_PRE=6 chains=2 functional_CLR=1038 interstage_D=4 RECOVERY_REMOVAL_EXCEPTION NOT_SIGNOFF"
        return $plan
    } finally {clear}
}
