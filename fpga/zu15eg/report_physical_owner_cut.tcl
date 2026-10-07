# Query the exact eliminated path on saved synthesis checkpoints. Not routed Fmax.
# Usage: FLOW_MODULE_DCP REGISTERED_MODULE_DCP OUT_DIRECTORY
if {$argc != 3} {error "Expected FLOW_MODULE_DCP REGISTERED_MODULE_DCP OUT_DIRECTORY"}
lassign $argv baseline candidate out
file mkdir $out
foreach kind {baseline candidate} {
    open_checkpoint [set $kind]
    set sources [get_ports -quiet io_memory_request_ready]
    set targets [get_ports -quiet {io_client0_response_valid io_client1_response_valid}]
    if {[llength $sources] != 1 || [llength $targets] != 2} {error "Missing arbiter test boundary"}
    set paths [get_timing_paths -quiet -from $sources -to $targets -max_paths 1]
    if {$kind eq "baseline"} {
        if {[llength $paths] != 1} {error "Missing original empty-owner bypass"}
        report_timing -from $sources -to $targets -max_paths 10 \
            -file [file join $out baseline_bypass.rpt]
        puts "OWNER_CUT: baseline bypass delay=[get_property DATAPATH_DELAY $paths]"
    } else {
        if {[llength $paths]} {error "Candidate retains request-ready -> response-valid bypass"}
        puts "OWNER_CUT: candidate has no request-ready -> response-valid bypass"
        report_timing -to $targets -max_paths 10 -file [file join $out candidate_response.rpt]
    }
    close_design
}
