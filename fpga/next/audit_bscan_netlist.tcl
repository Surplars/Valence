# Read-only netlist queries and report files; never creates clocks, waivers,
# resets, probes, synthesis or bitstreams. Source in a separately opened matching
# synthesized/routed design. This is an evidence collector, NOT CDC/RDC signoff.
source [file join [file dirname [info script]] check_jtag_chain.tcl]

proc valence_bscan_exact {kind name} {
    if {$name eq "" || [regexp {[\*\?\[\]]} $name]} {error "Exact BSCAN hierarchy required"}
    set objects [${kind} -quiet $name]
    if {[llength $objects]!=1} {error "Missing/ambiguous BSCAN object: $name"}
    return $objects
}
proc valence_bscan_sync_bank {root suffix count} {
    if {$root eq "" || [regexp {[\*\?\[\]]} $root]} {error "Exact BSCAN hierarchy required"}
    # Vivado may retain generate blocks as enabled.transport, not enabled/transport.
    # Literal dots and other regexp metacharacters must never broaden a selection.
    set quoted [regsub -all {[][{}().+*?^$\|\\]} $root {\\&}]
    set cells [get_cells -quiet -hierarchical -regexp [format {^%s/%s_reg\[[0-9]+\]$} $quoted $suffix]]
    if {[llength $cells]!=$count} {error "BSCAN synchronizer shape mismatch: $root/$suffix"}
    foreach cell $cells {
        if {[lsearch -exact [list_property $cell] ASYNC_REG]<0 ||
            [get_property ASYNC_REG $cell] ni {TRUE true 1}} {error "Missing ASYNC_REG: $cell"}
    }
    return $cells
}
proc valence_collect_bscan_netlist {primitive engine fabric_clock output} {
    if {[file exists $output]} {error "Use a fresh BSCAN report directory"}
    valence_assert_jtag_chain 2 $primitive
    valence_bscan_exact get_cells $primitive
    valence_bscan_exact get_cells $engine
    valence_bscan_exact get_clocks $fabric_clock
    if {![regsub {([/.])transport$} $engine {\1user_scan} expected_primitive] ||
        $primitive ne $expected_primitive} {
        error "Primitive and engine are not the matching wrapper siblings"
    }
    set clock_rows {}
    foreach pin {TCK DRCK UPDATE} {
        set object [valence_bscan_exact get_pins $primitive/$pin]
        set clocks [get_clocks -quiet -of_objects $object]
        if {[llength $clocks]==0} {error "Unconstrained BSCAN $pin; supply reviewed primitive clock model first"}
        foreach clock $clocks {
            lappend clock_rows [list $pin [get_property NAME $clock] [get_property PERIOD $clock] \
                [get_property WAVEFORM $clock]]
        }
    }
    set syncs {}
    foreach {suffix count} {source_release 3 update_sync 2 bridge/source_release 3 \
                           bridge/dest_release 3 bridge/request_sync 2 bridge/response_sync 2} {
        set slash [string last / $suffix]
        if {$slash<0} {set root $engine;set name $suffix} else {
            set root $engine/[string range $suffix 0 [expr {$slash-1}]]
            set name [string range $suffix [expr {$slash+1}] end]
        }
        lappend syncs {*}[valence_bscan_sync_bank $root $name $count]
    }
    file mkdir $output
    set file [open [file join $output structure.txt] w]
    puts $file "USER2 primitive=$primitive engine=$engine fabric_clock=$fabric_clock"
    puts $file "clock_rows=$clock_rows"
    puts $file "synchronizers=$syncs"
    puts $file "Primitive pins (including vendor special internal pins):"
    foreach pin [get_pins -of_objects [get_cells $primitive]] {puts $file $pin}
    puts $file "STATUS=SCOPED_STRUCTURE_PRESENT_NOT_PHYSICAL_SIGNOFF"
    close $file
    report_cdc -details -file [file join $output cdc.rpt]
    report_clock_interaction -file [file join $output clock_interaction.rpt]
    report_exceptions -coverage -file [file join $output exceptions.rpt]
    report_timing_summary -report_unconstrained -file [file join $output timing_summary.rpt]
    puts "BSCAN_REPORTS_COLLECTED REVIEW_BUNDLED_DATA_CLOCK_PHASES_RESET_AND_TIMING_MANUALLY"
}
