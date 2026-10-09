#!/usr/bin/env tclsh
# Script-command census in independent zero-latency mock; never a board rate.
source [file join [file dirname [info script]] ram-loader-test-model.tcl]
puts "Direct DTM script scan census (one TAP, IR=5, no added busy stalls, full readback, chunk=256 words):"
foreach size {256 4096} {
    model::reset
    set valence_ram::chunk_words 256
    set model::state(end) [expr {0x80200000 + $size}]
    set file [image_file [string repeat a5 $size]]
    valence_download_and_run $file 0x80200000
    set transitions [expr {6*$model::state(ir_scans) + 5*$model::state(dr_scans)}]
    set clocks [expr {$model::state(shifted_bits) + $model::state(idle_tck) + $transitions}]
    puts "bytes=$size DMI_requests=[llength $model::requests] IR_scans=$model::state(ir_scans) DR_scans=$model::state(dr_scans) shifted_bits=$model::state(shifted_bits) idle_TCK=$model::state(idle_tck) ideal_single_TAP_TCK=$clocks"
}
puts "Counts include initialization, metadata and one COMMIT. Ideal TCK includes shortest RUN/IDLE scan transitions. It excludes USB/Tcl/adapter latency, extra chain TAPs, busy stalls, ROM CRC and guest execution. No hardware throughput claim."
file delete -force $work
