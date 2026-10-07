# Additional read-only boundary check: an accepted output may be logic-replicated
# by synthesis, so a 0/0 query through that output is not a cut proof. Query the
# upstream frontend-valid boundary instead. Never synthesize/place/route here.
if {$argc != 3} {error "Expected BASELINE_DCP CANDIDATE_DCP OUT_DIRECTORY"}
lassign $argv baseline candidate out
file mkdir $out
set_param general.maxThreads 8
set core platform/core/core/core
set destination $core/backend/ledger/io_renamed_1_bits_destination*
foreach kind {baseline candidate} {
    open_checkpoint [set $kind]
    if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Functional black box remains"}
    if {[llength [get_clocks -quiet]]} {error "Expected clock-free checkpoint"}
    create_clock -name rename_admission_clock -period 20 [get_ports clock]
    set from [get_pins -quiet -hier -filter "NAME == $core/io_instructions_0_valid"]
    set to [get_pins -quiet -hier -filter "NAME =~ $destination"]
    if {![llength $from] || ![llength $to]} {error "Missing admission boundary"}
    set paths [get_timing_paths -quiet -through $from -through $to -max_paths 1]
    puts "RENAME_ADMISSION: $kind frontend_valid_to_lane1_destination direct_paths=[llength $paths]"
    if {$kind eq "baseline" && ![llength $paths]} {error "Baseline dependency not demonstrated"}
    if {$kind eq "candidate" && [llength $paths]} {error "Admission dependency remains"}
    if {$kind eq "candidate"} {
        set update [get_cells -quiet $core/backend/readyUpdate]
        if {[llength $update] != 1} {error "Missing static ready-update module"}
        set outputs [get_pins -quiet -of_objects $update -filter {DIRECTION == OUT}]
        puts "RENAME_ADMISSION: candidate static_ready_output_pins=[llength $outputs]"
        if {[llength $outputs] != 48} {error "Unexpected compact ready-update width"}
    }
    if {[llength $paths]} {
        report_timing -through $from -through $to -max_paths 5 -file [file join $out ${kind}_frontend_valid_to_lane1_destination.rpt]
    }
    close_design
}
