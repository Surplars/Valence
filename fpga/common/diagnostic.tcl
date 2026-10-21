# Independent physical measurement, never a release/signoff entry.
proc diagnostic_main {} {
    global argv valence
    if {[llength $argv]!=2} {error "usage: diagnostic.tcl CONFIG synthesis|implementation"}
    source [lindex $argv 0]
    if {![info exists valence(diagnosticOnly)] || $valence(diagnosticOnly)!=1 || $valence(clock_profile) ne "performance300-static"} {error "Diagnostic performance300 config required"}
    set valence(phase) [lindex $argv 1]
    if {$valence(phase) ni {synthesis implementation}} {error "No release/signoff phase exists here"}
    set valence(out) [file join $valence(root) diagnostic-run $valence(phase)]
    cd $valence(out)
    foreach cmd {write_bitstream write_device_image} {
        if {[llength [info commands $cmd]]} {rename $cmd diagnostic_forbidden_native_$cmd}
        proc ::$cmd {args} {error "DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM"}
    }
    set_param general.maxThreads $valence(threads)
    if {[get_param general.maxThreads]<$valence(threads) || $valence(threads)<8} {error "Thread request not honored"}
    set ::env(VALENCE_REQUESTED_THREADS) $valence(threads)
    set ::env(VALENCE_PROFILE_SHA256) $valence(profile_sha256)
    source [file join $valence(root) fpga common producer_common.tcl]
    puts [exec $valence(python) [file join $valence(root) fpga common diagnostic.py] check --manifest $valence(manifest)]
    if {$valence(phase) eq "synthesis"} {
        source [file join $valence(root) fpga common synthesize.tcl]
    } else {
        open_checkpoint [file join $valence(root) diagnostic-run synthesis synthesized.dcp]
        common_design_step opt_design
        source $valence(post_opt_constraints)
        write_checkpoint optimized.dcp
        common_design_step place_design
        write_checkpoint placed.dcp
        common_design_step phys_opt_design
        common_design_step route_design
        write_checkpoint routed.dcp
        report_timing_summary -delay_type min_max -report_unconstrained -file timing.rpt
        check_timing -verbose -file coverage.rpt
        report_cdc -details -file cdc.rpt
        report_drc -file drc.rpt
        report_clocks -file clocks.rpt
        report_route_status -file route.rpt
        report_bus_skew -file bus-skew.rpt
        report_utilization -file utilization.rpt
        # Same-clock register paths only. Not a cross-domain Fmax claim.
        foreach domain {cpu fabric} {
            set clk [get_clocks -quiet -of_objects [get_pins -quiet u_soc/${domain}Clock]]
            if {[llength $clk]!=1} {error "Missing actual $domain clock"}
            report_timing -from $clk -to $clk -delay_type max -max_paths 20 -file $domain-worst-paths.rpt
        }
        set valence(dcp_sha256) [string trim [exec $valence(python) -c {import hashlib;print(hashlib.sha256(open('routed.dcp','rb').read()).hexdigest())}]]
        set ::common_board_definitions_only 1
        source [file join $valence(root) fpga common board_audit.tcl]
        set f [open diagnostic-audit.txt w]
        if {[catch {common_board::run} reason]} {puts $f "BLOCKED $reason"} else {puts $f "STRUCTURAL_CHECKS_ONLY_NOT_QUALIFICATION"}
        puts $f "DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM missing_integrated_functional_receipt=1"
        close $f
        common_receipt
        close_design
    }
    puts "DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM"
}
if {[catch {diagnostic_main} reason options]} {
    # Keep work already completed, without admitting an invalid stage downstream.
    catch {write_checkpoint -force failed-stage-unqualified.dcp}
    set f [open diagnostic-failure.txt w];puts $f "$reason\n[dict get $options -errorinfo]";close $f
    puts stderr "DIAGNOSTIC_BLOCKED $reason"
    exit 1
}
exit 0
