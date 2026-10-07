# Read-only structural cuts and endpoint families. Reuses two real-ROM DCPs.
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
    create_clock -name execute_query_clock -period 20 [get_ports clock]
    if {$kind eq "baseline"} {set ras $core/entries*_reg*/D} else {set ras $core/returnStack/entries*_reg*/D}
    set checks [list \
        [list alu_result_to_ras [pins_at $backend/alu/io_result*] [pins_at $ras] to] \
        [list lsu_credit_to_alu_right [pins_at $backend/lsu/io_issueAvailable] \
            [pins_at $backend/alu/io_right*] through]]
    foreach check $checks {
        lassign $check name from to mode
        if {$mode eq "to"} {
            set paths [get_timing_paths -quiet -through $from -to $to -max_paths 1]
        } else {
            set paths [get_timing_paths -quiet -through $from -through $to -max_paths 1]
        }
        puts "EXECUTE_STAGE: $kind $name direct_paths=[llength $paths]"
        if {$kind eq "candidate" && [llength $paths]} {error "Requested execute cut remains: $name"}
        if {[llength $paths]} {
            if {$mode eq "to"} {
                report_timing -through $from -to $to -max_paths 5 -file [file join $out ${kind}_${name}.rpt]
            } else {
                report_timing -through $from -through $to -max_paths 5 -file [file join $out ${kind}_${name}.rpt]
            }
        }
    }
    report_timing -max_paths 80 -nworst 1 -file [file join $out ${kind}_endpoints_20ns.rpt]
    reset_timing
    create_clock -name execute_query_clock -period 10 [get_ports clock]
    report_timing_summary -delay_type min_max -file [file join $out ${kind}_summary_10ns.rpt]
    report_timing -max_paths 80 -nworst 1 -file [file join $out ${kind}_endpoints_10ns.rpt]
    # Do not let replicated RAS endpoints hide the next independent path classes.
    foreach {family pattern} [list ras $ras prf $backend/values*_reg*/D \
        rob $backend/ledger/*reg*/D issue_queue $backend/queue*_reg*/D \
        frontend_pc $core/pc_reg*/D fabric platform/*/owners/*reg*/CE] {
        set endpoints [get_pins -quiet -hier -filter "NAME =~ $pattern"]
        puts "EXECUTE_STAGE: $kind family=$family endpoints=[llength $endpoints]"
        if {[llength $endpoints]} {
            report_timing -to $endpoints -max_paths 5 -nworst 1 \
                -file [file join $out ${kind}_${family}_10ns.rpt]
        }
    }
    close_design
}
