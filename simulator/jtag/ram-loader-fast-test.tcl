#!/usr/bin/env tclsh
# Independent acceptance of streaming SBA and command-scoped USER leases.
set ::VALENCE_BSCAN_TEST_MODEL_ONLY 1
source [file join [file dirname [info script]] ram-loader-bscan-test.tcl]
unset ::VALENCE_BSCAN_TEST_MODEL_ONLY

foreach mode {fast safe} {
    foreach length {1 4 5 8 9 1023 1024 1025 4096 29296} {
        test ${mode}_exact_aperture_$length [list apply [list {mode length} {
            set ::valence_ram::chunk_words 256
            set padded [expr {($length + 3) & ~3}]
            set ::model::state(end) [expr {0x80200000 + $padded}]
            set hexbytes ""
            for {set i 0} {$i < $length} {incr i} {append hexbytes [format %02x [expr {($i * 73 + 19) & 255}]]}
            set result [::valence_download_and_run [image_file $hexbytes] 0x80200000 $mode]
            set words [expr {$padded / 4}]
            assert {[dict get $result mode] eq $mode}
            assert {$::model::state(writes) == $words && $::model::state(reads) == $words}
            assert {$::model::state(commit_count) == 1 && $::model::state(sb_busyerror) == 0 && $::model::state(sb_error) == 0}
            assert {!$::model::state(sb_busy) && !$::valence_ram::bscan_leased && !$::valence_ram::download_active}
            assert {[llength $::model::transactions] == 2 * $words}
            for {set i 0} {$i < $words} {incr i} {
                set address [expr {0x80200000 + 4 * $i}]
                assert {[lindex $::model::transactions $i] eq [list write $address]}
                assert {[lindex $::model::transactions [expr {$words + $i}]] eq [list read $address]}
                set expected 0
                for {set byte 0} {$byte < 4} {incr byte} {
                    set offset [expr {4 * $i + $byte}]
                    if {$offset < $length} {set expected [expr {$expected | ((($offset * 73 + 19) & 255) << (8 * $byte))}]}
                }
                assert {$::model::memory($address) == $expected}
            }
            if {$mode eq "fast" && $length >= 1024} {assert {$::model::state(b_ir_scans) < 40}}
        }] $mode $length]
    }
}
foreach chunk {1 2 3 17 256} {
    test fast_chunk_$chunk [list apply [list {chunk} {
        set ::valence_ram::chunk_words $chunk
        set ::model::state(end) 0x80200020
        ::valence_download_and_run [image_file 00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff] 0x80200000
        assert {$::model::state(writes) == 8 && $::model::state(reads) == 8 && $::model::state(sb_error) == 0}
    }] $chunk]
}
foreach feature {autoincrement_supported readondata_supported} {
    test fast_requires_$feature [list apply [list {feature} {
        set ::model::state($feature) 0
        fails {::valence_download_and_run [image_file 01020304] 0x80200000} {*Streaming SBA controls unavailable*}
        assert {![llength $::model::transactions] && $::model::state(commit_count) == 0}
        assert {!$::valence_ram::bscan_leased && !$::valence_ram::download_active}
    }] $feature]
}
test safe_does_not_require_streaming_controls {
    set ::model::state(autoincrement_supported) 0; set ::model::state(readondata_supported) 0
    ::valence_download_and_run [image_file 00112233445566778899aabb] 0x80200000 safe
    assert {$::model::state(writes) == 3 && $::model::state(reads) == 3 && $::model::state(commit_count) == 1}
}
test fast_delayed_bus_and_transport_no_duplicates {
    set ::model::state(sb_delay) 3; set ::model::state(b_delay) 100
    ::valence_download_and_run [image_file 0102030405060708090a0b0c] 0x80200000
    assert {$::model::state(writes) == 3 && $::model::state(reads) == 3 && $::model::state(commit_count) == 1}
    assert {$::model::state(b_error) == 0 && $::model::state(sb_busyerror) == 0}
}
test fast_mismatch_drains_one_bounded_read {
    set ::valence_ram::chunk_words 4
    set ::model::state(corrupt_address) 0x80200000
    fails {::valence_download_and_run [image_file 00112233445566778899aabbccddeeff] 0x80200000} {*Readback mismatch*COMMIT not sent*}
    assert {$::model::state(reads) == 2 && !$::model::state(sb_busy)}
    assert {($::model::state(sb_control) & 0x118000) == 0}
    assert {$::model::state(commit_count) == 0 && [array size ::model::metadata] == 0}
    assert {!$::valence_ram::bscan_leased && !$::valence_ram::download_active}
}
test fast_last_word_mismatch_never_reads_past_aperture {
    set ::model::state(end) 0x80200008; set ::model::state(corrupt_address) 0x80200004
    fails {::valence_download_and_run [image_file 0011223344556677] 0x80200000} {*Readback mismatch*COMMIT not sent*}
    assert {$::model::state(reads) == 2 && [llength $::model::transactions] == 4 && $::model::state(sb_error) == 0}
}
test fast_mismatch_drain_timeout_blocks_replay {
    set ::model::state(corrupt_address) 0x80200000; set ::model::state(stall_after_reads) 1
    fails {::valence_download_and_run [image_file 0011223344556677] 0x80200000} {*Readback mismatch*pending read drain failed*}
    assert {$::valence_ram::uncertain && $::model::state(sb_busy) && $::model::state(commit_count) == 0}
    set before $::model::state(b_submit)
    fails {::valence_download_and_run [image_file 0011223344556677] 0x80200000} {*Previous transport outcome uncertain*}
    assert {$::model::state(b_submit) == $before && !$::valence_ram::bscan_leased}
}
test fast_read_generation_change_blocks_commit {
    set ::model::state(gen_after_reads) 1
    fails {::valence_download_and_run [image_file 00112233445566778899aabb] 0x80200000} {*generation changed*}
    assert {$::model::state(reads) <= 2 && $::model::state(commit_count) == 0 && [array size ::model::metadata] == 0}
}
test invalid_mode_rejected_before_scans {
    fails {::valence_download_and_run [image_file 00112233] 0x80200000 turbo} {*fast or safe*}
    assert {$::model::state(b_ir_scans) == 0 && $::model::state(b_submit) == 0}
}
test lease_previous_capture_change_is_uncertain {
    ::valence_ram::start; ::valence_ram::bscan_begin
    ::valence_ram::rd 0x40
    set ::model::state(b_bad_previous) 1
    fails {::valence_ram::rd 0x40} {*previous USER result changed*acceptance uncertain*}
    assert {$::valence_ram::uncertain}
    set before $::model::state(b_submit)
    fails {::valence_ram::rd 0x40} {*Transport outcome uncertain*}
    assert {$::model::state(b_submit) == $before}
    ::valence_ram::bscan_end
}
test lease_configuration_mutation_rejected_before_scan {
    ::valence_ram::start; ::valence_ram::bscan_begin; ::valence_ram::rd 0x40
    set before $::model::state(b_dr_scans)
    set ::valence_ram::tap changed.tap
    fails {::valence_ram::rd 0x40} {*configuration changed during scan lease*}
    assert {$::model::state(b_dr_scans) == $before}
    ::valence_ram::bscan_end
}
test lease_does_not_cache_across_console_commands {
    ::valence_download_and_run [image_file 00112233] 0x80200000
    set ::model::state(b_current_ir) 0x123
    set before $::model::state(b_ir_scans)
    assert {[::valence_ram::rd 0x40] == 0x564c0101}
    assert {$::model::state(b_ir_scans) > $before && !$::valence_ram::bscan_leased}
}
test lease_released_on_dmi_failure {
    set ::model::state(fail_address) 60; set ::model::state(fail_op) 2
    fails {::valence_download_and_run [image_file 00112233] 0x80200000} {*DMI failed*}
    assert {$::valence_ram::uncertain && !$::valence_ram::bscan_leased && !$::valence_ram::download_active}
}
test claimed_helper_from_nonroot_namespace {
    set ::model::state(commit_claim) 1
    ::valence_download_and_run [image_file 00112233] 0x80200000
    set result [namespace eval unrelated {::valence_wait_claimed}]
    assert {[dict get $result state] eq "claimed"}
}
test source_cannot_clear_uncertain_transport {
    set ::valence_ram::uncertain 1
    fails {source [file join [file dirname [info script]] ram-loader.tcl]} {*Cannot reload an uncertain transport*}
    assert {$::valence_ram::uncertain}
}
test progress_contains_stages_and_segment_times {
    set result [::valence_download_and_run [image_file 0011223344556677] 0x80200000]
    set text [join $::messages \n]
    assert {[string match {*WRITE*100.0%*VERIFY*100.0%*COMMIT accepted*Mode=fast WRITE=*VERIFY=*effective=*} $text]}
    foreach key {write_ms verify_ms metadata_ms elapsed_ms} {assert {[dict exists $result $key]}}
}
test upgrade_source_only_and_complete_download {
    set ::VALENCE_RAM_BACKEND bscan
    set ::VALENCE_RAM_TAP mock_fpga.tap
    set ::VALENCE_RAM_FPGA_PART xczu15eg-ffvb1156-2-i
    set ::VALENCE_RAM_FPGA_IRLEN 12
    set ::VALENCE_RAM_JTAG_CHAIN 2
    set ::VALENCE_RAM_USER_IR 0x903
    set ::VALENCE_RAM_FPGA_IDCODE 0x14750093
    source [file join [file dirname [info script]] upgrade-host.tcl]
    assert {$::model::state(b_ir_scans) == 0 && $::model::state(b_submit) == 0}
    ::valence_download_and_run [image_file 0011223344556677] 0x80200000
    assert {$::model::state(writes) == 2 && $::model::state(reads) == 2 && $::model::state(commit_count) == 1}
}
test source_cannot_clear_active_download {
    set ::valence_ram::download_active 1
    fails {source [file join [file dirname [info script]] ram-loader.tcl]} {*Cannot reload loader during an active download*}
    assert {$::valence_ram::download_active}
    set ::valence_ram::download_active 0
}
finish "Fast streaming/lease host tests"
