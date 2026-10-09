#!/usr/bin/env tclsh
# Independent raw-DTM host tests; shared model contains no DUT definitions.
source [file join [file dirname [info script]] ram-loader-test-model.tcl]

test crc_standard_vectors {
    assert {[valence_ram::crc32 "123456789"] == 0xcbf43926}
    assert {[valence_ram::crc32 ""] == 0}
    assert {[valence_ram::crc32 [binary format H* 00010203ff80]] == 0x5a718093}
}
test happy_little_endian_full_readback {
    set result [valence_download_and_run [image_file 0001020380ff55aa] 0x80200004]
    assert {[dict get $result state] == "commit_accepted"}
    assert {$model::state(writes) == 2 && $model::state(reads) == 2}
    assert {$model::memory(2149580800) == 0x03020100}
    assert {$model::memory(2149580804) == 0xaa55ff80}
    assert {$model::state(commit_count) == 1 && $model::state(hard_resets) == 0}
    assert {$model::metadata(67) == 0x80200004 && $model::metadata(68) == 8}
}
test odd_length_padding_original_crc {
    set file [image_file 1122334480]
    set result [valence_download_and_run $file 0x80200004]
    assert {[dict get $result bytes] == 5 && [dict get $result padded_bytes] == 8}
    assert {$model::memory(2149580804) == 0x80}
    assert {$model::metadata(69) == 0xce197c72}
}
test one_byte_image {
    valence_download_and_run [image_file ff] 0x80200000
    assert {$model::state(writes) == 1 && $model::state(reads) == 1}
    assert {$model::memory(2149580800) == 255}
}
test all_byte_values_binary_file {
    set bytes ""; for {set n 0} {$n < 256} {incr n} {append bytes [format %02x $n]}
    valence_download_and_run [image_file $bytes] 0x80200000
    assert {$model::metadata(69) == 0x29058c73}
    assert {$model::state(writes) == 64 && $model::state(reads) == 64}
}
test dmi_busy_nop_no_duplicate_write {
    set model::state(delay) 100
    valence_download_and_run [image_file 89abcdef01234567] 0x80200000
    assert {$model::state(soft_resets) > 0 && $model::state(hard_resets) == 0}
    assert {$model::state(writes) == 2 && $model::state(commit_count) == 1}
    set data_writes 0
    foreach request $model::requests {if {[lindex $request 0] == 2 && [lindex $request 1] == 60} {incr data_writes}}
    assert {$data_writes == 2}
}
test dmi_busy_then_failed_response {
    set model::state(delay) 100; set model::state(fail_address) 57; set model::state(fail_op) 2
    fails {valence_download_and_run [image_file 11223344] 0x80200000} {*DMI failed*}
    assert {$model::state(writes) == 0 && $model::state(commit_count) == 0}
    assert {$model::state(soft_resets) > 0}
}
test dmi_failure_not_retried {
    set model::state(fail_address) 60; set model::state(fail_op) 2
    fails {valence_download_and_run [image_file 11223344] 0x80200000} {*DMI failed*}
    set before [llength $model::requests]
    fails {valence_download_and_run [image_file 11223344] 0x80200000} {*Previous transport outcome uncertain*}
    assert {[llength $model::requests] == $before && $model::state(commit_count) == 0}
}
test sb_busy_poll {
    set model::state(sb_delay) 3
    valence_download_and_run [image_file aabbccdd] 0x80200000
    assert {$model::state(writes) == 1 && $model::state(reads) == 1}
}
test sb_busy_timeout_no_automatic_abort {
    set model::state(sb_delay) 10000
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*SBA busy timeout*}
    assert {$model::state(abort_count) == 0 && $model::state(commit_count) == 0 && $model::state(sb_busy)}
}
test sb_error {
    set model::state(sb_error) 2
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*SBA sberror=2*}
    assert {$model::state(writes) == 0 && $model::state(commit_count) == 0}
}
test sb_write_error_prevents_commit {
    set model::state(bus_error_kind) write
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*SBA sberror=2*}
    assert {$model::state(writes) == 0 && $model::state(commit_count) == 0}
}
test sb_read_error_prevents_metadata {
    set model::state(bus_error_kind) read
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*SBA sberror=2*}
    assert {$model::state(writes) == 1 && $model::state(commit_count) == 0 && [array size model::metadata] == 0}
}
test sb_timeout_blocks_implicit_retry {
    set model::state(sb_delay) 10000
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*SBA busy timeout*}
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*Previous transport outcome uncertain*}
    assert {$model::state(commit_count) == 0 && $model::state(abort_count) == 0}
}
test explicit_abort_after_timed_out_bus {
    set model::state(sb_delay) 10000
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*SBA busy timeout*}
    set model::state(sb_remaining) 1
    assert {[dict get [valence_abort] state] == "cancelled"}
    assert {$model::state(abort_count) == 1 && !$model::state(sb_busy)}
}
test explicit_abort_after_failed_dmi {
    set model::state(fail_address) 60; set model::state(fail_op) 2
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*DMI failed*}
    set model::state(fail_address) -1
    assert {[dict get [valence_abort] state] == "cancelled"}
    assert {$model::state(abort_count) == 1 && $model::state(hard_resets) == 0}
}
test sb_busyerror {
    set model::state(sb_busyerror) 1
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*SBA sbbusyerror*}
    assert {$model::state(writes) == 0}
}
test unarmed_cannot_touch_memory {
    set model::state(status) 0x20
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*not ARMED*}
    assert {$model::state(writes) == 0 && $model::state(reads) == 0}
}
test link_down {
    set model::state(status) 1
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*link is down*}
    assert {$model::state(writes) == 0}
}
test wrong_id {
    set model::state(id) 3
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*Unexpected IDCODE*}
    assert {[llength $model::requests] == 0}
}
test wrong_dtm_abits {
    set model::state(dtmcs) 0x7061
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*Unsupported DTMCS*}
}
test wrong_capability {
    set model::state(cap) 0x564c0102
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*capability/version mismatch*}
}
test wrong_sb_capability {
    set model::state(cap_override) 0x20000804
    fails {valence_download_and_run [image_file aabbccdd] 0x80200000} {*Unsupported SBCS*}
}
test empty {
    fails {valence_download_and_run [image_file ""] 0x80200000} {*Image is empty*}
    assert {[llength $model::requests] == 0}
}
test entry_unaligned {
    fails {valence_download_and_run [image_file 11223344] 0x80200002} {*4-byte aligned*}
    assert {$model::state(writes) == 0}
}
test entry_before_base {
    fails {valence_download_and_run [image_file 11223344] 0x801ffffc} {*outside the logical image*}
    assert {$model::state(writes) == 0}
}
test entry_after_logical_image {
    fails {valence_download_and_run [image_file 11223344] 0x80200004} {*outside the logical image*}
    assert {$model::state(writes) == 0}
}
test entry_uint32_overflow {
    fails {valence_download_and_run [image_file 11223344] 0x180200000} {*outside the unsigned 32-bit range*}
}
test image_outside_ram {
    set model::state(end) 0x80200004
    fails {valence_download_and_run [image_file 1122334455] 0x80200000} {*including final-word padding*}
    assert {$model::state(writes) == 0}
}
test invalid_ram_end {
    set model::state(end) 0x80200003
    fails {valence_download_and_run [image_file 11] 0x80200000} {*Invalid advertised RAM interval*}
}
test generation_change_prevents_metadata_commit {
    set model::state(gen_after_writes) 1
    fails {valence_download_and_run [image_file 112233445566778899] 0x80200000} {*generation changed*}
    assert {$model::state(writes) <= 2 && $model::state(commit_count) == 0 && [array size model::metadata] == 0}
}
test armed_loss_prevents_commit {
    set model::state(armed_after_writes) 1
    fails {valence_download_and_run [image_file 11223344] 0x80200000} {*not ARMED*}
    assert {$model::state(commit_count) == 0}
}
test corrupted_readback_prevents_commit {
    set model::state(corrupt_address) 0x80200000
    fails {valence_download_and_run [image_file 1122334455] 0x80200000} {*Readback mismatch*COMMIT not sent*}
    assert {$model::state(commit_count) == 0 && [array size model::metadata] == 0}
}
test explicit_abort {
    set result [valence_abort]
    assert {[dict get $result state] == "cancelled" && $model::state(abort_count) == 1}
    assert {$model::state(hard_resets) == 0}
}
test abort_busy_reports_drain {
    set model::state(abort_hold_busy) 1
    fails {valence_abort} {*bus drain is still BUSY*}
    assert {$model::state(abort_count) == 1}
}
test abort_after_claim_refused {
    set model::state(status) 0x62
    fails {valence_abort} {*already CLAIMED*}
    assert {$model::state(abort_count) == 0}
}
test commit_failure_never_replayed {
    set model::state(commit_fail) 1
    fails {valence_download_and_run [image_file 11223344] 0x80200000} {*DMI failed*}
    assert {$model::state(commit_count) == 1}
}
test commit_timeout_never_replayed {
    set model::state(commit_timeout) 1
    fails {valence_download_and_run [image_file 11223344] 0x80200000} {*outcome uncertain*}
    assert {$model::state(commit_count) == 1 && $model::state(abort_count) == 0}
    fails {valence_download_and_run [image_file 11223344] 0x80200000} {*Previous transport outcome uncertain*}
    assert {$model::state(commit_count) == 1}
}
test rearm_at_commit_rejects_stale_epoch_token {
    set model::state(rearm_at_commit) 1
    fails {valence_download_and_run [image_file 11223344] 0x80200000} {*DMI failed*}
    assert {$model::state(commit_count) == 1 && $model::metadata(73) == 9 && $model::state(epoch) == 10}
}
test rapidly_claimed_commit_is_accepted {
    set model::state(commit_claim) 1
    valence_download_and_run [image_file 11223344] 0x80200000
    assert {[dict get [valence_wait_claimed] state] == "claimed"}
    assert {$model::state(commit_count) == 1}
}
test claimed_observed_separately {
    valence_download_and_run [image_file 11223344] 0x80200000
    set model::state(force_claim) 1
    assert {[dict get [valence_wait_claimed] state] == "claimed"}
}
test claim_timeout_no_abort {
    valence_download_and_run [image_file 11223344] 0x80200000
    fails {valence_wait_claimed} {*CLAIM was not observed*}
    assert {$model::state(abort_count) == 0 && $model::state(commit_count) == 1}
}
test adapter_error_latches_uncertain {
    valence_ram::start
    set model::state(scan_fault) 1
    fails {valence_ram::wr 0x42 2} {*adapter I/O failure*}
    set model::state(scan_fault) 0
    fails {valence_ram::wr 0x42 2} {*Transport outcome uncertain*}
}
test jim_minimal_byte_primitives_no_binary_dependency {
    set file [image_file c3a900ffe282ac80]
    # Emulate only Jim's byte APIs in stock Tcl, retaining a separate host-only
    # binary command for the independent unpack stub. Not a real Jim runtime.
    rename ::binary ::test_host_binary
    proc ::unpack {bytes kind bitpos width} {
        if {$kind != "-uintle" || $width != 8 || ($bitpos % 8)} {error "Wrong Jim unpack call"}
        ::test_host_binary scan [::string index $bytes [expr {$bitpos / 8}]] c value
        return [expr {$value & 255}]
    }
    proc ::valence_ram::string {subcommand args} {
        if {$subcommand == "bytelength"} {return [::string length [lindex $args 0]]}
        return [uplevel 1 [linsert $args 0 ::string $subcommand]]
    }
    set valence_ram::jim_bytes 1
    set code [catch {
        valence_download_and_run $file 0x80200000
        assert {$model::memory(2149580800) == 0xff00a9c3}
        assert {$model::memory(2149580804) == 0x80ac82e2}
        assert {$model::metadata(69) == 0xf891f814}
    } message]
    set valence_ram::jim_bytes 0
    rename ::valence_ram::string {}; rename ::unpack {}
    rename ::test_host_binary ::binary
    if {$code} {error $message}
}
finish "RAM loader host tests"
