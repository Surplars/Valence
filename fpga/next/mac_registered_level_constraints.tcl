# PREPARED_NOT_NETLIST_QUALIFIED. Five exact single-bit CDC bounds only.
# The read-only collector remains separate. No false paths, clock groups,
# multicycle paths, reset exceptions or raw/managed functional-path exceptions.
source [file join [file dirname [info script]] audit_mac_netlist.tcl]

proc valence_mac_registered_level_constraints {contract} {
    valence_mac::validate_contract $contract
    set root [dict get $contract root]
    set valence_mac::clocks [dict create]
    dict for {domain pin} [dict get $contract clock_pins] {
        dict set valence_mac::clocks $domain [valence_mac::clock $root/$pin]
    }
    set valence_mac::facts stdout
    set scopes {}
    foreach row [dict get $contract level_rules] {
        lassign $row chain source from to sr tr
        lappend scopes [valence_mac::level $root/$chain $root/$source $from $to \
            [format {%s/%s/release_0_reg[2]/Q} $root $sr] [format {%s/%s/release_0_reg[2]/Q} $root $tr]]
    }
    # Validate every endpoint before creating any constraint. These legal C
    # startpoints avoid Q-pin path segmentation and are never clock-wide cuts.
    foreach scope $scopes {
        lassign $scope start end
        set_max_delay -datapath_only 8.0 -from [get_pins $start] -to [get_pins $end]
    }
    puts "MAC_FIVE_REGISTERED_LEVEL_BOUNDS_APPLIED NETLIST_REVIEW_STILL_REQUIRED"
}
