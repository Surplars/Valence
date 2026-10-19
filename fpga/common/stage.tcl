# Reviewed producer contract: config.tcl supplies valence(root/out/threads/profile...).
# This wrapper is not a sandbox for untrusted Tcl. All producer bytes are hash-bound.
proc valence_stage_main {} {
    global argv argc valence
    if {$argc != 2} {error "usage: stage.tcl CONFIG_TCL simulation|synthesis|implementation"}
    source [lindex $argv 0]
    set phase [lindex $argv 1]
    if {$phase ni {simulation synthesis implementation}} {error "Unknown phase"}
    set valence(phase) $phase
    set valence(out) [file join $valence(root) local-run $phase]
    cd $valence(out)
    if {$valence(threads) < 8} {error "Request at least eight threads"}
    set_param general.maxThreads $valence(threads)
    set limit [get_param general.maxThreads]
    if {$limit < $valence(threads)} {error "Vivado thread limit below requested value: $limit"}
    puts "COMMON_THREAD_LIMIT requested=$valence(threads) effective_limit=$limit active_threads=UNMEASURED"
    set ::env(VALENCE_REQUESTED_THREADS) $valence(threads)
    set ::env(VALENCE_PROFILE_SHA256) $valence(profile_sha256)
    rename write_bitstream valence_disabled_native_write_bitstream
    proc ::write_bitstream {args} {error "Bit generation is forbidden before common final signoff"}
    source $valence(script_$phase)
    if {![file isfile [file join $valence(out) stage-receipt.json]]} {error "Stage receipt was not produced"}
    puts "COMMON_STAGE_FINISHED $phase REQUIRES_PYTHON_RECEIPT_CHECK"
}
if {[catch {valence_stage_main} result options]} {
    puts stderr "COMMON_STAGE_FAILED: $result"
    if {[dict exists $options -errorinfo]} {puts stderr [dict get $options -errorinfo]}
    exit 1
}
exit 0
