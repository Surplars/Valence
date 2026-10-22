# Synthetic command/negative tests only, not native placement or timing proof.
source [file join [file dirname [info script]] mac_clock_placement.tcl]
set mode ok
set writes {}
proc get_cells {args} {
    if {$::mode eq "missing-gate" && [string match *rxManaged* [lindex $args end]]} {return {}}
    return [lindex $args end]
}
proc get_pins {args} {return [lindex $args end]}
proc get_clock_regions {args} {return [lindex $args end]}
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
        NAME {return $object}
        CLOCK_ROOT {if {$::mode eq "unplaced"} {return {}}; return X2Y4}
        default {error "Unexpected property $property"}
    }
}
proc set_property {property value objects} {lappend ::writes [list $property $value $objects]}
common_mac_placement::apply
set expected {{USER_CLOCK_ROOT X2Y4 {raw_net net_u_soc/peripherals/gmac/txManaged_gate/buffer/O net_u_soc/peripherals/gmac/rxManaged_gate/buffer/O}}}
if {$writes ne $expected} {error "Unexpected mutations: $writes"}
foreach mode {missing-gate wrong-divider wrong-gate inverted wrong-period unrelated phy-rx-source alias-output unplaced} {
    set writes {}
    if {![catch {common_mac_placement::apply} message]} {error "Accepted negative: $mode"}
    if {[llength $writes]} {error "Mutation before all validations completed: $mode"}
    puts "REJECTED $mode: $message"
}
puts "PASS_MAC_CLOCK_PLACEMENT_SYNTHETIC_ONLY"
