# vivado -mode batch -source this_file -tclargs REPO_ROOT ORIGINAL_ROUTED_DCP FRESH_OUTPUT
# Read-only design queries. This script NEVER applies constraints or saves a DCP.
if {[llength $argv]!=3} {error "usage: REPO_ROOT ORIGINAL_ROUTED_DCP FRESH_OUTPUT"}
lassign $argv repo dcp output
if {![file isfile $dcp] || [file exists $output]} {error "existing DCP and fresh output required"}
file mkdir $output
set ::valence(root) [file normalize $repo]
open_checkpoint $dcp
source [file join $repo fpga common common_cdc.tcl]
source [file join $repo fpga common dynamic mapped_cdc_coverage_repair.tcl]
set plan [r40_cdc_repair::inspect]
set f [open [file join $output mapped-plan.tcllist] w]
puts $f [list $plan]
close $f
set evidence [r40_cdc_repair::timing $plan before 0]
set f [open [file join $output before-paths.tcllist] w]
puts $f [list $evidence]
close $f
puts "R40_CDC_CENSUS_COMPLETE READ_ONLY NO_CONSTRAINT_CHANGE NATIVE_APPLY_NOT_RUN"
