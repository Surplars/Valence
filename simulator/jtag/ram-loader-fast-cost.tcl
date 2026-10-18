#!/usr/bin/env tclsh
# Command counts only. Never a USB/adapter/board throughput claim.
set ::VALENCE_BSCAN_TEST_MODEL_ONLY 1
source [file join [file dirname [info script]] ram-loader-bscan-test.tcl]
unset ::VALENCE_BSCAN_TEST_MODEL_ONLY
foreach mode {safe fast} {
    foreach size {4096 29296} {
        ::model::reset
        set ::valence_ram::chunk_words 256
        set ::model::state(end) [expr {0x80200000 + $size}]
        ::valence_download_and_run [image_file [string repeat a5 $size]] 0x80200000 $mode
        assert {$::model::state(reads) == $size/4 && $::model::state(writes) == $size/4 && $::model::state(commit_count) == 1}
        puts "CENSUS mode=$mode bytes=$size dmi=[llength $::model::requests] ir=$::model::state(b_ir_scans) dr=$::model::state(b_dr_scans) idle_calls=$::model::state(b_idle_calls) idle_tck=$::model::state(b_idle_tck)"
    }
}
finish "BSCAN command census (not a hardware rate)"
