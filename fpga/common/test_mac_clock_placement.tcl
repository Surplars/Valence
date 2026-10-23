# Synthetic command/negative tests only, not native placement or timing proof.
source [file join [file dirname [info script]] mac_clock_placement.tcl]
set mode ok
set writes {}
set route_calls {}
set roots_override [dict create]
# Both inspect/apply APIs must never initiate a design/routing operation.
foreach operation {route_design update_clock_routing place_design phys_opt_design} {
    proc $operation {args} "lappend ::route_calls $operation"
}
proc get_cells {args} {
    if {$::mode eq "missing-gate" && [string match *rxManaged* [lindex $args end]]} {return {}}
    return [lindex $args end]
}
proc get_pins {args} {return [lindex $args end]}
proc get_clock_regions {args} {
    set name [lindex $args end]
    if {$::mode eq "unknown-root" && $name eq "X9Y9"} {return {}}
    return $name
}
proc get_nets {args} {
    set pin [lindex $args end]
    if {$pin eq "network_clock/raw_div/O"} {return raw_net}
    if {[string match */buffer/I $pin]} {
        if {$::mode eq "phy-rx-source" && [string match *rxManaged* $pin]} {return clk_rx}
        return raw_net
    }
    if {$::mode eq "alias-output"} {return raw_net}
    return net_$pin
}
proc get_clocks {args} {
    set pin [lindex $args end]
    if {$pin eq "network_clock/raw_div/I"} {return ref500}
    if {$::mode eq "unrelated" && [string match *rxManaged* $pin]} {return phy_rx}
    return raw125
}
proc get_property {property object} {
    switch -- $property {
        REF_NAME {
            if {$object eq "network_clock/raw_div"} {return BUFGCE_DIV}
            if {$::mode eq "wrong-gate"} {return LUT1}
            return BUFGCE
        }
        BUFGCE_DIVIDE {if {$::mode eq "wrong-divider"} {return 2}; return 4}
        IS_INVERTED {if {$::mode eq "inverted"} {return 1}; return 0}
        PERIOD {
            if {$object eq "ref500"} {return 2.0}
            if {$::mode eq "wrong-period"} {return 40.0}
            return 8.0
        }
        NAME {
            if {$::mode eq "root-identity" && [string match X* $object]} {return X9Y9}
            return $object
        }
        CLOCK_ROOT {
            if {$::mode eq "unplaced"} {return {}}
            if {[dict exists $::roots_override $object]} {return [dict get $::roots_override $object]}
            return X2Y4
        }
        default {error "Unexpected property $property"}
    }
}
proc set_property {property value objects} {lappend ::writes [list $property $value $objects]}
set result [common_mac_placement::apply]
if {[dict get $result status] ne "APPLIED_REQUIRES_REROUTE"} {error "Missing applied status"}
set expected {{USER_CLOCK_ROOT X2Y4 {raw_net net_u_soc/peripherals/gmac/txManaged_gate/buffer/O net_u_soc/peripherals/gmac/rxManaged_gate/buffer/O}}}
if {$writes ne $expected || [llength $route_calls]} {error "Unexpected mutations: $writes"}
foreach mode {missing-gate wrong-divider wrong-gate inverted wrong-period unrelated phy-rx-source alias-output unplaced root-identity} {
    set writes {}
    set route_calls {}
    if {![catch {common_mac_placement::apply} message]} {error "Accepted negative: $mode"}
    if {[llength $writes] || [llength $route_calls]} {error "Mutation before all validations completed: $mode"}
    puts "REJECTED $mode: $message"
}
# Multiple roots must be represented explicitly, in observed order, never
# selected, flattened into USER_CLOCK_ROOT, or silently reported as applied.
set mode ok
foreach {label net roots} {
    raw raw_net {X3Y3 X2Y3}
    reversed raw_net {X2Y3 X3Y3}
    tx net_u_soc/peripherals/gmac/txManaged_gate/buffer/O {X3Y3 X2Y3}
    rx net_u_soc/peripherals/gmac/rxManaged_gate/buffer/O {X3Y3 X2Y3}
} {
    set roots_override [dict create $net $roots]
    set writes {}
    set route_calls {}
    set inspection [common_mac_placement::inspect]
    set result [common_mac_placement::apply]
    if {[llength $writes] || [llength $route_calls] || [dict get $result status] ne "DEFERRED_MULTI_ROOT" ||
        [dict exists $result root] || [dict get $result roots_by_net $net] ne $roots ||
        $inspection ne $result} {error "Multi-root case was altered or claimed applied: $label"}
    puts "PRESERVED_MULTI_ROOT $label"
}
# A second scalar fixture must still align to the actual RAW root, not a
# hard-coded board region or the first managed root.
set mode ok
set roots_override [dict create raw_net X3Y3 \
    net_u_soc/peripherals/gmac/txManaged_gate/buffer/O X2Y3 \
    net_u_soc/peripherals/gmac/rxManaged_gate/buffer/O X2Y4]
set writes {}
set route_calls {}
set result [common_mac_placement::apply]
if {[dict get $result status] ne "APPLIED_REQUIRES_REROUTE" ||
    [dict get $result root] ne "X3Y3" || [llength $writes] != 1 ||
    [lindex [lindex $writes 0] 1] ne "X3Y3" || [llength $route_calls]} {error "Scalar behavior changed"}
# A multi-root value must not mask broken serial topology or invalid roots.
foreach {mode roots} {
    phy-rx-source {X3Y3 X2Y3}
    unknown-root {X3Y3 X9Y9}
    ok {X3Y3 X3Y3}
    ok {X3Y3 bad-root}
    ok {}
} {
    set roots_override [dict create raw_net $roots]
    set writes {}
    set route_calls {}
    if {![catch {common_mac_placement::apply} message] || [llength $writes] || [llength $route_calls]} {
        error "Bad multi-root/topology case did not fail before mutation: $mode $roots"
    }
    puts "REJECTED_ROOT_OR_TOPOLOGY $mode $roots: $message"
}
set mode ok
set roots_override [dict create]
set writes {}
set route_calls {}
set result [common_mac_placement::inspect]
if {[dict get $result status] ne "SINGLE_ROOT_CANDIDATE" || [llength $writes] || [llength $route_calls]} {
    error "Inspection changed physical properties"
}
# Representative optional caller: no unroute is permitted before the decision.
proc optional_candidate_caller {} {
    set result [common_mac_placement::apply]
    switch -- [dict get $result status] {
        APPLIED_REQUIRES_REROUTE {update_clock_routing}
        DEFERRED_MULTI_ROOT {}
        default {error "Unexpected root helper result"}
    }
    return $result
}
set roots_override [dict create raw_net {X3Y3 X2Y3}]
set writes {}
set route_calls {}
optional_candidate_caller
if {[llength $writes] || [llength $route_calls]} {error "Deferred caller changed native assignment/routing"}
set roots_override [dict create]
set writes {}
set route_calls {}
optional_candidate_caller
if {$writes ne $expected || $route_calls ne {update_clock_routing}} {error "Single-root caller contract changed"}
puts "PASS_MAC_CLOCK_PLACEMENT_SYNTHETIC_ONLY"
