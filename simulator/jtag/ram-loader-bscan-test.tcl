#!/usr/bin/env tclsh
# Independent USER transport model + shared independent DMI/SBA endpoint model.
source [file join [file dirname [info script]] ram-loader-test-model.tcl]
source [file join [file dirname [info script]] ram-loader-bscan.tcl]
rename model::reset model::raw_reset
proc model::reset {} {
    raw_reset
    variable state
    array set state {
        b_id 0x14750093 b_magic 0x5642 b_version 1 b_cap 0x701
        b_updated 0 b_pending 0 b_remaining 0 b_error 0 b_done 0
        b_status 0 b_data 0 b_address 0 b_op 0 b_value 0 b_target 0
        b_response_status 0 b_response_data 0 b_delay 0 b_clears 0 b_controls 0
        b_hard_resets 0 b_polls 0 b_submit 0 b_stuck 0 b_bad_echo 0 b_ir_scans 0 b_idle_calls 0
    }
    set ::valence_ram::backend bscan
    set ::valence_ram::tap mock_fpga.tap
    set ::valence_ram::user_ir 0x903
    set ::valence_ram::fpga_part xczu15eg-ffvb1156-2-i
    set ::valence_ram::fpga_irlen 12
    set ::valence_ram::jtag_chain 2
    set ::valence_ram::fpga_id_mask 0x0fffffff
    set ::valence_ram::fpga_id 0x04750093
}
proc jtag {subcommand tap option} {
    if {$subcommand != "cget" || $tap != "mock_fpga.tap" || $option != "-idcode"} {error "Wrong FPGA ID query"}
    return $model::state(b_id)
}
rename irscan raw_irscan
proc irscan {tap instruction args} {
    if {$tap != "mock_fpga.tap" || $instruction != $::valence_ram::user_ir} {error "Wrong physical FPGA TAP/USER instruction"}
    incr model::state(b_ir_scans)
}
rename runtest raw_runtest
proc runtest {cycles} {
    upvar #0 model::state s
    incr s(b_idle_calls)
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

# Independent known-part guards: all bad inputs must fail before the first IR scan.
foreach {name variable value pattern} {
    wrong_part fpga_part xczu9eg-ffvb1156-2-i {*reviewed BSDL profile*}
    missing_part fpga_part {} {*Explicit VALENCE_RAM_FPGA_PART*}
    wrong_irlen fpga_irlen 6 {*12-bit FPGA IR*}
    soft_irlen fpga_irlen 5 {*12-bit FPGA IR*}
    missing_chain jtag_chain -1 {*2..4*}
    user1_collision jtag_chain 1 {*USER1 is occupied*}
    truncated_user2 user_ir 0x03 {*full 12-bit opcode 0x903*}
    inner_dmi_opcode user_ir 0x11 {*full 12-bit opcode 0x903*}
    wrong_chain_opcode user_ir 0x922 {*full 12-bit opcode 0x903*}
    oversized_opcode user_ir 0x1903 {*full 12-bit opcode 0x903*}
    wrong_part_id fpga_id 0x04711093 {*BSDL identity*}
    overbroad_idmask fpga_id_mask 0x00000fff {*28 BSDL fixed bits*}
    overwide_id fpga_id 0x104750093 {*outside the unsigned 32-bit range*}
} {
    test bscan_guard_$name [list apply [list {variable value pattern} {
        set ::valence_ram::$variable $value
        fails {valence_ram::start} $pattern
        assert {$model::state(b_ir_scans) == 0 && $model::state(b_submit) == 0 && $model::state(b_idle_calls) == 0}
    }] $variable $value $pattern]
}
foreach {chain opcode} {2 0x903 3 0x922 4 0x923} {
    test bscan_exact_user$chain [list apply [list {chain opcode} {
        set ::valence_ram::jtag_chain $chain
        set ::valence_ram::user_ir $opcode
        valence_download_and_run [image_file 01020304] 0x80200000
        assert {$model::state(writes) == 1 && $model::state(commit_count) == 1}
    }] $chain $opcode]
}
test bscan_bsdl_revision_wildcard {
    set model::state(b_id) 0xf4750093
    valence_download_and_run [image_file 01020304] 0x80200000
    assert {$model::state(commit_count) == 1}
}
test bscan_observed_fixed_id_bit_rejected {
    set model::state(b_id) 0x14750091
    fails {valence_ram::start} {*Unexpected FPGA IDCODE*}
    assert {$model::state(b_ir_scans) == 0 && $model::state(b_submit) == 0 && $model::state(b_idle_calls) == 0}
}
test bscan_mutation_after_start_rejected {
    valence_ram::start
    set before $model::state(b_ir_scans)
    set valence_ram::user_ir 0x3
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*full 12-bit opcode*}
    assert {$model::state(b_ir_scans) == $before}
}

# Exhaust the BSDL mask rather than importing a DUT/profile constant.
for {set revision 0} {$revision < 16} {incr revision} {
    test bscan_revision_$revision [list apply [list {revision} {
        set model::state(b_id) [expr {($revision << 28) | 0x04750093}]
        valence_ram::start
        assert {$model::state(b_ir_scans) > 0}
    }] $revision]
}
for {set bit 0} {$bit < 28} {incr bit} {
    foreach location {expected observed} {
        test bscan_fixed_${location}_bit$bit [list apply [list {bit location} {
            set wrong [expr {0x04750093 ^ (1 << $bit)}]
            if {$location eq "expected"} {
                set valence_ram::fpga_id $wrong
                fails {valence_ram::start} {*BSDL identity*}
            } else {
                set model::state(b_id) $wrong
                fails {valence_ram::start} {*Unexpected FPGA IDCODE*}
            }
            assert {$model::state(b_ir_scans) == 0 && $model::state(b_idle_calls) == 0}
        }] $bit $location]
    }
}
foreach {chain correct wrong} {
    2 0x903 0x02 2 0x903 0x03 2 0x903 0x922 2 0x903 0x923
    3 0x922 0x22 3 0x922 0x903 3 0x922 0x923
    4 0x923 0x23 4 0x923 0x903 4 0x923 0x922
} {
    test bscan_opcode_pair_${chain}_$wrong [list apply [list {chain wrong} {
        set valence_ram::jtag_chain $chain
        set valence_ram::user_ir $wrong
        fails {valence_ram::start} {*full 12-bit opcode*}
        assert {$model::state(b_ir_scans) == 0 && $model::state(b_idle_calls) == 0}
    }] $chain $wrong]
}
test bscan_observed_id_overwide {
    set model::state(b_id) 0x104750093
    fails {valence_ram::start} {*outside the unsigned 32-bit range*}
    assert {$model::state(b_ir_scans) == 0 && $model::state(b_idle_calls) == 0}
}

foreach entrypoint {dmi wait_claimed raw_scan collect} {
    test bscan_started_user1_mutation_$entrypoint [list apply [list {entrypoint} {
        valence_ram::start
        set before_ir $model::state(b_ir_scans)
        set before_idle $model::state(b_idle_calls)
        set valence_ram::committed_generation 9
        set valence_ram::user_ir 0x902
        set valence_ram::jtag_chain 1
        switch -- $entrypoint {
            dmi {fails {valence_ram::rd 0x40} {*USER1 is occupied*}}
            wait_claimed {fails {valence_wait_claimed} {*USER1 is occupied*}}
            raw_scan {fails {valence_ram::bscan_scan 0 0 0} {*USER1 is occupied*}}
            collect {fails {valence_ram::bscan_collect test} {*USER1 is occupied*}}
        }
        assert {$model::state(b_ir_scans) == $before_ir && $model::state(b_idle_calls) == $before_idle}
    }] $entrypoint]
}
finish "BSCANE2 USER loader host tests"
