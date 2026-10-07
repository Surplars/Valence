# Read-only cached OOC report extraction; no optimization or reimplementation.
if {$argc != 1} { error "usage: vivado-fp-cached-paths.tcl REPORT_ROOT" }
set fp_cached_root [file normalize [lindex $argv 0]]
source [file join [file dirname [info script]] vivado-module-path-details.tcl]
foreach fp_cached_top {FloatingPointAdd FloatingPointState FloatingPointSystem} {
    set fp_cached_dir [file join $fp_cached_root $fp_cached_top]
    open_checkpoint [file join $fp_cached_dir post_route.dcp]
    valence_module_path_details [file join $fp_cached_dir cached-details]
    close_design
}
puts "FP_CACHED_PATH_DETAILS_COMPLETE"
