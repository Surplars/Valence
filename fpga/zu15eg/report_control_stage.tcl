# Reuse two full real-ROM SoC checkpoints; no synthesis or implementation.
if {$argc != 3} {error "Expected BASELINE_DCP CANDIDATE_DCP OUT_DIRECTORY"}
lassign $argv baseline candidate out
file mkdir $out
set_param general.maxThreads 8
proc pins_at {pattern} {
    set pins [get_pins -quiet -hier -filter "NAME =~ $pattern"]
    if {![llength $pins]} {error "Missing boundary $pattern"}
    return $pins
}
set root platform/core/core/core/backend
foreach kind {baseline candidate} {
    open_checkpoint [set $kind]
    if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Unresolved functional black box"}
    if {[llength [get_clocks -quiet]]} {error "Expected clock-free SoC checkpoint"}
    create_clock -name control_query_clock -period 20 [get_ports clock]
    set checks [list \
        [list completion_to_recovery [pins_at $root/multiplier/io_complete_valid] \
            [pins_at $root/ledger/io_recoveryAccepted]] \
        [list invalidate_to_page_metadata [pins_at $root/io_invalidateFetch] \
            [pins_at platform/frontend/io_instructionPageFaults_0]] \
        [list destination0_to_lane1_admission [pins_at $root/ledger/io_renamed_0_bits_destination*] \
            [pins_at $root/ledger/io_renamed_1_valid]]]
    foreach check $checks {
        lassign $check name from to
        set paths [get_timing_paths -quiet -through $from -through $to -max_paths 1]
        puts "CONTROL_STAGE: $kind $name direct_paths=[llength $paths]"
        if {$kind eq "candidate" && [llength $paths]} {
            error "Candidate retains requested control dependency $name"
        }
        if {[llength $paths]} {
            report_timing -through $from -through $to -max_paths 5 \
                -file [file join $out ${kind}_${name}.rpt]
        }
    }
    report_timing -max_paths 10 -file [file join $out ${kind}_worst.rpt]
    close_design
}
