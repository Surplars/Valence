# Strict structural check, not a routed hold waiver. Both members of a group
# must see the SAME pre-global-buffer root; never cascade one BUFG into another.
proc i1_balanced_clock_roots {report_path} {
    set all_buffers [get_cells -quiet -hierarchical -filter {REF_NAME == BUFGCE}]
    if {[llength $all_buffers] != 5} {
        error "expected five actual parallel raw/gated BUFGCEs, got [llength $all_buffers]"
    }
    set log [open $report_path w]
    puts $log "Parallel BUFG roots only; no setup/hold exception; no routed signoff."
    foreach {pattern root expected group} {
        bank/uart/* io_uartClockIn 2 I1_UART_RAW_GATED
        bank/gmac/* io_macTxClock 3 I1_MAC_TX_RAW_GATED
    } {
        set members [filter $all_buffers "NAME =~ $pattern"]
        if {[llength $members] != $expected} {
            error "wrong actual buffer count for $root: $members"
        }
        set outputs {}
        foreach cell $members {
            set input_nets [get_nets -segments -of_objects [get_pins $cell/I]]
            set ports [get_ports -quiet -of_objects $input_nets]
            if {[llength $ports] != 1 || [get_property NAME $ports] ne $root} {
                error "BUFG input is not the expected direct root $root: $cell -> $ports"
            }
            set drivers [get_pins -quiet -leaf -of_objects $input_nets -filter {DIRECTION == OUT}]
            if {[llength $drivers] != 0} {
                error "cascaded/generated BUFG root forbidden in this shell: $cell -> $drivers"
            }
            set net [get_nets -of_objects [get_pins $cell/O]]
            if {[llength $net] != 1} { error "missing clock output net: $cell" }
            lappend outputs $net
            puts $log "$cell I=$root O=$net CE=[get_nets -of_objects [get_pins $cell/CE]]"
        }
        if {[lsearch -exact [list_property [lindex $outputs 0]] CLOCK_DELAY_GROUP] < 0} {
            error "CLOCK_DELAY_GROUP unsupported on actual clock net"
        }
        set_property CLOCK_DELAY_GROUP $group $outputs
        puts $log "CLOCK_DELAY_GROUP=$group nets=$outputs"
    }
    close $log
    puts "I1_PARALLEL_BUFG_ROOTS_CONFIRMED count=5 no_cascade no_timing_waiver"
}
