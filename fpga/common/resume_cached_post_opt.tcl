# Separate post-opt-only recovery. Never touches an active run or frozen manifest.
set cached_resume_tools [file dirname [file normalize [info script]]]
proc cached_post_opt_resume {} {
    global argv valence cached_resume_tools
    if {[llength $argv]!=2} {error "usage: ORIGINAL_CONFIG OBSERVED_OPTIMIZED_SHA256"}
    source [lindex $argv 0]
    if {$valence(diagnosticOnly)!=1 || $valence(clock_profile) ne "performance300-static"} {error "Diagnostic performance300 required"}
    foreach command {write_bitstream write_device_image} {
        if {[llength [info commands $command]]} {rename $command cached_resume_forbidden_$command}
        proc ::$command {args} {error "DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM"}
    }
    # Original frozen checker validates original inventory; explicit checkpoint
    # digest must be obtained from the preserved run, never inferred as success.
    set evidence [exec $valence(python) -E [file join $cached_resume_tools resume_cached_post_opt.py] $valence(root) [lindex $argv 1]]
    set valence(out) [file join $valence(root) diagnostic-run cached-post-opt-[clock clicks]]
    if {[file exists $valence(out)]} {error "Do not overwrite recovery evidence"}
    file mkdir $valence(out)
    cd $valence(out)
    set f [open provenance.json {WRONLY CREAT EXCL}]; puts $f $evidence; close $f
    set valence(control_lemma) 1
    set_param general.maxThreads $valence(threads)
    if {$valence(threads)<8 || [get_param general.maxThreads]<$valence(threads)} {error "Thread request not honored"}
    open_checkpoint [file join $valence(root) diagnostic-run implementation optimized-unqualified.dcp]
    # This executes the original frozen entry; only exact object lookups change.
    source [file join $cached_resume_tools cached_post_opt.tcl]
    write_checkpoint optimized-checked-unqualified.dcp
    puts "CACHED_POST_OPT_COMPLETE DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM"
}
if {[catch {cached_post_opt_resume} reason options]} {
    puts stderr "$reason\n[dict get $options -errorinfo]"
    exit 1
}
exit 0
