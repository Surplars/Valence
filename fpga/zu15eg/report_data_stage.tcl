# Read-only structural and 10ns setup queries of complete real-ROM checkpoints.
# Never runs synthesis, placement, routing, or bit generation.
if {$argc != 3} {error "Expected BASELINE_DCP CANDIDATE_DCP OUT_DIRECTORY"}
lassign $argv baseline candidate out
file mkdir $out
set_param general.maxThreads 8
proc pins_at {pattern} {
    set pins [get_pins -quiet -hier -filter "NAME =~ $pattern"]
    if {![llength $pins]} {error "Missing boundary $pattern"}
    return $pins
}
set backend platform/core/core/core/backend
foreach kind {baseline candidate} {
    open_checkpoint [set $kind]
    if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Functional black box remains"}
    if {[llength [get_clocks -quiet]]} {error "Expected clock-free checkpoint"}
    create_clock -name data_query_clock -period 20 [get_ports clock]
    set checks [list \
        [list issue_to_dtlb_ready [pins_at $backend/lsu/io_start_valid] \
            [pins_at platform/core/adapter/io_translation_request_ready]] \
        [list lsu_ready_to_aplic_ready [pins_at $backend/lsu/io_memory_response_ready] \
            [pins_at platform/core/parallelRouter/io_upstream_response_ready]]]
    foreach check $checks {
        lassign $check name from to
        set paths [get_timing_paths -quiet -through $from -through $to -max_paths 1]
        puts "DATA_STAGE: $kind $name direct_paths=[llength $paths]"
        if {$kind eq "candidate" && [llength $paths]} {error "Requested credit cut remains combinational: $name"}
        if {[llength $paths]} {
            report_timing -through $from -through $to -max_paths 5 -file [file join $out ${kind}_${name}.rpt]
        }
    }
    report_timing -max_paths 80 -nworst 1 -file [file join $out ${kind}_endpoints_20ns.rpt]
    # Reconstraint the same synthesized netlist, not a new 100MHz synthesis run.
    reset_timing
    create_clock -name data_query_clock -period 10 [get_ports clock]
    report_timing_summary -delay_type min_max -file [file join $out ${kind}_summary_10ns.rpt]
    report_timing -max_paths 80 -nworst 1 -file [file join $out ${kind}_endpoints_10ns.rpt]
    close_design
}
