# Only the new native frame/config/event/retention boundary. No global
# set_clock_groups or broad false paths: payloads and Gray pointers are timed.
source [file join [file dirname [info script]] cdc_constraints.tcl]
proc valence_level_cdc_constraint {hier budget} {
    set captures [get_cells -quiet "$hier/stages_reg?0?"]
    if {[llength $captures] != 1} { error "Missing level first stage: $hier" }
    set ends [get_pins -of_objects $captures -filter {REF_PIN_NAME == D}]
    set drivers [all_fanin -flat -startpoints_only -to $ends]
    set starts [get_pins -of_objects [get_cells -of_objects $drivers] -filter {REF_PIN_NAME == C}]
    if {[llength $starts] != 1} { error "Level CDC is not driven by ONE registered bit: $hier" }
    set_max_delay -datapath_only $budget -from $starts -to $ends
    puts "NATIVE_GMAC_CDC_LEVEL $hier budget=$budget"
}
proc valence_mailbox_cdc_constraints {hier budget} {
    valence_cdc_bus [get_cells -quiet "$hier/held*_reg*"] \
        [get_cells -quiet "$hier/captured*_reg*"] $budget "$hier atomic_payload"
    valence_level_cdc_constraint "$hier/requestSync" $budget
    valence_level_cdc_constraint "$hier/ackSync" $budget
}
proc valence_fifo_payload_constraints {hier budget} {
    # Small SyncReadMem instances may infer LUTRAM plus a registered address,
    # not BRAM. The held-data ownership protocol is valid for either mapping;
    # ALSO bound RAM write-clock -> destination capture data and inter-bit skew.
    # open_checkpoint expands RAM32M16 into RAMD32/RAMS32 primitives; the
    # write-clock pin may be WCLK rather than the pre-expansion CLK name.
    set starts [get_pins -quiet -hier -filter "NAME =~ $hier/storage_ext/* && (REF_PIN_NAME == CLK || REF_PIN_NAME == WCLK)"]
    set captures [get_cells -quiet "$hier/output_0_reg*"]
    set ends [get_pins -of_objects $captures -filter {REF_PIN_NAME == D}]
    if {[llength $starts] == 0 || [llength $ends] != 38} {
        error "Native frame RAM payload mapping changed: $hier starts=[llength $starts] ends=[llength $ends]"
    }
    set_max_delay -datapath_only $budget -from $starts -to $ends
    set_bus_skew $budget -from $starts -to $ends
    set paths [get_timing_paths -quiet -from $starts -to $ends -max_paths 100 -nworst 1]
    if {[llength $paths] != 38} { error "Not all 38 FIFO payload captures are covered: $hier" }
    puts "NATIVE_GMAC_RAM_BOUNDED $hier starts=[llength $starts] ends=[llength $ends] budget=$budget"
}
proc valence_native_gmac_cdc_constraints {root budget} {
    set prefix [expr {$root eq "" ? "" : "$root/"}]
    foreach name {txFifo rxFifo} {
        valence_stream_cdc_constraints "${prefix}${name}/fifo" $budget
        valence_fifo_payload_constraints "${prefix}${name}/fifo" $budget
    }
    foreach name {txConfig rxConfig txEvents rxEvents} {
        valence_mailbox_cdc_constraints "${prefix}${name}/mailbox" $budget
    }
    valence_level_cdc_constraint "${prefix}policy/ack" $budget
    valence_level_cdc_constraint "${prefix}agent/request" $budget
}
