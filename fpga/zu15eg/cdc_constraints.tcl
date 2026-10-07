# Scoped constraints, not set_clock_groups. Do not mask payloads or Gray buses.
# Call AFTER synthesis with hierarchy and the minimum supported domain period.
proc valence_cdc_bus {from_cells to_cells budget label} {
    if {[llength $from_cells] == 0 || [llength $to_cells] == 0} {
        error "Missing CDC endpoint: $label; naming/implementation changed"
    }
    # Use legal sequential STARTPOINTS (C/cells), not Q. Q segmentation would
    # break unrelated timing arcs and make bus skew reports return NA.
    set starts [get_pins -of_objects $from_cells -filter {REF_PIN_NAME == C}]
    set ends [get_pins -of_objects $to_cells -filter {REF_PIN_NAME == D}]
    if {[llength $starts] == 0 || [llength $ends] == 0} { error "Missing CDC pin: $label" }
    set_max_delay -datapath_only $budget -from $starts -to $ends
    if {[llength $starts] >= 2 && [llength $ends] >= 2} {
        set_bus_skew $budget -from $starts -to $ends
    }
    puts "VALENCE_CDC_BOUNDED $label starts=[llength $starts] ends=[llength $ends] budget=$budget"
}
proc valence_register_cdc_constraints {hier min_period} {
    valence_cdc_bus [get_cells -quiet "$hier/requestHeld*_reg*"] \
        [get_cells -quiet "$hier/request_*_reg*"] $min_period register_request_payload
    valence_cdc_bus [get_cells -quiet "$hier/responseHeld*_reg*"] \
        [get_cells -quiet "$hier/reply_*_reg*"] $min_period register_response_payload
    foreach pair {{requestToggle requestSync} {responseToggle responseSync}} {
        lassign $pair toggle synchronizer
        valence_cdc_bus [get_cells -quiet "$hier/${toggle}_reg*"] \
            [get_cells -quiet "$hier/$synchronizer/stages_reg?0?"] $min_period $toggle
    }
}
proc valence_stream_cdc_constraints {hier min_period} {
    # Synthesis merges Gray MSB with binary MSB. Trace the REAL drivers rather
    # than constraining only registers still named *Gray* (which misses one bit).
    foreach name {readGraySync_stage0 writeGraySync_stage0} {
        set captures [get_cells -quiet "$hier/${name}_reg*"]
        if {[llength $captures] == 0} { error "Missing Gray capture bank: $hier/$name" }
        set ends [get_pins -of_objects $captures -filter {REF_PIN_NAME == D}]
        set drivers [all_fanin -flat -startpoints_only -to $ends]
        set starts [get_pins -of_objects [get_cells -of_objects $drivers] -filter {REF_PIN_NAME == C}]
        if {[llength $starts] != [llength $ends]} {
            error "Gray bus driver width differs: $hier/$name"
        }
        set_max_delay -datapath_only $min_period -from $starts -to $ends
        set_bus_skew $min_period -from $starts -to $ends
        puts "VALENCE_CDC_BOUNDED $name starts=[llength $starts] ends=[llength $ends] budget=$min_period"
    }
}
