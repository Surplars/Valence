# Synthetic release-guard execution tests. No real DCP/CAD/bit operations.
if {$argc!=1} {error "Expected RELEASE_SCRIPT"}
set f [open [lindex $argv 0] r]; set script [read $f]; close $f
if {![info complete $script]} {error "Incomplete release Tcl"}
set fixtures {
    pass {} {}
    wrong_argc {set argc 0} {Expected CANDIDATE_ROOT}
    external_dcp {lset argv 1 C:/other/routed.dcp} {own source-integrated}
    wrong_output {lset argv 4 C:/other/output} {fresh named release}
    occupied_output {set mockOccupied 1} {fresh named release}
    unqualified_contract {set mockInitialGate 0} {contract rejected}
    incomplete_rom {set mockIncompleteRom 1} {Incomplete selected BootROM}
    wrong_rom {set mockWrongRom 1} {Implemented BootROM differs}
    wrong_part {set mockPart wrong} {Wrong FPGA part}
    blackbox {set mockBoxes bb} {Functional black boxes}
    absent_fpu {set mockFpu {}} {Missing actual RV64GC FPU}
    duplicate_fpu {set mockFpu {a b}} {Missing actual RV64GC FPU}
    legacy_eth {set mockLegacy legacy} {Legacy Ethernet IP}
    missing_clock {set mockMissingClock 1} {Missing actual clock endpoint}
    wrong_clock {set mockWrongClock 1} {Wrong actual board clock}
    bad_topology {set mockTopology 0} {bad topology}
    negative_setup {set mockBadSetup 1} {Actual routed setup/hold}
    negative_hold {set mockBadHold 1} {Actual routed setup/hold}
    untimed_global {set mockUntimedGlobal 1} {Actual routed setup/hold}
    missing_io_lane {set mockLaneCount 4} {Missing physical}
    bad_io_slack {set mockBadIo 1} {Physical tx lane}
    wrong_tx_edges {set mockBadEdges 1} {TX edge relationship}
    bad_pulse {set mockBadPulse 1} {Setup/hold/pulse failure}
    failing_endpoints {set mockBadEndpoints 1} {Timing failing endpoint}
    unparsed_summary {set mockUnparsedSummary 1} {Cannot validate}
    missing_coverage {set mockBadCoverage 1} {Timing coverage failure}
    missing_skew {set mockSkewCount 26} {Bus-skew checks}
    failing_skew {set mockBadSkew 1} {Bus-skew checks}
    unrouted_nets {set mockFullyRouted 99} {Incomplete routing}
    route_errors {set mockRouteErrors 1} {Incomplete routing}
    bitstream_drc {set mockDrc 1} {Bitstream DRC}
    changed_current_cdc {set mockFinalGate 0} {current CDC contract rejected}
}
set mocked {
    set argc 5
    set argv {C:/candidate C:/candidate/implementation-report-recovery-r1/routed.dcp C:/proof/contract.json C:/python.exe C:/candidate/release-rv64gc100-u460800-r3}
    set mockOccupied 0; set mockInitialGate 1; set mockFinalGate 1
    set mockIncompleteRom 0; set mockWrongRom 0; set mockPart xczu15eg-ffvb1156-2-i
    set mockBoxes {}; set mockFpu fp; set mockLegacy {}; set mockMissingClock 0; set mockWrongClock 0
    set mockTopology 1; set mockBadSetup 0; set mockBadHold 0; set mockUntimedGlobal 0
    set mockLaneCount 5; set mockBadIo 0; set mockBadEdges 0
    set mockBadPulse 0; set mockBadEndpoints 0; set mockUnparsedSummary 0; set mockBadCoverage 0
    set mockSkewCount 27; set mockBadSkew 0; set mockFullyRouted 100; set mockRouteErrors 0; set mockDrc 0
    set mockPhase {}; set mockQueryIo 0; set events {}
    rename file real_file
    proc file {op args} {
        switch -- $op {
            normalize {return [string map {\\ /} [lindex $args 0]]}
            exists {return $::mockOccupied}
            mkdir {lappend ::events mkdir; return}
            default {return [real_file $op {*}$args]}
        }
    }
    proc exec args {
        if {[lsearch -exact $args --cdc-report]>=0} {
            lappend ::events final_contract
            if {!$::mockFinalGate} {error "current CDC contract rejected"}
        } else {
            lappend ::events initial_contract
            if {!$::mockInitialGate} {error "contract rejected"}
        }
        if {[lsearch -exact $args -B]<0 || [lsearch -exact $args -I]<0} {error "Python must isolate environment and avoid pycache"}
        return PASS_MOCK_CONTRACT
    }
    proc set_param args {}
    proc open_checkpoint path {
        lappend ::events open_checkpoint
        set ::mockPhase [expr {[string match */blk_mem_gen_0.dcp $path] ? "rom" : "board"}]
    }
    proc close_design args {}
    proc current_design args {return design}
    proc get_cells args {
        set filter [lindex $args end]
        if {[string match *IS_BLACKBOX* $filter]} {return $::mockBoxes}
        if {[string match *FloatingPointSystem* $filter]} {return $::mockFpu}
        if {[string match *clk_wiz_eth* $filter]} {return $::mockLegacy}
        if {[string match *RAMB* $filter]} {
            set result {}
            for {set n 0} {$n<17} {incr n} {lappend result rom$n}
            return $result
        }
        return $filter
    }
    proc list_property cell {
        set count [expr {$cell eq "rom16" ? ($::mockIncompleteRom ? 79 : 80) : 256}]
        set result {}
        for {set n 0} {$n<$count} {incr n} {lappend result [format INIT_%02X $n]}
        return $result
    }
    proc get_pins args {
        if {$::mockMissingClock} {return {}}
        return [lindex $args end]
    }
    proc get_clocks args {return [lindex $args end]}
    proc get_property {property obj} {
        switch -- $property {
            NAME {return $obj}
            PART {return $::mockPart}
            PERIOD {
                if {$::mockWrongClock} {return 99}
                set periods {
                    u_soc/clock 10.0 u_soc/io_alwaysOnClock 20.0
                    u_soc/nativeBank/uart/uart/clock 20.0 u_soc/io_nativeGmac_rawTxClock 8.0
                    u_rgmii/delay_clock 2.0 u_rgmii/tx_clock_ddr/CLK 4.0 u_ddr/c0_ddr4_ui_clk 4.0
                }
                return [dict get $periods $obj]
            }
            SLACK {
                if {$::mockQueryIo && $::mockBadIo} {return -0.1}
                if {!$::mockQueryIo && (($obj eq "max" && $::mockBadSetup) || ($obj eq "min" && $::mockBadHold))} {return -0.1}
                return 0.01
            }
            REQUIREMENT {return [expr {$::mockBadEdges ? 4.0 : ($obj eq "max" ? 2.0 : -2.0)}]}
            default {
                if {[string match INIT_* $property]} {
                    if {$::mockWrongRom && [string match u_soc/* $obj]} {return BAD}
                    return ZERO
                }
                error "Unexpected property $property"
            }
        }
    }
    proc source args {
        proc valence_quarter_tx_audit args {
            if {!$::mockTopology} {error "bad topology"}
            lappend ::events topology
        }
    }
    proc get_ports args {
        set result {}
        for {set n 0} {$n<$::mockLaneCount} {incr n} {lappend result port$n}
        return $result
    }
    proc get_timing_paths args {
        set ::mockQueryIo [expr {[lsearch -exact $args -to]>=0 || [lsearch -exact $args -from]>=0}]
        if {!$::mockQueryIo && $::mockUntimedGlobal} {return {}}
        return [lindex $args [expr {[lsearch -exact $args -delay_type]+1}]]
    }
    foreach command {report_timing_summary report_route_status report_bus_skew check_timing report_cdc report_drc} {
        proc $command args {}
    }
    proc get_drc_violations args {return [expr {$::mockDrc ? "violation" : ""}]}
    proc open {path mode} {return $path}
    proc close args {}
    proc puts args {}
    proc read path {
        switch -- [real_file tail $path] {
            timing_summary.rpt {
                if {$::mockUnparsedSummary} {return "No summary"}
                set pulse [expr {$::mockBadPulse ? -0.1 : 0.081}]
                set failures [expr {$::mockBadEndpoints ? 1 : 0}]
                return "  0.012  0.000  $failures  100  0.010  0.000  0  100  $pulse  0.000  0  20"
            }
            check_timing.rpt {
                set result ""
                foreach name {no_clock unconstrained_internal_endpoints generated_clocks loops multiple_clock latch_loops} {
                    set count [expr {$::mockBadCoverage && $name eq "no_clock" ? 1 : 0}]
                    append result "checking $name ($count)\n"
                }
                return $result
            }
            bus_skew.rpt {return "[string repeat {Slack (MET) } $::mockSkewCount][expr {$::mockBadSkew ? {Slack (VIOLATED)} : {}}]"}
            route_status.rpt {return "routable nets.... : 100\nfully routed nets.... : $::mockFullyRouted\nnets with routing errors.... : $::mockRouteErrors"}
            default {error "Unexpected read $path"}
        }
    }
    proc write_checkpoint args {lappend ::events checkpoint_saved}
    proc write_bitstream args {lappend ::events bit_generated}
}
set count 0
foreach {name setup expected} $fixtures {
    set child [interp create]
    $child eval $mocked
    $child eval $setup
    set failed [catch {$child eval $script} detail]
    set events [$child eval {set events}]
    set bit [expr {[lsearch -exact $events bit_generated]>=0}]
    if {$expected eq ""} {
        if {$failed || !$bit} {error "$name failed: $detail"}
        if {[lsearch -exact $events final_contract]>[lsearch -exact $events bit_generated]} {error "Bit emitted before final contract"}
    } else {
        if {!$failed || $bit || [string first $expected $detail]<0} {error "$name incorrect guard: $detail events=$events"}
    }
    interp delete $child
    incr count
}
puts "PASS_NATIVE_RV64GC_BIT_RELEASE_GUARD_UNIT cases=$count MOCKED_NO_DCP_NO_REAL_BIT_NO_BOARD_PROOF"

