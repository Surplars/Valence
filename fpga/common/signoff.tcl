# Reopen exactly this run's routed checkpoint. No frequency/exception/DRC relaxation.
# Report format support must be qualified against the installed Vivado version.
proc valence_final_main {} {
    global argv argc valence
    if {$argc != 4} {error "usage: signoff.tcl CONFIG_TCL WINDOWS_PYTHON DCP_SHA256 GENERATE_BIT_0_OR_1"}
    source [lindex $argv 0]
    if {[info exists valence(clock_profile)] && $valence(clock_profile) eq "boot50-dynamic"} {
        error "DYNAMIC_SIGNOFF_BLOCKED: native DRP/CDC/RDC and CPU300/fabric250 scenarios are not yet qualified; no bitstream"
    }
    set python [lindex $argv 1]
    set valence(python) $python
    set valence(dcp_sha256) [lindex $argv 2]
    set generate [lindex $argv 3]
    if {![regexp {^[0-9a-f]{64}$} $valence(dcp_sha256)] || $generate ni {0 1}} {error "Invalid final arguments"}
    set valence(out) [file join $valence(root) local-run signoff]
    set dcp [file join $valence(root) local-run implementation routed.dcp]
    cd $valence(out)
    set_param general.maxThreads $valence(threads)
    set limit [get_param general.maxThreads]
    if {$valence(threads) < 8 || $limit < $valence(threads)} {error "Requested thread limit unavailable"}
    puts "COMMON_THREAD_LIMIT requested=$valence(threads) effective_limit=$limit active_threads=UNMEASURED"
    # Block bit output before any supplied scenario/audit script is evaluated.
    rename write_bitstream valence_blocked_write_bitstream
    proc ::write_bitstream {args} {error "Early bit generation forbidden before complete same-DCP gate"}
    open_checkpoint $dcp
    if {[string tolower [get_property PART [current_design]]] ne $valence(part) ||
            [get_property NAME [current_design]] ne $valence(top)} {error "Wrong checkpoint part/top"}
    if {[info exists valence(media_scenarios)]} {source $valence(media_scenarios)}
    # Audit scripts are trusted, frozen, READ-ONLY netlist checkers. Guard common accidental mutations.
    foreach cmd {open_checkpoint read_checkpoint read_xdc set_param set_property reset_property
                 create_clock create_generated_clock delete_clocks set_false_path set_max_delay set_min_delay set_bus_skew
                 set_multicycle_path set_clock_groups set_clock_uncertainty set_input_delay set_output_delay
                 synth_design opt_design place_design phys_opt_design route_design} {
        if {[llength [info commands $cmd]]} {
            rename $cmd valence_blocked_$cmd
            proc ::$cmd {args} {error "No design/constraint mutation or early bit in final checkpoint audit"}
        }
    }
    if {[info exists valence(media_scenarios)]} {
        # Fresh semantic proof on the original final DCP, without new exceptions.
        valence_native_mac_assert_mode u_rgmii
    }
    source $valence(audit_script)
    if {![file isfile [file join $valence(out) board-audit.json]]} {error "Missing actual ROM/reset/CDC/CPU audit"}
    report_timing_summary -delay_type min_max -report_unconstrained -file timing.rpt
    check_timing -verbose -file coverage.rpt
    report_route_status -file route.rpt
    report_bus_skew -delay_type min_max -file bus_skew.rpt
    report_drc -file drc.rpt
    report_cdc -details -file cdc.rpt
    report_clocks -file clocks.rpt
    set critical [llength [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]]
    set boxes [llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]
    set domains {}
    foreach name {cpu fabric timebase ddr_ui uart aon} {
        set pin [get_pins -quiet $valence(pin_$name)]
        if {[llength $pin] != 1} {error "Missing/ambiguous actual $name clock endpoint"}
        set clock [get_clocks -of_objects $pin]
        if {[llength $clock] != 1} {error "Missing/ambiguous actual $name clock"}
        set period [get_property PERIOD $clock]
        if {abs($period - 1.0e9/$valence(hz_$name)) > 0.002} {error "Wrong actual $name clock rate"}
        foreach kind {max min} {
            set path [get_timing_paths -from $clock -to $clock -delay_type $kind -max_paths 1]
            if {[llength $path] != 1} {error "Missing actual $name $kind timing path"}
            set slack($kind) [get_property SLACK $path]
        }
        lappend domains [format {"%s":{"period_ns":%s,"setup_ns":%s,"hold_ns":%s}} $name $period $slack(max) $slack(min)]
    }
    set f [open facts.json w]
    puts $f [format {{"profile_sha256":"%s","dcp_sha256":"%s","part":"%s","top":"%s","critical_drc":%d,"blackboxes":%d,"requested_threads":%d,"effective_thread_limit":%d,"domains":{%s}}} \
        $valence(profile_sha256) $valence(dcp_sha256) $valence(part) $valence(top) $critical $boxes \
        $valence(threads) $limit [join $domains ,]]
    close $f
    # Nonzero parser/coverage/stage/hash failure raises Tcl error BEFORE the sole bit write.
    puts [exec $python -E [file join $valence(root) fpga common manifest.py] signoff \
        --manifest $valence(manifest) --reports $valence(out) --dcp $dcp --dcp-sha256 $valence(dcp_sha256)]
    if {$generate} {
        valence_blocked_write_bitstream [file join $valence(out) qualified.bit]
        puts "COMMON_BIT_GENERATED_FROM_SAME_OPEN_CHECKPOINT BOARD_NOT_TESTED"
    } else {
        puts "COMMON_REPORT_CONTRACT_PASSED NO_BIT_REQUESTED BOARD_NOT_TESTED"
    }
    close_design
}
if {[catch {valence_final_main} result options]} {
    puts stderr "COMMON_FINAL_FAILED: $result"
    if {[dict exists $options -errorinfo]} {puts stderr [dict get $options -errorinfo]}
    exit 1
}
exit 0
