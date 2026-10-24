# Source after cdc_constraints.tcl, then call on each ClockPerformanceTelemetry.
# Budget must be strictly less than the fastest supported managed source period.
# Do NOT replace this with asynchronous clock groups / false paths.
proc valence_performance_telemetry_constraints {hier budget {profile i1}} {
    if {$profile ni {i1 a1-experimental}} {error "Unknown telemetry physical profile"}
    if {$budget <= 0} { error "Telemetry Gray budget must be positive" }
    # One hierarchy-scoped query, then classify names locally: no per-bit scan.
    set allCaptures [get_cells -quiet -hierarchical -filter "(NAME =~ $hier/domain*/graySync0_*_reg* || NAME =~ $hier/cpuRetireLane1/graySync0_*_reg*)"]
    set captureNames [get_property NAME $allCaptures]
    set expected [expr {$profile eq "i1" ? 512 : 544}]
    if {[llength $allCaptures] != $expected || [llength [lsort -unique $captureNames]] != $expected} {
        error "Wrong exact telemetry Gray census for $profile"
    }
    set banks {}
    foreach domain {domain0 domain1} {
        for {set counter 0} {$counter < 8} {incr counter} {lappend banks [list $domain $counter]}
    }
    if {$profile eq "a1-experimental"} {lappend banks [list cpuRetireLane1 1]}
    set plan {}
    foreach bank $banks {
        lassign $bank domain counter
        set captures {}; set bankNames {}
        foreach cell $allCaptures name $captureNames {
            if {[string match "$hier/$domain/graySync0_${counter}_reg*" $name]} {lappend captures $cell; lappend bankNames $name}
        }
        if {[llength $captures] != 32} { error "Wrong telemetry Gray capture width: $hier/$domain/$counter" }
        set expectedNames {}
        for {set bit 0} {$bit<32} {incr bit} {
            lappend expectedNames [format {%s/%s/graySync0_%d_reg[%d]} $hier $domain $counter $bit]
        }
        if {[lsort $bankNames] ne [lsort $expectedNames]} {error "Wrong telemetry Gray bit identities"}
        set ends [get_pins -of_objects $captures -filter {REF_PIN_NAME == D}]
        # Synthesis may merge Gray MSB with binary MSB: trace actual drivers.
        set drivers [all_fanin -flat -startpoints_only -to $ends]
        set starts [get_pins -of_objects [get_cells -of_objects $drivers] -filter {REF_PIN_NAME == C}]
        if {[llength $starts] != 32 || [llength $ends] != 32 || [llength [lsort -unique [get_property NAME $ends]]] != 32 || [llength [lsort -unique [get_property NAME $starts]]] != 32} { error "Telemetry Gray bank width mismatch" }
        lappend plan [list $domain $counter $starts $ends]
    }
    # Prove every Gray bank before adding any new constraint. The A1 extension
    # is explicit; never infer a profile or weaken the old I1 512-bit census.
    valence_register_cdc_constraints "$hier/bridge" $budget
    foreach entry $plan {
        lassign $entry domain counter starts ends
        set_max_delay -datapath_only $budget -from $starts -to $ends
        set_bus_skew $budget -from $starts -to $ends
        puts "VALENCE_TELEMETRY_GRAY $hier/$domain/$counter width=[llength $ends] budget=$budget profile=$profile"
    }
}
