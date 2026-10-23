# Physical-only repair for the fixed RAW125 -> serial managed MAC125 trees.
# This is NOT recovered phy_rx/clk_rx. Do not group serial upstream/downstream
# buffers with CLOCK_DELAY_GROUP or change clocks, CE logic or exceptions.
# Use on a placed/routed candidate; retain the existing RAW125 root and align
# both managed output trees with it, then rebuild/reroute and requalify timing.
# UG912 permits multiple tool-assigned CLOCK_ROOT regions on one clock net.
# Never collapse those into an arbitrary USER_CLOCK_ROOT. Such candidates are
# explicitly deferred without mutation; callers must check the returned status.
namespace eval common_mac_placement {}
proc common_mac_placement::one {command args} {
    set objects [$command {*}$args]
    if {[llength $objects] != 1} {error "MAC locality requires exactly one $command $args; got $objects"}
    return $objects
}
proc common_mac_placement::net {pin} {
    return [one get_nets -of_objects [one get_pins -quiet $pin]]
}
proc common_mac_placement::clock {pin period} {
    set clock [one get_clocks -of_objects [one get_pins -quiet $pin]]
    if {abs([get_property PERIOD $clock] - $period) > 0.001} {error "MAC locality clock period changed: $pin"}
    return [get_property NAME $clock]
}
proc common_mac_placement::inspect {} {
    set raw [one get_cells -quiet network_clock/raw_div]
    if {[get_property REF_NAME $raw] ne "BUFGCE_DIV" || [get_property BUFGCE_DIVIDE $raw] != 4} {
        error "MAC locality requires the actual RAW125 divide-by-four buffer"
    }
    clock network_clock/raw_div/I 2.0
    set rawClock [clock network_clock/raw_div/O 8.0]
    set rawNet [net network_clock/raw_div/O]
    set nets [list $rawNet]
    set rawSegments [get_nets -segments -of_objects [one get_pins -quiet network_clock/raw_div/O]]
    foreach gate {txManaged_gate rxManaged_gate} {
        set path u_soc/peripherals/gmac/$gate/buffer
        set cell [one get_cells -quiet $path]
        if {[get_property REF_NAME $cell] ne "BUFGCE"} {error "MAC managed gate primitive changed: $path"}
        set input [one get_pins -quiet $path/I]
        if {[get_property IS_INVERTED $input] ni {0 FALSE false 1'b0}} {error "MAC managed gate input polarity changed: $path"}
        set overlap 0
        foreach segment [get_nets -segments -of_objects $input] {
            if {[lsearch -exact $rawSegments $segment] >= 0} {set overlap 1}
        }
        if {!$overlap} {error "MAC managed gate is not serially sourced by RAW125: $path"}
        if {[clock $path/O 8.0] ne $rawClock} {error "MAC managed clock must inherit the same related RAW125 clock: $path"}
        set output [net $path/O]
        if {$output eq $rawNet || [lsearch -exact $nets $output] >= 0} {error "MAC clock outputs must be distinct"}
        lappend nets $output
    }
    # Resolve each region separately, after all serial-topology checks. A
    # multi-root value belongs to ONE net, not multiple accidentally selected
    # nets. A root shared by two nets does not identify the relevant clock branch.
    set rootsByNet [dict create]
    set multiRoot 0
    foreach output $nets {
        set names [get_property CLOCK_ROOT $output]
        if {[llength $names] == 0} {error "MAC locality needs actual placed CLOCK_ROOT: $output"}
        set roots {}
        foreach name $names {
            if {![regexp {^X[0-9]+Y[0-9]+$} $name]} {
                error "MAC locality requires reviewed clock-region roots, not an unknown root expression: $name"
            }
            set region [one get_clock_regions -quiet $name]
            if {[get_property NAME $region] ne $name || [lsearch -exact $roots $name] >= 0} {
                error "MAC locality root identity is not unique/exact: $name"
            }
            lappend roots $name
        }
        dict set rootsByNet $output $roots
        if {[llength $roots] > 1} {set multiRoot 1}
    }
    set result [dict create nets $nets roots_by_net $rootsByNet]
    if {$multiRoot} {
        dict set result status DEFERRED_MULTI_ROOT
        dict set result reason {Preserve native multi-root assignment; driver/load branch evidence required before any root override}
    } else {
        dict set result status SINGLE_ROOT_CANDIDATE
        dict set result root [lindex [dict get $rootsByNet $rawNet] 0]
    }
    return $result
}
proc common_mac_placement::apply {} {
    set objects [inspect]
    if {[dict get $objects status] eq "DEFERRED_MULTI_ROOT"} {
        puts "COMMON_MAC_CLOCK_LOCALITY_DEFERRED reason=MULTI_ROOT roots=[dict get $objects roots_by_net] NO_PROPERTIES_CHANGED REVIEW_REQUIRED"
        return $objects
    }
    # Validate every object before changing any property. Do not move BUFGs;
    # their serial route legality and all original data placements stay intact.
    set_property USER_CLOCK_ROOT [dict get $objects root] [dict get $objects nets]
    puts "COMMON_MAC_CLOCK_LOCALITY root=[dict get $objects root] nets=[dict get $objects nets] SERIAL_TREES_REQUIRE_FULL_SETUP_HOLD"
    dict set objects status APPLIED_REQUIRES_REROUTE
    return $objects
}
