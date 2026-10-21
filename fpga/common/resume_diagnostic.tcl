# Recovery overlay outside the frozen package. Never regenerates IP or writes a bitstream.
set recovery_tools [file dirname [file normalize [info script]]]
proc resume_diagnostic {} {
    global argv valence recovery_tools
    if {[llength $argv]!=1} {error "usage: resume_diagnostic.tcl ORIGINAL_CONFIG"}
    source [lindex $argv 0]
    if {$valence(diagnosticOnly)!=1 || $valence(clock_profile) ne "performance300-static"} {error "Only reviewed diagnostic profile may resume"}
    set valence(phase) synthesis
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
    if {[file exists resume-ooc-evidence.json]} {error "Preserve previous resume evidence; inspect before retry"}
    set evidence [exec $valence(python) -E [file join $recovery_tools resume_diagnostic.py] $valence(root)]
    set f [open resume-ooc-evidence.json w]; puts $f $evidence; close $f
    set valence(resume_ooc) 1
    source [file join $recovery_tools synthesize.tcl]
    puts "DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM"
}
if {[catch {resume_diagnostic} reason options]} {
    puts stderr "$reason\n[dict get $options -errorinfo]"
    exit 1
}
exit 0
