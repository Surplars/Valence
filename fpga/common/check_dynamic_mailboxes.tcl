# Read-only targeted structural check, not a replacement for full post_synth.
# Arguments: original_raw.dcp frozen_root repaired_common_cdc.tcl exact_cache.tcl report.txt
if {$argc!=5} {error "Usage: raw.dcp frozen_root repaired_common_cdc.tcl exact_cache.tcl new_report.txt"}
lassign $argv raw frozen checker cache report
foreach path [list $raw $checker $cache [file join $frozen fpga common inactive_zero_state.tcl]] {
    if {![file isfile $path]} {error "Missing input $path"}
}
if {[file exists $report]} {error "Refusing to overwrite $report"}
set out [open $report {WRONLY CREAT EXCL}]
set ::valence(root) [file normalize $frozen]
open_checkpoint $raw
source $checker
source $cache
common_exact_cache::enable
# Use clock objects on exact physical sources from the original raw DCP. The
# full post flow names MAC clocks later; this check must not manufacture clocks.
set clocks {}
foreach {role pin period} {
    cpu cpu_clock/managed_buffer/O 3.333
    fabric fabric_clock/managed_buffer/O 4.0
    fixed u_ddr/inst/u_ddr4_infrastructure/u_bufg_divClk/O 4.0
    mac network_clock/raw_div/O 8.0
    aon u_soc/alwaysOnClock 20.0
} {
    set actual [common_cdc::clock $pin]
    common_cdc::expect_clock $pin $actual $period
    dict set clocks $role $actual
    puts $out [list CLOCK $role $pin $actual $period]
}
if {[dict get $clocks cpu] ne {cpu_target300} || [dict get $clocks fabric] ne {fabric_target250} ||
    [llength [lsort -unique [dict values $clocks]]]!=5} {error "Changed independent CPU300/fabric250 clock identities"}
# Exact source-known collect_dynamic mailbox table, reordered only to exercise
# the currently failing commands and adjacent receipts/observations first.
set rows {
    {u_soc/peripherals/crossing/commands 35 fabric mac}
    {u_soc/peripherals/crossing/receipts 35 mac fabric}
    {u_soc/peripherals/crossing/observations 52 mac fabric}
    {u_soc/peripherals/rateCmu/receipt 1 fabric aon}
    {u_soc/fixedTimer/snapshots 64 fixed fabric}
    {u_soc/debugSequence/boundary/crossing/requests 41 fixed fabric}
    {u_soc/debugSequence/boundary/crossing/responses 34 fabric fixed}
    {u_soc/peripherals/guard/requests 17 aon mac}
    {u_soc/peripherals/guard/replies 18 mac aon}
    {u_soc/ddrQualification/command 10 fabric fixed}
    {u_soc/ddrQualification/observation 9 fixed fabric}
    {u_soc/ddrQualification/terminal 9 fixed fabric}
    {u_soc/ddrQualification/retirement 9 fixed fabric}
    {u_soc/timerQualification/command 10 fabric fixed}
    {u_soc/timerQualification/observation 9 fixed fabric}
    {u_soc/timerQualification/terminal 9 fixed fabric}
    {u_soc/timerQualification/retirement 9 fixed fabric}
    {u_soc/runtime/command 11 aon fabric}
    {u_soc/runtime/cpuArm 10 aon cpu}
    {u_soc/runtime/cpuObservation 12 cpu aon}
    {u_soc/runtime/fabricObservation 12 fabric aon}
    {u_soc/runtime/terminal 9 fabric aon}
    {u_soc/runtime/retirement 8 fabric aon}
    {u_soc/debugSequence/prepare 8 fabric fixed}
    {u_soc/debugSequence/proof 8 fixed fabric}
    {u_soc/debugSequence/decision 9 fabric fixed}
    {u_soc/debugSequence/terminal 9 fixed fabric}
    {u_soc/debugSequence/retirement 8 fixed fabric}
    {u_soc/debugSequence/boundary/probe 8 fixed fabric}
    {u_soc/debugSequence/boundary/proof 8 fabric fixed}
    {u_soc/debugSequence/boundary/release_0 8 fixed fabric}
    {u_soc/debugSequence/boundary/releaseAck 8 fabric fixed}
}
if {[llength $rows]!=32 || [llength [lsort -unique [lmap row $rows {lindex $row 0}]]]!=32} {error "Changed targeted mailbox census"}
set failed {};set passed 0;set index 0
puts $out [list INPUTS raw [file normalize $raw] checker [file normalize $checker] tool [version -short]]
foreach row $rows {
    incr index
    lassign $row h width source destination
    puts "MAILBOX_TARGET_BEGIN $index/32 $h"; flush stdout
    if {[catch {
        set debug u_soc/debugSequence/boundary/crossing
        if {$h in [list $debug/requests $debug/responses]} {
            common_cdc::same_net $h/commonReset $debug/release_0/asyncReset
        } else {common_cdc::same_net $h/commonReset u_soc/commonColdReset}
        set scope [common_cdc::mailbox_width $h $width [dict get $clocks $source] [dict get $clocks $destination]]
    } why options]} {
        lappend failed $h
        puts $out [list FAIL $row $why [dict get $options -errorinfo]]
        puts "MAILBOX_TARGET_FAIL $index/32 $h : $why"
    } else {
        incr passed
        puts $out [list PASS $row $scope]
        puts "MAILBOX_TARGET_PASS $index/32 $h"
    }
    flush $out;flush stdout
}
puts $out [list SUMMARY passed $passed total 32 failed $failed scope STRUCTURAL_MAILBOX_ONLY_NO_TIMING_EXCEPTION_APPLIED]
close $out
if {[llength $failed]} {error "MAILBOX_TARGETED_FAILED $failed"}
puts "MAILBOX_TARGETED_32_STRUCTURAL_PASS FULL_POSTCHECK_STILL_REQUIRED NO_NATIVE_TIMING_OR_RATE_QUALIFICATION"
