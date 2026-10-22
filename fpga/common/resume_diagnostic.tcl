# Recovery overlay outside the frozen package. Never regenerates IP or writes a bitstream.
set recovery_tools [file dirname [file normalize [info script]]]
proc resume_diagnostic {} {
    global argv valence recovery_tools
    if {[llength $argv] ni {1 2 3 4}} {error "usage: resume_diagnostic.tcl ORIGINAL_CONFIG ?synthesis|implementation|post-opt|place-route|post-synth-tail? ?CHECKPOINT? ?OBSERVED_SHA256?"}
    source [lindex $argv 0]
    if {$valence(diagnosticOnly)!=1 || $valence(clock_profile) ni {performance300-static boot50-dynamic}} {error "Only reviewed diagnostic profile may resume"}
    set phase [expr {[llength $argv]>=2 ? [lindex $argv 1] : "synthesis"}]
    if {$phase ni {synthesis implementation post-opt place-route post-synth-tail}} {error "Invalid recovery phase"}
    if {($phase in {post-opt post-synth-tail} && [llength $argv]!=3) || ($phase eq "place-route" && [llength $argv]!=4) || ($phase in {synthesis implementation} && [llength $argv]>2)} {error "Invalid checkpoint arguments for mode"}
    if {$phase eq "post-opt"} {
        if {[file normalize [lindex $argv 0]] ne [file normalize [file join $valence(root) diagnostic-run config.tcl]] || [version -short] ne "2025.2"} {error "POST_OPT requires canonical frozen config and Vivado 2025.2"}
        if {![info exists ::env(VALENCE_POST_OPT_DEADLINE_MS)] || ![string is entier -strict $::env(VALENCE_POST_OPT_DEADLINE_MS)]} {error "POST_OPT requires wrapper start + 600000 ms deadline"}
        set ::post_opt_deadline $::env(VALENCE_POST_OPT_DEADLINE_MS)
        set now [clock milliseconds]
        if {$::post_opt_deadline<=$now || $::post_opt_deadline-$now>600000} {error "Invalid post-opt 600 second deadline"}
        puts "POST_OPT_BUDGET_BEGIN deadline_ms=$::post_opt_deadline budget_ms=600000"
        flush stdout
    }
    set valence(phase) $phase
    set valence(out) [file join $valence(root) diagnostic-run synthesis]
    cd $valence(out)
    foreach cmd {write_bitstream write_device_image} {
        if {[llength [info commands $cmd]]} {rename $cmd recovery_forbidden_$cmd}
        proc ::$cmd {args} {error "DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM"}
    }
    set_param general.maxThreads $valence(threads)
    if {$valence(threads)<8 || [get_param general.maxThreads]<$valence(threads)} {error "Thread request not honored"}
    set ::env(VALENCE_REQUESTED_THREADS) $valence(threads)
    set ::env(VALENCE_PROFILE_SHA256) $valence(profile_sha256)
    source [file join $valence(root) fpga common producer_common.tcl]
    set extra {}; if {$phase in {post-opt post-synth-tail}} {set extra [list [lindex $argv 2]]}; if {$phase eq "place-route"} {set extra [lrange $argv 2 3]}
    set evidence [exec $valence(python) -E [file join $recovery_tools resume_diagnostic.py] $valence(root) $phase {*}$extra]
    set f [open resume-ooc-evidence-[clock clicks].json {WRONLY CREAT EXCL}]; puts $f $evidence; close $f
    # Only successful frozen check grants this source-bound lemma.
    set valence(control_lemma) 1
    set valence(recovery_tools) $recovery_tools
    # Versioned anchor overlay is separately hashed in recovery evidence above.
    set valence(post_synth_constraints) [file join $recovery_tools post_synth.tcl]
    set valence(post_opt_constraints) [file join $recovery_tools post_opt.tcl]
    if {$phase eq "post-synth-tail"} {
        if {$valence(clock_profile) ne "boot50-dynamic" || [version -short] ne "2025.2"} {error "TAIL requires reviewed dynamic profile and Vivado 2025.2"}
        foreach name {post-synth-tail-start.json post-synth-tail-native.json post-synth-tail-provenance.json tail-retained.xdc tail-retained-constraints.json dynamic-performance-target-clocks.rpt} {
            if {[file exists $name]} {error "Preserve previous tail output $name"}
        }
        set f [open post-synth-tail-start.json {WRONLY CREAT EXCL}]; puts $f $evidence; close $f
        open_checkpoint [file join $valence(out) failed-resume-unqualified-1603981302391.dcp]
        if {[get_property PART [current_design]] ne "xczu15eg-ffvb1156-2-i" || [get_property TOP [current_design]] ne "soc_top_common_ddr"} {error "TAIL wrong reopened part/top"}
        foreach command {synth_design opt_design place_design phys_opt_design route_design launch_runs create_project create_ip generate_target import_ip read_xdc create_clock create_generated_clock set_max_delay set_min_delay set_bus_skew set_false_path set_clock_groups set_multicycle_path} {
            if {[llength [info commands $command]]} {rename $command tail_forbidden_$command}
            proc ::$command {args} {error "TAIL_FORBIDS_SYNTH_IP_IMPLEMENTATION_AND_CONSTRAINT_MUTATION"}
        }
        source [file join $recovery_tools dynamic performance_targets.tcl]
        native_dynamic_performance_targets
        source [file join $recovery_tools post_synth_tail_constraints.tcl]
        post_synth_tail_retained_constraints
        puts [exec $valence(python) -E [file join $recovery_tools resume_diagnostic.py] $valence(root) retained-tail]
        set f [open post-synth-tail-native.json {WRONLY CREAT EXCL}]
        puts $f {{"status":"TARGET_CHECKS_RETURNED","version":"2025.2","part":"xczu15eg-ffvb1156-2-i","top":"soc_top_common_ddr"}}
        close $f
        write_checkpoint synthesized.dcp
        report_utilization -file utilization.rpt
        puts [exec $valence(python) -E [file join $recovery_tools resume_diagnostic.py] $valence(root) seal-tail [lindex $argv 2]]
        set valence(phase) synthesis
        common_record post_synth_tail [list open_checkpoint failed-resume-unqualified-1603981302391.dcp] configured [get_param general.maxThreads] post-synth-tail-provenance.json
        common_receipt
        puts [exec $valence(python) -E [file join $recovery_tools resume_diagnostic.py] $valence(root) implementation]
        close_project
    } elseif {$phase eq "place-route"} {
        foreach command {synth_design opt_design launch_runs create_project create_ip generate_target import_ip write_bitstream write_device_image} {
            if {[llength [info commands $command]]} {rename $command continuation_forbidden_$command}
            proc ::$command {args} {error "CONTINUATION_FORBIDS_SYNTH_OPT_IP_AND_BIT"}
        }
        set input [file normalize [lindex $argv 2]]
        set stages [dict create optimized-checked-unqualified.dcp optimized placed.dcp placed physical-optimized-unqualified.dcp physical routed.dcp routed]
        set stage [dict get $stages [file tail $input]]
        set valence(out) [file join $valence(root) diagnostic-run place-route-[clock clicks]]
        if {[file exists $valence(out)]} {error "Preserve prior continuation"}
        file mkdir $valence(out); cd $valence(out)
        set f [open provenance.json {WRONLY CREAT EXCL}]; puts $f $evidence; close $f
        open_checkpoint $input
        set valence(continuation) 1
        set ::diagnostic_definitions_only 1
        source [file join $recovery_tools diagnostic.tcl]
        diagnostic_tail $stage
        set f [open continuation-complete.txt {WRONLY CREAT EXCL}]; puts $f "DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM"; close $f
    } elseif {$phase eq "post-opt"} {
        set valence(out) [file join $valence(root) diagnostic-run cached-post-opt-[clock clicks]]
        if {[file exists $valence(out)]} {error "Do not overwrite recovery evidence"}
        file mkdir $valence(out); cd $valence(out)
        set f [open provenance.json {WRONLY CREAT EXCL}]; puts $f $evidence; close $f
        open_checkpoint [file join $valence(root) diagnostic-run implementation optimized-unqualified.dcp]
        foreach command {synth_design opt_design place_design phys_opt_design route_design launch_runs create_project create_ip generate_target import_ip} {
            if {[llength [info commands $command]]} {rename $command post_opt_forbidden_$command}
            proc ::$command {args} {error "POST_OPT_FORBIDS_SYNTH_OPT_IP_AND_PHYSICAL_STEPS"}
        }
        if {[get_property PART [current_design]] ne "xczu15eg-ffvb1156-2-i" || [get_property TOP [current_design]] ne "soc_top_common_ddr"} {error "POST_OPT wrong reopened part/top"}
        source [file join $recovery_tools cached_post_opt.tcl]
        if {$::common_collect_session::active || [dict get $::common_collect_session::last outcome] ne "COMPLETE" || [llength [dict get $::common_collect_session::last incomplete_phases]]} {error "POST_OPT incomplete collect lifecycle"}
        foreach name {properties kinds ambiguous queries guarded} {
            if {[set ::common_collect_session::$name] ne {}} {error "POST_OPT retained collect state: $name"}
        }
        set now [clock milliseconds]
        if {$now>$::post_opt_deadline} {error "PERF_FAIL_INCOMPLETE post-opt exceeded 600 seconds"}
        write_checkpoint optimized-candidate-unqualified.dcp
        set now [clock milliseconds]
        if {$now>$::post_opt_deadline} {error "PERF_FAIL_INCOMPLETE post-opt checkpoint exceeded 600 seconds"}
        set f [open post-opt-native.json {WRONLY CREAT EXCL}]
        puts $f [format {{"status":"POST_OPT_RETURNED","started_unix_ms":%s,"completed_unix_ms":%s,"deadline_unix_ms":%s,"budget_ms":600000}} [expr {$::post_opt_deadline-600000}] $now $::post_opt_deadline]
        close $f
        puts [exec $valence(python) -E [file join $recovery_tools resume_diagnostic.py] $valence(root) seal-post-opt $valence(out)]
        puts "POST_OPT_COMPLETE_WITHIN_600S elapsed_ms=[expr {[clock milliseconds]-($::post_opt_deadline-600000)}]"
        flush stdout
    } elseif {$phase eq "implementation"} {
        if {[file exists [file join $valence(root) diagnostic-run implementation]]} {error "Preserve previous implementation attempt"}
        file mkdir [file join $valence(root) diagnostic-run implementation]
        set argv [list [lindex $argv 0] implementation]
        source [file join $recovery_tools diagnostic.tcl]
    } else {
        set valence(resume_ooc) 1
        set valence(resume_raw) [file exists raw-synthesized-unqualified.dcp]
        source [file join $recovery_tools synthesize.tcl]
    }
    puts "DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM"
}
if {[catch {resume_diagnostic} reason options]} {
    catch {write_checkpoint failed-resume-unqualified-[clock clicks].dcp}
    puts stderr "$reason\n[dict get $options -errorinfo]"
    exit 1
}
exit 0
