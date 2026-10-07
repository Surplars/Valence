# Read-only timing/structural queries: never synthesize or implement again.
# Use the real-ROM-imported, clock-free soc_candidate.dcp from this exact batch.
if {$argc != 2} {error "Expected CANDIDATE_SOC_DCP OUT_DIRECTORY"}
lassign $argv candidate out
file mkdir $out
open_checkpoint $candidate
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {
    error "Candidate contains unresolved functional black boxes"
}
if {[llength [get_clocks -quiet]]} {error "Expected clock-free replaceable SoC partition"}
create_clock -name soc_query_clock -period 20 [get_ports clock]
set translated [get_pins -quiet -hier -filter {
    NAME =~ platform/core/adapter/translated/*/C && REF_PIN_NAME == C}]
set owners [get_pins -quiet -hier -filter {
    NAME =~ platform/core/adapter/owners/*/WE && REF_PIN_NAME == WE}]
set checked [get_pins -quiet -hier -filter {
    NAME =~ platform/core/adapter/checked/*/WE && REF_PIN_NAME == WE}]
if {![llength $translated] || ![llength $owners] || ![llength $checked]} {
    error "Missing translated/checked/owner FIFO boundaries"
}
set old_chain [get_timing_paths -quiet -from $translated -to $owners -max_paths 1]
if {[llength $old_chain]} {error "Translated/PMP to response-owner WE is still combinational"}
puts "STAGED_FABRIC: translated/PMP -> physical response-owner WE has no direct path"
report_timing -from $translated -to $checked -max_paths 5 \
    -file [file join $out translated_to_checked_we.rpt]
# This is an enqueue/write-enable control query, NOT the PMP fault-data delay.
set home_ready [get_pins -quiet platform/coherentHome/io_upstream_request_ready]
set arbiter_ready [get_pins -quiet platform/physicalData_systemArbiter/io_memory_request_ready]
if {[llength $home_ready] != 1 || [llength $arbiter_ready] != 1} {
    error "Missing Home/system-arbiter boundary"
}
set ready_chain [get_timing_paths -quiet -through $home_ready -through $arbiter_ready -max_paths 1]
if {[llength $ready_chain]} {error "Home grant still feeds system ready combinationally"}
puts "STAGED_FABRIC: Home grant -> system ready has no direct path"
report_timing -through $home_ready -max_paths 5 \
    -file [file join $out home_grant.rpt]
report_timing -max_paths 10 -file [file join $out remaining_worst.rpt]
close_design
