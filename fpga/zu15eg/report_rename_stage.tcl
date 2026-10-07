# Read-only queries on real-ROM complete checkpoints. Never synth/place/route.
if {$argc != 3} {error "Expected BASELINE_DCP CANDIDATE_DCP OUT_DIRECTORY"}
lassign $argv baseline candidate out
file mkdir $out
set_param general.maxThreads 8
proc pins_at {pattern} {
    set pins [get_pins -quiet -hier -filter "NAME =~ $pattern"]
    if {![llength $pins]} {error "Missing boundary $pattern"}
    return $pins
}
set core platform/core/core/core
set backend $core/backend
foreach kind {baseline candidate} {
    open_checkpoint [set $kind]
    if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Functional black box remains"}
    if {[llength [get_clocks -quiet]]} {error "Expected clock-free checkpoint"}
    create_clock -name rename_query_clock -period 20 [get_ports clock]
    set checks [list \
        [list lane0_grant_to_lane1_destination [pins_at $backend/ledger/io_renamed_0_valid] \
            [pins_at $backend/ledger/io_renamed_1_bits_destination*]] \
        [list frontend_valid_to_prediction_payload [pins_at $core/io_instructions_0_valid] \
            [pins_at $backend/io_allocate_1_bits_predictedNextPc_bits*]]]
    foreach check $checks {
        lassign $check name from to
        set paths [get_timing_paths -quiet -through $from -through $to -max_paths 1]
        puts "RENAME_STAGE: $kind $name direct_paths=[llength $paths]"
        if {$kind eq "candidate" && [llength $paths]} {error "Requested payload cut remains: $name"}
        if {[llength $paths]} {
            report_timing -through $from -through $to -max_paths 5 -file [file join $out ${kind}_${name}.rpt]
        }
    }
    if {$kind eq "candidate"} {
        if {[llength [get_cells -quiet $backend/readyUpdate]] != 1} {error "Missing static ready-update module"}
        set ready_outputs [get_pins -quiet -of_objects [get_cells $backend/readyUpdate] -filter {DIRECTION == OUT}]
        puts "RENAME_STAGE: candidate static_ready_output_pins=[llength $ready_outputs]"
    }
    report_timing -max_paths 80 -nworst 1 -file [file join $out ${kind}_endpoints_20ns.rpt]
    reset_timing
    create_clock -name rename_query_clock -period 10 [get_ports clock]
    report_timing_summary -delay_type min_max -file [file join $out ${kind}_summary_10ns.rpt]
    report_timing -max_paths 80 -nworst 1 -file [file join $out ${kind}_endpoints_10ns.rpt]
    foreach {family pattern} [list scoreboard $backend/ready*_reg*/D \
        ras $core/returnStack/entries*_reg*/D prf $backend/values*_reg*/D \
        rob $backend/ledger/*reg*/D issue_queue $backend/queue*_reg*/D frontend_pc $core/pc_reg*/D \
        fabric platform/*/owners/*reg*/CE] {
        set endpoints [get_pins -quiet -hier -filter "NAME =~ $pattern"]
        puts "RENAME_STAGE: $kind family=$family endpoints=[llength $endpoints]"
        if {[llength $endpoints]} {
            report_timing -to $endpoints -max_paths 5 -nworst 1 -file [file join $out ${kind}_${family}_10ns.rpt]
        }
    }
    close_design
}
