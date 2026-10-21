# Tool-only overlay for a separately hash-verified frozen post_opt entry.
# Caller must first verify/open the exact optimized checkpoint and frozen package.
# The original frozen path is unchanged; this overlay installs lookups only.
if {![info exists valence(post_opt_constraints)] || ![file isfile $valence(post_opt_constraints)]} {
    error "EXACT_CACHE requires original frozen post_opt entry"
}
set cache_overlay_dir [file dirname [file normalize [info script]]]
if {[file normalize $valence(post_opt_constraints)] eq [file normalize [info script]]} {
    error "EXACT_CACHE original post_opt entry must not be the overlay"
}
source [file join $cache_overlay_dir exact_object_cache.tcl]
common_exact_cache::enable
source $valence(post_opt_constraints)
puts "EXACT_CACHE_FROZEN_POST_OPT_COMPLETE LOOKUPS_ONLY_ALL_ORIGINAL_PROOFS_REEXECUTED"
