#!/usr/bin/env tclsh
# Independent USER transport model + shared independent DMI/SBA endpoint model.
source [file join [file dirname [info script]] ram-loader-test-model.tcl]
source [file join [file dirname [info script]] ram-loader-bscan.tcl]
rename model::reset model::raw_reset
proc model::reset {} {
    raw_reset
    variable state
    array set state {
        b_id 0x14711093 b_magic 0x5642 b_version 1 b_cap 0x701
        b_updated 0 b_pending 0 b_remaining 0 b_error 0 b_done 0
        b_status 0 b_data 0 b_address 0 b_op 0 b_value 0 b_target 0
        b_response_status 0 b_response_data 0 b_delay 0 b_clears 0 b_controls 0
        b_hard_resets 0 b_polls 0 b_submit 0 b_stuck 0 b_bad_echo 0
    }
    set ::valence_ram::backend bscan
    set ::valence_ram::tap mock_fpga.tap
    set ::valence_ram::user_ir 2
    set ::valence_ram::fpga_id 0x14711093
}
proc jtag {subcommand tap option} {
    if {$subcommand != "cget" || $tap != "mock_fpga.tap" || $option != "-idcode"} {error "Wrong FPGA ID query"}
    return $model::state(b_id)
}
rename irscan raw_irscan
proc irscan {tap instruction args} {
    if {$tap != "mock_fpga.tap" || $instruction != 2} {error "Wrong physical FPGA TAP/USER instruction"}
}
rename runtest raw_runtest
proc runtest {cycles} {
    upvar #0 model::state s
    if {$cycles < 8} {error "USER needs >=8 clocks after UPDATE"}
    if {$s(b_updated)} {
        set s(b_updated) 0; set s(b_done) 0
        if {$s(b_op) == 3} {
            incr s(b_controls)
            switch -- $s(b_target) {
                0 {set s(b_status) 0; set s(b_data) $s(b_cap); set s(b_address) 0; set s(b_done) 1}
                1 {incr s(b_clears); set s(b_error) 0; set s(b_status) 0; set s(b_data) 0; set s(b_done) 0}
                2 {incr s(b_hard_resets); error "Forbidden USER hard reset"}
                default {set s(b_error) 1}
            }
        } else {
            lassign [model::access $s(b_op) $s(b_target) $s(b_value)] s(b_response_status) s(b_response_data)
            set s(b_pending) 1; set s(b_remaining) $s(b_delay)
            if {$s(commit_timeout) && $s(b_op) == 2 && $s(b_target) == 66 && $s(b_value) == 2} {set s(b_stuck) 1}
        }
    }
    if {$s(b_pending) && !$s(b_stuck)} {
        incr s(b_remaining) -$cycles
        if {$s(b_remaining) <= 0} {
            set s(b_pending) 0; set s(b_done) 1
            set s(b_status) $s(b_response_status); set s(b_data) $s(b_response_data)
            set s(b_address) [expr {$s(b_target) ^ $s(b_bad_echo)}]
        }
    }
}
rename drscan raw_drscan
proc drscan {tap args} {
    upvar #0 model::state s
    if {$tap != "mock_fpga.tap" || [llength $args] != 12} {error "Wrong USER scan framing"}
    set fields {}
    foreach {bits value} $args expected {2 32 7 3 4 16} {
        if {$bits != $expected} {error "USER scan field width mismatch"}
        lappend fields [expr {$value + 0}]
    }
    if {[lindex $fields 3] != 0 || [lindex $fields 4] != 1 || [lindex $fields 5] != 0x5642} {error "Malformed host USER header"}
    set busy [expr {$s(b_updated) || $s(b_pending)}]
    set flags [expr {$s(b_done) | ($busy << 1) | ($s(b_error) << 2)}]
    if {$busy} {set status 3} else {set status $s(b_status)}
    set result [list [format %x $status] [format %08x $s(b_data)] [format %02x $s(b_address)] [format %x $flags] [format %x $s(b_version)] [format %04x $s(b_magic)]]
    set op [lindex $fields 0]
    if {$op == 0} {incr s(b_polls)} else {
        incr s(b_submit)
        set address [lindex $fields 2]
        if {$busy || ($s(b_error) && !($op == 3 && $address == 1))} {set s(b_error) 1} else {
            set s(b_updated) 1; set s(b_op) $op; set s(b_target) $address; set s(b_value) [lindex $fields 1]
        }
    }
    return $result
}

test bscan_happy_odd_file {
    set result [valence_download_and_run [image_file 0102030480] 0x80200004]
    assert {[dict get $result bytes] == 5}
    assert {$model::state(writes) == 2 && $model::state(reads) == 2}
    assert {$model::memory(2149580800) == 0x04030201 && $model::memory(2149580804) == 128}
    assert {$model::metadata(73) == 9 && $model::state(commit_count) == 1}
    assert {$model::state(b_hard_resets) == 0 && $model::state(b_error) == 0}
}
test bscan_busy_no_duplicate_write {
    set model::state(b_delay) 100
    valence_download_and_run [image_file aabbccdd] 0x80200000
    assert {$model::state(writes) == 1 && $model::state(reads) == 1 && $model::state(commit_count) == 1}
    assert {$model::state(b_polls) > $model::state(b_submit)}
}
test bscan_busy_then_endpoint_failure {
    set model::state(b_delay) 100; set model::state(fail_address) 60; set model::state(fail_op) 2
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*DMI failed*}
    assert {$model::state(writes) == 0 && $model::state(commit_count) == 0}
}
test bscan_bad_fpga_id {
    set model::state(b_id) 1
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*Unexpected FPGA IDCODE*}
    assert {$model::state(b_submit) == 0}
}
test bscan_bad_signature {
    set model::state(b_magic) 0xffff
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*signature/version mismatch*}
    assert {$model::state(b_submit) == 0}
}
test bscan_bad_version {
    set model::state(b_version) 2
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*signature/version mismatch*}
}
test bscan_bad_capability {
    set model::state(b_cap) 0x801
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*USER capability mismatch*}
    assert {[llength $model::requests] == 0}
}
test bscan_no_board_defaults {
    set valence_ram::user_ir -1
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*requires board-supplied*}
    assert {$model::state(b_submit) == 0}
}
test bscan_stale_error_cleared_idle_only {
    set model::state(b_error) 1
    valence_download_and_run [image_file aabbccdd] 0x80200000
    assert {$model::state(b_clears) == 1 && $model::state(b_hard_resets) == 0}
}
test bscan_request_into_busy_forbidden {
    valence_ram::start
    set model::state(b_pending) 1; set model::state(b_stuck) 1
    set before $model::state(b_submit)
    fails {valence_ram::wr 0x42 2} {*not ready*no request submitted*}
    assert {$model::state(b_submit) == $before}
}
test bscan_response_address_mismatch {
    set model::state(b_bad_echo) 1
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*response address mismatch*}
    assert {$model::state(commit_count) == 0}
}
test bscan_commit_timeout_once {
    set model::state(commit_timeout) 1
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*USER response timeout*}
    assert {$model::state(commit_count) == 1 && $model::state(abort_count) == 0}
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*Previous transport outcome uncertain*}
    assert {$model::state(commit_count) == 1}
}
test bscan_abort_drains_without_resets {
    valence_abort
    assert {$model::state(abort_count) == 1 && $model::state(b_hard_resets) == 0}
}
test bscan_abort_cannot_replay_timed_out_commit {
    set model::state(commit_timeout) 1
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*USER response timeout*}
    fails {valence_abort} {*Initial USER transport drain*timeout*}
    assert {$model::state(commit_count) == 1 && $model::state(abort_count) == 0 && $model::state(b_hard_resets) == 0}
}
test bscan_claimed {
    set model::state(commit_claim) 1
    valence_download_and_run [image_file aabbccdd] 0x80200000
    assert {[dict get [valence_wait_claimed] state] == "claimed"}
}
finish "BSCANE2 USER loader host tests"
