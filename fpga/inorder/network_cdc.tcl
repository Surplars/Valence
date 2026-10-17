# Scoped bounds only; no blanket clock groups or datapath false paths.
if {[llength [info commands valence_cdc_bus]] == 0} {
    source [file join [file dirname [info script]] native-gmac-cdc-constraints.tcl]
}
proc i1_network_cdc {budget {constant_levels {}}} {
    set counts [dict create register 0 mailbox 0 gray 0 level 0 payload 0]
    set verified_constants {}
    foreach cell [get_cells -hierarchical -filter {REF_NAME =~ RegisterClockDomainBridge*}] {
        valence_register_cdc_constraints [get_property NAME $cell] $budget
        dict incr counts register
    }
    foreach cell [get_cells -hierarchical -filter {REF_NAME =~ CdcMailbox*}] {
        valence_mailbox_cdc_constraints [get_property NAME $cell] $budget
        dict incr counts mailbox
    }
    foreach cell [get_cells -hierarchical -filter {REF_NAME =~ CdcDataFifo* || REF_NAME =~ StreamClockDomainFifo*}] {
        set hier [get_property NAME $cell]
        valence_stream_cdc_constraints $hier $budget
        dict incr counts gray
        set captures [get_cells -quiet "$hier/output_0_reg*"]
        if {[llength $captures] == 0} { set captures [get_cells -quiet "$hier/output_reg*"] }
        if {[llength $captures] == 0} { error "missing actual registered FIFO output: $hier" }
        set ends [get_pins -of_objects $captures -filter {REF_PIN_NAME == D}]
        set starts [filter [all_fanin -flat -startpoints_only -to $ends] \
            {REF_PIN_NAME == C || REF_PIN_NAME == CLK || REF_PIN_NAME == WCLK || REF_PIN_NAME == CLKARDCLK || REF_PIN_NAME == CLKBWRCLK}]
        if {[llength $starts] == 0 || [llength $ends] == 0} { error "missing FIFO RAM launch/capture: $hier" }
        set_max_delay -datapath_only $budget -from $starts -to $ends
        set_bus_skew $budget -from $starts -to $ends
        puts "I1_FIFO_PAYLOAD_BOUND $hier starts=[llength $starts] ends=[llength $ends] budget=$budget"
        dict incr counts payload
    }
    foreach cell [get_cells -hierarchical -filter {REF_NAME =~ CdcLevel*}] {
        set hier [get_property NAME $cell]
        set captures [get_cells -quiet "$hier/stages_reg?0?"]
        if {[llength $captures] != 1} { error "missing persistent-level first synchronizer stage: $hier" }
        set ends [get_pins -of_objects $captures -filter {REF_PIN_NAME == D}]
        # Board-only unused inputs may be explicitly tied off. The normal OOC
        # invocation has an empty allowlist and retains its original strict gate.
        # Prove the ACTUAL first-stage D is driven directly by GND/VCC; no
        # exception is added, and constants do not count as qualified CDC links.
        if {[dict exists $constant_levels $hier]} {
            set expected [dict get $constant_levels $hier]
            if {$expected ni {GND VCC}} {error "Invalid constant CDC contract: $hier"}
            set nets [get_nets -segments -of_objects $ends]
            set leaf [get_pins -quiet -leaf -of_objects $nets -filter {DIRECTION == OUT}]
            if {[llength $leaf] != 1 ||
                [get_property REF_NAME [get_cells -of_objects $leaf]] ne $expected} {
                error "Explicit board CDC tie-off changed: $hier expected=$expected got=$leaf"
            }
            lappend verified_constants $hier
            puts "I1_BOARD_CONSTANT_LEVEL_VERIFIED $hier $expected NO_TIMING_EXCEPTION"
            continue
        }
        set drivers [all_fanin -flat -startpoints_only -to $ends]
        set ports [filter $drivers {CLASS == port}]
        if {[llength $ports] == 1 && [llength $drivers] == 1} {
            set_max_delay -datapath_only $budget -from $ports -to $ends
        } else { valence_level_cdc_constraint $hier $budget }
        dict incr counts level
    }
    if {[lsort $verified_constants] ne [lsort [dict keys $constant_levels]]} {
        error "Explicit board CDC tie-off endpoint missing: $constant_levels"
    }
    if {[dict get $counts register] < 2 || [dict get $counts mailbox] < 2 ||
        [dict get $counts gray] < 2 || [dict get $counts payload] < 2 || [dict get $counts level] < 2} {
        error "incomplete managed CDC composition: $counts"
    }
    puts "I1_NETWORK_CDC_BOUNDS $counts budget=$budget NO_CLOCK_GROUPS NO_PAYLOAD_FALSE_PATHS"
    return $counts
}
