# Only the four native gate reset synchronizers proved in the R36 focused
# mapped reports. This removes recovery/removal at exactly their twelve async
# PRE inputs, NOT just assertion timing. The complete three-stage local release
# chain and every downstream functional reset path remain normally timed.
# No action on source; explicitly call native_dynamic_reset::apply after the
# unchanged CPU300/fabric250 target clocks and dynamic helper have been loaded.
# No other CdcResetRelease (including telemetry) is covered by this contract.
namespace eval native_dynamic_reset {namespace path ::native_dynamic_lock}

proc native_dynamic_reset::loads {root role} {
    set result {}
    if {$role eq "raw"} {
        foreach name {ce raw_token closed_token} {lappend result $root/gate/${name}_reg/CLR}
        foreach {name count} {enable_sync 3 token_sync 3 closed_edges 4} {
            for {set i 0} {$i < $count} {incr i} {lappend result [format {%s/gate/%s_reg[%d]/CLR} $root $name $i]}
        }
    } elseif {$role eq "managed"} {
        for {set i 0} {$i < 4} {incr i} {lappend result [format {%s/gate/managed_edges_reg[%d]/CLR} $root $i]}
    } else {error "DYNAMIC_RESET unknown role $role"}
    return [lsort $result]
}

proc native_dynamic_reset::falling {endpoint} {
    return [regexp {/(closed_edges_reg\[[0-3]\]|raw_token_reg|closed_token_reg)/CLR$} $endpoint]
}

proc native_dynamic_reset::inspect {} {
    set plan {}; set aon [clock u_clk_wiz/clk_out1]
    require {abs([get_property PERIOD [get_clocks -quiet $aon]]-20.0)<0.002} "reset source clock is not AON50"
    foreach {root target period} {cpu_clock cpu_target300 3.333333333333 fabric_clock fabric_target250 4.0} {
        foreach role {raw managed} {
            set driver [expr {$role eq "raw" ? [format {%s/aon_reset_pipe_reg[2]} $root] : "$root/gate/evidence_clear_reg"}]
            set driverObject [native_dynamic_exact get_cells $driver]
            require {[get_property REF_NAME $driverObject] eq "FDPE" &&
                [string tolower [get_property INIT $driverObject]] in {1 1'b1 1'h1 0x1}} "wrong registered reset source $driver"
            foreach refpin {C D CE PRE} {pin $driver/$refpin IN $refpin}
            pin $driver/Q OUT Q 0; enabled $driver
            require {[clock $driver/C] eq $aon} "reset source is not AON $driver"
            set buffer [expr {$role eq "raw" ? "$root/observer_buffer/O" : "$root/managed_buffer/O"}]
            set stages {}
            for {set i 0} {$i < 3} {incr i} {lappend stages [format {%s/gate/%s_reset_pipe_reg[%d]} $root $role $i]}
            set pattern [format {^%s/gate/%s_reset_pipe_reg\[[0-9]+\]$} $root $role]
            require {[names [native_dynamic_lookup::matching $pattern]] eq [lsort $stages]} "reset stage census changed $root/$role"
            set endpoints {}
            foreach cell $stages {
                set object [native_dynamic_exact get_cells $cell]
                require {[get_property REF_NAME $object] eq "FDPE" &&
                    [get_property ASYNC_REG $object] in {1 true TRUE} &&
                    [string tolower [get_property INIT $object]] in {1 1'b1 1'h1 0x1}} "unreviewed reset stage $cell"
                foreach refpin {C D CE PRE} {pin $cell/$refpin IN $refpin}
                pin $cell/Q OUT Q 0; enabled $cell
                require {[clock $cell/C] eq $target && [connections $cell/C OUT] eq [list $buffer]} "wrong release clock/buffer $cell"
                require {abs([get_property PERIOD [get_clocks -quiet $target]]-$period)<0.002} "changed target period $target"
                require {[connections $cell/PRE OUT] eq [list $driver/Q]} "wrong reset PRE driver $cell"
                lappend endpoints $cell/PRE
            }
            set first [lindex $stages 0]
            set nets [get_nets -quiet -segments -of_objects [pin $first/D IN D]]
            require {[llength $nets]>0} "floating stage0 D $first"
            foreach net $nets {require {[get_property TYPE $net] eq "GROUND"} "stage0 D is not zero $first"}
            set timed {}
            for {set i 1} {$i < 3} {incr i} {
                set previous [lindex $stages [expr {$i-1}]]; set next [lindex $stages $i]
                require {[connections $next/D OUT] eq [list $previous/Q] &&
                    [connections $previous/Q IN] eq [list $next/D]} "reset interstage/early fanout changed $previous"
                lappend timed [list $previous/C $next/D 0]
            }
            set last [lindex $stages 2]; set consumers [loads $root $role]
            require {[connections $last/Q IN] eq $consumers} "functional reset fanout changed $last"
            foreach endpoint $consumers {
                set cell [file dirname $endpoint]
                require {[get_property REF_NAME [native_dynamic_exact get_cells $cell]] eq "FDCE"} "functional load is not FDCE $endpoint"
                pin $endpoint IN CLR
                set c [pin $cell/C IN C 0]; set invert [get_property IS_INVERTED $c]
                set falls [falling $endpoint]
                require {$invert in {0 1 false true FALSE TRUE} &&
                    ($invert in {1 true TRUE}) == $falls} "functional load clock polarity changed $endpoint"
                require {[clock $cell/C] eq $target && [connections $cell/C OUT] eq [list $buffer]} "foreign functional reset clock $endpoint"
                require {[connections $endpoint OUT] eq [list $last/Q]} "functional reset has another driver $endpoint"
                lappend timed [list $last/C $endpoint $falls]
            }
            lappend plan [dict create root $root role $role target $target period $period endpoints $endpoints timed $timed]
        }
    }
    return $plan
}

proc native_dynamic_reset::timing {plan phase} {
    set evidence {}
    foreach bank $plan {
        set target [dict get $bank target]; set period [dict get $bank period]
        foreach row [dict get $bank timed] {
            lassign $row from to falls
            foreach kind {max min} {
                set paths [get_timing_paths -quiet -from [pin $from IN C] -to [native_dynamic_exact get_pins $to] \
                    -delay_type $kind -max_paths 1]
                require {[llength $paths]==1} "missing retained $kind path $from -> $to"
                set req [get_property REQUIREMENT $paths]; set slack [get_property SLACK $paths]
                set expected [expr {($kind eq "max" ? $period : 0.0)-($falls ? $period/2 : 0.0)}]
                require {[finite $req] && [finite $slack] && abs($req-$expected)<0.002} "wrong/nonfinite retained $kind timing $to"
                require {[get_property STARTPOINT_PIN $paths] eq $from && [get_property ENDPOINT_PIN $paths] eq $to &&
                    [get_property STARTPOINT_CLOCK $paths] eq $target && [get_property ENDPOINT_CLOCK $paths] eq $target} "wrong retained timing endpoints/clocks $to"
                require {[string tolower [string trim [get_property EXCEPTION $paths]]] in {{} none}} "excepted retained reset path $to"
                lappend evidence [list $from $to $kind $req $slack]
                puts "DYNAMIC_RESET_RETAINED phase=$phase from=$from to=$to kind=$kind requirement=$req slack=$slack"
            }
        }
    }
    return $evidence
}

proc native_dynamic_reset::apply {} {
    if {![llength [info commands ::native_dynamic_lookup::begin]]} {error "DYNAMIC_RESET load dynamic_clock_constraints.tcl first"}
    try {
        native_dynamic_lookup::begin
        set plan [inspect]
        set before [timing $plan before]
        set cuts {}
        foreach bank $plan {foreach name [dict get $bank endpoints] {lappend cuts [pin $name IN PRE]}}
        require {[llength $cuts]==12} "wrong exact reset-entry count"
        set_false_path -to $cuts
        set after [timing $plan after]
        require {$before eq $after} "retained reset timing changed after entry exception"
        puts "DYNAMIC_RESET_ENTRIES_PROVED exact_PRE=12 chains=4 FUNCTIONAL_RECOVERY_REMOVAL_RETAINED NOT_SIGNOFF"
        return $plan
    } finally {native_dynamic_lookup::clear}
}
