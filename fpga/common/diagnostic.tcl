set ::diagnostic_tools [file dirname [file normalize [info script]]]
# Shared tail for fresh implementation and validated checkpoint continuation.
proc diagnostic_stage_gate {stage {routingStage {}}} {
    if {$routingStage eq {}} {set routingStage $stage}
    check_timing -verbose -file $stage-coverage.rpt
    set f [open $stage-coverage.rpt]; set coverage [read $f]; close $f
    foreach key {no_clock unconstrained_internal_endpoints} {
        set matches [regexp -all -inline [format {checking %s \(([0-9]+)\)} $key] $coverage]
        if {![llength $matches]} {error "Unknown coverage format: $key"}
        foreach {whole count} $matches {if {$count != 0} {error "Blocked $stage: $key=$count"}}
    }
    report_drc -file $stage-drc.rpt
    set critical [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]
    foreach violation $critical {
        # RTSTAT-13 means route-status checks cannot run before routing exists.
        # Preserve original report/severity; this is stage applicability, not waiver.
        set name [get_property NAME $violation]
        set severity [get_property SEVERITY $violation]
        if {$routingStage in {optimized placed physical} && $severity eq "Critical Warning" && [regexp {^RTSTAT-13#[0-9]+$} $name]} {
            set f [open $stage-drc-applicability.txt a]
            puts $f "$name PRE_ROUTE_NOT_YET_APPLICABLE stage=$routingStage original_severity=$severity NO_WAIVER"
            close $f
            puts "DIAGNOSTIC_PRE_ROUTE_NOT_YET_APPLICABLE $name stage=$routingStage NO_WAIVER"
        } else {error "Blocked $stage: Error/Critical Warning DRC $violation"}
    }
    foreach {domain period} {cpu 3.333333333333 fabric 4.0} {
        set clocks [get_clocks -quiet -of_objects [get_pins -quiet u_soc/${domain}Clock]]
        if {[llength $clocks]!=1 || abs([get_property PERIOD $clocks]-$period)>0.002} {error "Actual performance clock changed: $domain"}
    }
}
proc diagnostic_tail {start} {
    global valence diagnostic_tools
    if {$start ni {optimized placed physical routed}} {error "Invalid continuation stage"}
    diagnostic_stage_gate entry $start
    if {$start eq "routed"} {
        write_checkpoint routed.dcp
        if {[info exists valence(continuation)] && $valence(continuation)} {
            puts [exec $valence(python) -E [file join $diagnostic_tools resume_diagnostic.py] $valence(root) seal-stage $valence(out) routed]
        }
    }
    set run [expr {$start eq "optimized"}]
    foreach {prior stage command file} {
        optimized placed place_design placed.dcp
        placed physical phys_opt_design physical-optimized-unqualified.dcp
        physical routed route_design routed.dcp
    } {
        if {$start eq $prior} {set run 1}
        if {!$run} {continue}
        common_design_step $command
        # Save completed expensive work before any subsequent validation.
        write_checkpoint $file
        if {[info exists valence(continuation)] && $valence(continuation)} {
            puts [exec $valence(python) -E [file join $diagnostic_tools resume_diagnostic.py] $valence(root) seal-stage $valence(out) $stage]
        }
        diagnostic_stage_gate $stage
    }
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
        set valence(dcp_sha256) [string trim [exec $valence(python) -E -c {import hashlib;print(hashlib.sha256(open('routed.dcp','rb').read()).hexdigest())}]]
        set ::common_board_definitions_only 1
        source [file join $diagnostic_tools board_audit.tcl]
        set f [open diagnostic-audit.txt w]
        if {[catch {common_board::run} reason]} {puts $f "BLOCKED $reason"} else {puts $f "STRUCTURAL_CHECKS_ONLY_NOT_QUALIFICATION"}
        puts $f "DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM missing_integrated_functional_receipt=1"
        close $f
}

# Independent physical measurement, never a release/signoff entry.
proc diagnostic_main {} {
    global argv valence diagnostic_tools
    set valence(recovery_tools) $diagnostic_tools
    if {[llength $argv]!=2} {error "usage: diagnostic.tcl CONFIG synthesis|implementation"}
    source [lindex $argv 0]
    if {![info exists valence(diagnosticOnly)] || $valence(diagnosticOnly)!=1 || $valence(clock_profile) ni {performance300-static boot50-dynamic}} {error "Diagnostic performance300 config required"}
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
    puts [exec $valence(python) -E [file join $valence(root) fpga common diagnostic.py] check --manifest $valence(manifest)]
    # check above validates all artifact hashes and board_inputs.emission's exact
    # parent/encoder/pad control-equality proof. Never set this before that check.
    set valence(control_lemma) 1
    # New runs use their own tool revision; frozen recovery hashes this overlay.
    set valence(post_opt_constraints) [file join $diagnostic_tools post_opt.tcl]
    if {$valence(phase) eq "synthesis"} {
        source [file join $valence(root) fpga common synthesize.tcl]
    } else {
        open_checkpoint [file join $valence(root) diagnostic-run synthesis synthesized.dcp]
        common_design_step opt_design
        write_checkpoint optimized-unqualified.dcp
        source [file join $diagnostic_tools cached_post_opt.tcl]
        write_checkpoint optimized.dcp
        diagnostic_tail optimized
        common_receipt
        close_design
    }
    puts "DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM"
}
if {[info exists ::diagnostic_definitions_only] && $::diagnostic_definitions_only} {return}
if {[catch {diagnostic_main} reason options]} {
    # Keep work already completed, without admitting an invalid stage downstream.
    catch {write_checkpoint -force failed-stage-unqualified.dcp}
    set f [open diagnostic-failure.txt w];puts $f "$reason\n[dict get $options -errorinfo]";close $f
    puts stderr "DIAGNOSTIC_BLOCKED $reason"
    exit 1
}
exit 0
