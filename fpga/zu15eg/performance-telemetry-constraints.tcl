# Source after cdc_constraints.tcl, then call on each ClockPerformanceTelemetry.
# Budget must be strictly less than the fastest supported managed source period.
# Do NOT replace this with asynchronous clock groups / false paths.
proc valence_performance_telemetry_constraints {hier budget} {
    if {$budget <= 0} { error "Telemetry Gray budget must be positive" }
    valence_register_cdc_constraints "$hier/bridge" $budget
    # One hierarchy-scoped query, then classify names locally: no per-bit scan.
    set allCaptures [get_cells -quiet -hierarchical -filter "NAME =~ $hier/domain*/graySync0_*_reg*"]
    set captureNames [get_property NAME $allCaptures]
    if {[llength $allCaptures] != 512} {error "Expected16 telemetry Gray banks of32bits"}
    foreach domain {domain0 domain1} {
        for {set counter 0} {$counter < 8} {incr counter} {
            set captures {}
            foreach cell $allCaptures name $captureNames {
                if {[string match "$hier/$domain/graySync0_${counter}_reg*" $name]} {lappend captures $cell}
            }
            if {[llength $captures] != 32} { error "Wrong telemetry Gray capture width: $hier/$domain/$counter" }
            set ends [get_pins -of_objects $captures -filter {REF_PIN_NAME == D}]
            # Synthesis may merge Gray MSB with binary MSB: trace actual drivers.
            set drivers [all_fanin -flat -startpoints_only -to $ends]
            set starts [get_pins -of_objects [get_cells -of_objects $drivers] -filter {REF_PIN_NAME == C}]
            if {[llength $starts] != [llength $ends]} { error "Telemetry Gray bank width mismatch" }
            set_max_delay -datapath_only $budget -from $starts -to $ends
            set_bus_skew $budget -from $starts -to $ends
            puts "VALENCE_TELEMETRY_GRAY $hier/$domain/$counter width=[llength $ends] budget=$budget"
        }
    }
}
