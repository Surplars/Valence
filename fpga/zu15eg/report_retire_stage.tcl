# Read-only real-ROM checkpoint queries. No synth/place/route/clock-IP changes.
if {$argc ni {3 4}} {error "Expected BASELINE_DCP CANDIDATE_DCP OUT_DIRECTORY ?candidate-only?"}
lassign $argv baseline candidate out
set kinds {baseline candidate}
if {$argc == 4} {
    if {[lindex $argv 3] ne "candidate-only"} {error "Unknown report subset"}
    set kinds {candidate}
}
file mkdir $out
set_param general.maxThreads 8
set core platform/core/core/core
set backend $core/backend
foreach kind $kinds {
    open_checkpoint [set $kind]
    if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Functional black box remains"}
    if {[llength [get_clocks -quiet]]} {error "Expected clock-free checkpoint"}
    create_clock -name retire_query_clock -period 20 [get_ports clock]
    set faults [get_pins -quiet -hier -filter "NAME =~ $backend/branch*/io_misaligned"]
    set commits [get_pins -quiet -hier -filter "NAME =~ $backend/ledger/io_commit_*_valid"]
    if {![llength $faults] || ![llength $commits]} {error "Missing fault/retirement boundary"}
    set paths [get_timing_paths -quiet -through $faults -through $commits -max_paths 1]
    puts "RETIRE_STAGE: $kind branch_alignment_to_commit_valid direct_paths=[llength $paths]"
    if {$kind eq "candidate" && [llength $paths]} {error "Branch alignment still gates immediate retirement"}
    if {[llength $paths]} {
        report_timing -through $faults -through $commits -max_paths 5 -file [file join $out ${kind}_alignment_to_retirement.rpt]
    }
    if {$kind eq "candidate"} {
        # Vivado uniquifies duplicated instance references with suffixes.
        set compares [get_cells -quiet -hier -filter {REF_NAME =~ BalancedBranchCompare*}]
        puts "RETIRE_STAGE: candidate balanced_compare_modules=[llength $compares]"
        foreach compare $compares {puts "RETIRE_STAGE: comparator $compare ref=[get_property REF_NAME $compare]"}
        if {[llength $compares] != 2} {error "Missing per-lane balanced comparators"}
    }
    report_timing -max_paths 80 -nworst 1 -file [file join $out ${kind}_endpoints_20ns.rpt]
    reset_timing
    create_clock -name retire_query_clock -period 10 [get_ports clock]
    report_timing_summary -delay_type min_max -file [file join $out ${kind}_summary_10ns.rpt]
    foreach {family pattern} [list scoreboard $backend/ready*_reg*/D \
        ras_data $core/returnStack/entries*_reg*/D ras_enable $core/returnStack/entries*_reg*/CE \
        ras_control $core/returnStack/count*_reg*/D prf $backend/values*_reg*/D \
        rob $backend/ledger/*reg*/D issue_queue $backend/queue*_reg*/D frontend_pc $core/pc_reg*/D \
        fabric platform/*/owners/*reg*/CE] {
        set endpoints [get_pins -quiet -hier -filter "NAME =~ $pattern"]
        puts "RETIRE_STAGE: $kind family=$family endpoints=[llength $endpoints]"
        if {[llength $endpoints]} {
            report_timing -to $endpoints -max_paths 5 -nworst 1 -file [file join $out ${kind}_${family}_10ns.rpt]
        }
    }
    close_design
}
