#!/usr/bin/env tclsh
# Source-only configuration checks; no installed OpenOCD and no adapter access.
set directory [file dirname [info script]]
set n 0
foreach mode {direct_new direct_existing bscan bscan_missing} {
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
    if {$mode == "direct_existing"} {interp eval $child {set VALENCE_RAM_TAP board.dtm; set VALENCE_RAM_IDCODE 3}}
    if {[string match bscan* $mode]} {
        set cfg openocd-ram-loader-bscan.cfg
        if {$mode == "bscan"} {interp eval $child {set VALENCE_RAM_TAP board.fpga; set VALENCE_RAM_USER_IR 2; set VALENCE_RAM_FPGA_IDCODE 3}}
    }
    set rc [catch {interp eval $child [list source [file join $directory $cfg]]} result]
    if {$mode == "bscan_missing"} {
        if {!$rc || ![string match {*Board configuration must set*} $result]} {error "Missing mandatory BSCAN configuration was not rejected"}
    } else {
        if {$rc} {error "$mode: $result"}
        set calls [interp eval $child {set config_calls}]
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
