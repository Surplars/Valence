# Recovery overlay outside the frozen package. Never regenerates IP or writes a bitstream.
set recovery_tools [file dirname [file normalize [info script]]]
proc resume_diagnostic {} {
    global argv valence recovery_tools
    if {[llength $argv] ni {1 2 3}} {error "usage: resume_diagnostic.tcl ORIGINAL_CONFIG ?synthesis|implementation|post-opt? ?OBSERVED_OPTIMIZED_SHA256?"}
    source [lindex $argv 0]
    if {$valence(diagnosticOnly)!=1 || $valence(clock_profile) ne "performance300-static"} {error "Only reviewed diagnostic profile may resume"}
    set phase [expr {[llength $argv]>=2 ? [lindex $argv 1] : "synthesis"}]
    if {$phase ni {synthesis implementation post-opt}} {error "Invalid recovery phase"}
    if {($phase eq "post-opt") != ([llength $argv]==3)} {error "Only post-opt requires an observed checkpoint SHA256"}
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
    set extra {}; if {$phase eq "post-opt"} {set extra [list [lindex $argv 2]]}
    set evidence [exec $valence(python) -E [file join $recovery_tools resume_diagnostic.py] $valence(root) $phase {*}$extra]
    set f [open resume-ooc-evidence-[clock clicks].json {WRONLY CREAT EXCL}]; puts $f $evidence; close $f
    # Only successful frozen check grants this source-bound lemma.
    set valence(control_lemma) 1
    set valence(recovery_tools) $recovery_tools
    # Versioned anchor overlay is separately hashed in recovery evidence above.
    set valence(post_synth_constraints) [file join $recovery_tools post_synth.tcl]
    set valence(post_opt_constraints) [file join $recovery_tools post_opt.tcl]
    if {$phase eq "post-opt"} {
        set valence(out) [file join $valence(root) diagnostic-run cached-post-opt-[clock clicks]]
        if {[file exists $valence(out)]} {error "Do not overwrite recovery evidence"}
        file mkdir $valence(out); cd $valence(out)
        set f [open provenance.json {WRONLY CREAT EXCL}]; puts $f $evidence; close $f
        open_checkpoint [file join $valence(root) diagnostic-run implementation optimized-unqualified.dcp]
        source [file join $recovery_tools cached_post_opt.tcl]
        write_checkpoint optimized-checked-unqualified.dcp
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
