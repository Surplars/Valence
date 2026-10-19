# Called by final signoff BEFORE the read-only audit guard. Each scenario starts
# from the SAME routed.dcp. Only three media clock definitions/budgets change;
# internal CDC bounds, route, hardware and frequencies never change.
source [file join $valence(root) fpga common media_constraints.tcl]
foreach rate {10 100 1000} {
    close_design
    open_checkpoint $dcp
    set directory [file join $valence(out) media-$rate]
    if {[file exists $directory]} {error "Refuse stale media evidence"}
    file mkdir $directory
    set old [get_clocks -quiet {phy_rx phy_rx_launch phy_tx_capture}]
    if {[llength $old] != 3} {error "Expected exactly three reviewed media clocks"}
    delete_clocks $old
    common_media_apply $rate
    # These scenarios cannot issue bit or change implementation.
    report_timing_summary -delay_type min_max -report_unconstrained -file $directory/timing.rpt
    check_timing -verbose -file $directory/coverage.rpt
    report_route_status -file $directory/route.rpt
    report_bus_skew -delay_type min_max -file $directory/bus_skew.rpt
    report_drc -file $directory/drc.rpt
    set critical [llength [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]]
    set periods {}
    foreach clock {phy_rx phy_rx_launch phy_tx_capture} {
        set actual [get_clocks -quiet $clock]
        if {[llength $actual] != 1} {error "Missing media clock $clock"}
        lappend periods [format {"%s":%s} $clock [get_property PERIOD $actual]]
    }
    set f [open $directory/scenario.json w]
    puts $f [format {{"rate_mbps":%d,"profile_sha256":"%s","dcp_sha256":"%s","critical_drc":%d,"periods_ns":{%s},"rx_min_ns":-1.050,"rx_max_ns":1.050,"tx_min_ns":-1.250,"tx_max_ns":1.250}} \
        $rate $valence(profile_sha256) $valence(dcp_sha256) $critical [join $periods ,]]
    close $f
}
# Final audit and optional bit use the original checkpoint, not a scenario overlay.
close_design
open_checkpoint $dcp
