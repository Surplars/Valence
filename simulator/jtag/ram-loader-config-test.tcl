#!/usr/bin/env tclsh
# Source-only configuration checks; no installed OpenOCD and no adapter access.
set directory [file dirname [info script]]
set n 0
set modes {direct_new direct_existing bscan bscan_user3 bscan_user4 bscan_missing
    bscan_badpart bscan_ir6 bscan_user1 bscan_low6 bscan_wrongpair bscan_badid bscan_missingchain}
foreach mode $modes {
    set child [interp create]
    interp eval $child {
        set config_calls {}
        proc transport {args} {lappend ::config_calls [linsert $args 0 transport]}
        proc gdb {args} {lappend ::config_calls [linsert $args 0 gdb]}
        proc tcl {args} {lappend ::config_calls [linsert $args 0 tcl]}
        proc telnet {args} {lappend ::config_calls [linsert $args 0 telnet]}
        proc jtag {args} {lappend ::config_calls [linsert $args 0 jtag]}
    }
    set cfg openocd-ram-loader.cfg
    set failure {}
    if {$mode == "direct_existing"} {interp eval $child {set VALENCE_RAM_TAP board.dtm; set VALENCE_RAM_IDCODE 3}}
    if {[string match bscan* $mode]} {
        set cfg openocd-ram-loader-bscan.cfg
        if {$mode ne "bscan_missing"} {
            interp eval $child {
                set VALENCE_RAM_TAP board.fpga
                set VALENCE_RAM_FPGA_PART xczu15eg-ffvb1156-2-i
                set VALENCE_RAM_FPGA_IRLEN 12
                set VALENCE_RAM_JTAG_CHAIN 2
                set VALENCE_RAM_USER_IR 0x903
                set VALENCE_RAM_FPGA_IDCODE 0x04750093
            }
        }
        switch -- $mode {
            bscan_user3 {interp eval $child {set VALENCE_RAM_JTAG_CHAIN 3; set VALENCE_RAM_USER_IR 0x922}}
            bscan_user4 {interp eval $child {set VALENCE_RAM_JTAG_CHAIN 4; set VALENCE_RAM_USER_IR 0x923}}
            bscan_missing {set failure {*Board configuration must set*}}
            bscan_badpart {interp eval $child {set VALENCE_RAM_FPGA_PART xczu9eg};set failure {*reviewed BSDL profile*}}
            bscan_ir6 {interp eval $child {set VALENCE_RAM_FPGA_IRLEN 6};set failure {*12-bit FPGA IR*}}
            bscan_user1 {interp eval $child {set VALENCE_RAM_JTAG_CHAIN 1;set VALENCE_RAM_USER_IR 0x902};set failure {*USER1 is occupied*}}
            bscan_low6 {interp eval $child {set VALENCE_RAM_USER_IR 0x03};set failure {*full 12-bit opcode*}}
            bscan_wrongpair {interp eval $child {set VALENCE_RAM_JTAG_CHAIN 3};set failure {*opcode 0x922*}}
            bscan_badid {interp eval $child {set VALENCE_RAM_FPGA_IDCODE 0x04711093};set failure {*BSDL identity*}}
            bscan_missingchain {interp eval $child {unset VALENCE_RAM_JTAG_CHAIN};set failure {*VALENCE_RAM_JTAG_CHAIN*}}
        }
    }
    set rc [catch {interp eval $child [list source [file join $directory $cfg]]} result]
    set calls [interp eval $child {set config_calls}]
    if {$failure ne ""} {
        if {!$rc || ![string match $failure $result]} {error "$mode expected $failure, got $result"}
        if {[llength $calls]} {error "$mode performed commands before rejecting config: $calls"}
    } else {
        if {$rc} {error "$mode: $result"}
        foreach service {gdb tcl telnet} {
            if {[lsearch -exact $calls [list $service port disabled]] < 0} {error "$mode left $service enabled"}
        }
        if {$mode == "direct_new"} {
            if {[llength $calls] != 5} {error "Unexpected direct configuration side effects: $calls"}
        } elseif {[llength $calls] != 4} {error "Unexpected supplied-TAP configuration side effects: $calls"}
        if {[interp eval $child {llength [info commands valence_download_and_run]}] != 1} {error "API missing"}
    }
    interp delete $child
    incr n; puts "PASS config_$mode"
}
puts "RAM loader configuration tests: $n passed (source-only mocks, no OpenOCD/adapter)"
