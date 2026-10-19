# Run on the current ROUTED no-MAC board. Structural/STA inventory only:
# no false paths, waivers, clock changes or physical qualification are applied.
proc i1_audit_board_reset_cdc {reports} {
    set cdc [open [file join $reports cdc.rpt] r]
    set text [read $cdc]
    close $cdc
    set critical [regexp -all -inline -line {^\s*[0-9]+\s+CDC-[0-9]+\s+Critical[^\n]*} $text]
    if {[llength $critical]!=9} {error "Expected exact nine reset Critical rows; review changed CDC inventory"}
    set stems [list \
        u_soc/bank/cmu/bridge/destinationResetSync/release_0_reg \
        u_soc/bank/uart/agent/release_0/release_0_reg \
        u_soc/bank/uart/bridge/destinationResetSync/release_0_reg \
        u_soc/bank/uart/gatedClock_gate/release_0/release_0_reg \
        u_soc/bank/uart/ingress/release_0/release_0_reg \
        u_soc/bank/uart/rawRelease/release_0_reg \
        u_soc/transport/enabled.transport/raw_release_reg \
        u_soc/transport/enabled.transport/source_release_reg \
        u_soc/transport/enabled.transport/update_release_reg]
    set expected [list]
    foreach stem $stems {
        set first [get_cells -quiet "${stem}?0?"]
        if {[llength $first]!=1} {error "Missing exact reset stage0: $stem"}
        set controls [get_pins -of_objects $first -filter {REF_PIN_NAME == PRE || REF_PIN_NAME == CLR}]
        if {[llength $controls]!=1} {error "Reset synchronizer must have one asynchronous control: $stem"}
        lappend expected [get_property NAME $controls]
    }
    set observed [list]
    foreach line $critical {lappend observed [lindex [split [string trim $line]] end]}
    if {[lsort $observed] ne [lsort $expected]} {error "Unreviewed Critical data/reset endpoint"}
    set f [open [file join $reports reset_cdc_structure.tsv] w]
    puts $f "instance\tclock\tstages\tasync_reg\tdirect_chain\tfunctional_reset_loads\tsynchronizer_reset_loads\tmax_slack_ns\tmin_slack_ns"
    set index 0
    foreach stem $stems {
        incr index
        set previous {}
        set localClock {}
        for {set stage 0} {$stage<3} {incr stage} {
            set cell [get_cells -quiet "${stem}?${stage}?"]
            if {[llength $cell]!=1 || ![get_property ASYNC_REG $cell]} {
                error "Every retained reset stage must be ASYNC_REG: $stem $stage"
            }
            set clock [get_clocks -of_objects [get_pins -of_objects $cell -filter {REF_PIN_NAME == C}]]
            if {[llength $clock]!=1} {error "Missing unique reset destination clock: $stem"}
            if {$stage==0} {set localClock [get_property NAME $clock]}
            if {[get_property NAME $clock] ne $localClock} {error "Reset stages cross clocks: $stem"}
            if {$stage>0} {
                set d [get_pins -of_objects $cell -filter {REF_PIN_NAME == D}]
                set driver [get_pins -leaf -of_objects [get_nets -segments -of_objects $d] \
                    -filter {DIRECTION == OUT}]
                if {[llength $driver]!=1 || [get_property NAME $driver] ne $previous} {
                    error "Combinational logic or branch inside reset release chain: $stem $stage"
                }
            }
            set q [get_pins -of_objects $cell -filter {REF_PIN_NAME == Q}]
            set previous [get_property NAME $q]
        }
        set loads [filter [all_fanout -flat -endpoints_only -from $q] \
            {CLASS == pin && DIRECTION == IN && (REF_PIN_NAME == PRE || REF_PIN_NAME == CLR)}]
        set functional [list]
        set synchronizers [list]
        foreach load $loads {
            if {[get_property ASYNC_REG [get_cells -of_objects $load]] in {1 TRUE true}} {
                lappend synchronizers $load
            } else {lappend functional $load}
        }
        if {![llength $functional] && $index ni {4 6}} {
            error "Unexpected missing functional reset loads: $stem"
        }
        set slacks [list]
        foreach delay {max min} {
            set path {}
            if {[llength $functional]} {
                set path [get_timing_paths -quiet -from $q -to $functional -delay_type $delay -max_paths 1]
            }
            if {[llength $functional]} {
                if {![llength $path] || [get_property SLACK $path] eq ""} {
                    error "Functional reset release lacks timed recovery/removal: $stem $delay"
                }
                lappend slacks [get_property SLACK $path]
                report_timing -from $q -to $functional -delay_type $delay -max_paths 10 \
                    -file [file join $reports [format "reset_release_%02d_%s.rpt" $index $delay]]
            } else {lappend slacks SYNC_RESET_ONLY_EXISTING_EXCEPTION_REVIEW}
        }
        puts $f "$stem\t$localClock\t3\tTRUE\tTRUE\t[llength $functional]\t[llength $synchronizers]\t[join $slacks \t]"
    }
    close $f
    puts "I1_RESET_CDC_STRUCTURE_CHECKED exact_critical=9 stages=3 NO_WAIVER NO_CDC_SIGNOFF"
}
