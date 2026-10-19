# Executed inside EACH generated IP synthesis process, not merely its parent.
if {![info exists ::env(VALENCE_REQUESTED_THREADS)] || $::env(VALENCE_REQUESTED_THREADS)<8} {error "Missing IP synthesis thread request"}
set_param general.maxThreads $::env(VALENCE_REQUESTED_THREADS)
set effective [get_param general.maxThreads]
if {$effective<$::env(VALENCE_REQUESTED_THREADS)} {error "IP synthesis general thread limit below request"}
set f [open common-ip-threads.txt w]
puts $f "requested=$::env(VALENCE_REQUESTED_THREADS) general_limit=$effective synth_design_effective_max=4 active_threads=UNMEASURED vivado=[version -short]"
close $f
