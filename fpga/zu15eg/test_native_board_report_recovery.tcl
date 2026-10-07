# Unit-test wrapper control flow only; all design/CAD/report APIs are mocked.
# No DCP, hardware, topology, timing, CDC or bit release proof.
if {$argc != 1} {error "Expected RECOVERY_SCRIPT"}
set f [open [lindex $argv 0] r]; set recovery [read $f]; close $f
if {![info complete $recovery]} {error "Incomplete recovery Tcl"}
set fixtures {
    pass {} {}
    wrong_argc {set argc 2} {Expected CANDIDATE_ROOT}
    external_dcp {set argv {C:/candidate C:/other/placed.dcp C:/candidate/implementation-report-recovery-r1}} {Only this candidate}
    external_output {set argv {C:/candidate C:/candidate/implementation/placed.dcp C:/other/output}} {Recovery output must stay}
    existing_output {set occupied 1} {output exists}
    missing_manifest {set manifest 0} {Missing frozen candidate manifest}
    missing_placed {set mockPlacedPresent 0} {Only this candidate}
    wrong_part {set part wrong} {Wrong FPGA part}
    absent_fpu {set fpu {}} {actual full RV64GC FPU}
    duplicate_fpu {set fpu {fp0 fp1}} {actual full RV64GC FPU}
    functional_blackbox {set boxes bb} {Functional black boxes}
    missing_clock {set absentClock 1} {Missing actual clock endpoint}
    wrong_clock {set wrongClock 1} {Wrong actual clock}
    bad_topology {set badTopology 1} {bad actual topology}
    failed_report_saved_dcp {set failReport 1} {report failure}
}
set mocked {
    set argc 3
    set argv {C:/candidate C:/candidate/implementation/placed.dcp C:/candidate/implementation-report-recovery-r1}
    set occupied 0; set manifest 1; set mockPlacedPresent 1
    set part xczu15eg-ffvb1156-2-i; set fpu fp0; set boxes {}
    set absentClock 0; set wrongClock 0; set badTopology 0; set failReport 0
    set events {}
    rename file real_file
    proc file {op args} {
        switch -- $op {
            normalize {return [string map {\\ /} [lindex $args 0]]}
            isfile {
                set path [lindex $args 0]
                if {[string match */placed.dcp $path]} {return $::mockPlacedPresent}
                return $::manifest
            }
            exists {return $::occupied}
            mkdir {lappend ::events mkdir; return}
            default {return [real_file $op {*}$args]}
        }
    }
    proc cd args {}
    proc open args {return fake_report}
    proc puts args {lappend ::events puts}
    proc close args {}
    proc set_param args {}
    proc open_checkpoint args {lappend ::events open_checkpoint}
    proc current_design {} {return design}
    proc get_cells args {
        if {[lindex $args end] eq "centered_tx_clock.clock_dut/quarter_div"} {return quarter}
        if {[string match *FloatingPointSystem* [lindex $args end]]} {return $::fpu}
        return $::boxes
    }
    proc get_pins args {
        if {$::absentClock} {return {}}
        return [lindex $args end]
    }
    proc get_clocks args {return [lindex $args end]}
    proc get_property {name obj} {
        switch -- $name {
            PART {return $::part}
            SLACK {return 0.01}
            REQUIREMENT {return [expr {$obj eq "max" ? 2.0 : -2.0}]}
            PERIOD {
                if {$::wrongClock} {return 99.0}
                set frequencies {
                    u_soc/clock 100000000
                    u_soc/io_alwaysOnClock 50000000
                    u_soc/nativeBank/uart/uart/clock 50000000
                    u_soc/io_nativeGmac_rawTxClock 125000000
                    u_rgmii/delay_clock 500000000
                    u_rgmii/tx_clock_ddr/CLK 250000000
                }
                return [expr {1.0e9/[dict get $frequencies $obj]}]
            }
        }
        error "Unexpected property $name"
    }
    proc source args {
        proc valence_quarter_tx_audit args {
            if {$::badTopology} {error "bad actual topology"}
            lappend ::events topology_checked
            return {lane0 lane1 lane2 lane3 control}
        }
    }
    proc route_design args {lappend ::events route}
    proc phys_opt_design args {lappend ::events physopt}
    proc write_checkpoint name {lappend ::events "checkpoint:$name"}
    proc report_timing_summary args {
        lappend ::events first_report
        if {$::failReport} {error "report failure"}
    }
    foreach command {
        report_timing report_utilization report_clock_interaction report_cdc
        report_bus_skew report_route_status report_exceptions check_timing
        report_drc report_clocks write_xdc close_design
    } {proc $command args {}}
    proc get_ports args {return {p0 p1 p2 p3 p4}}
    proc get_timing_paths args {
        set i [lsearch -exact $args -delay_type]
        return [lindex $args [expr {$i+1}]]
    }
}
set passed 0
foreach {name setup expected} $fixtures {
    set child [interp create]
    $child eval $mocked
    $child eval $setup
    set failed [catch {$child eval $recovery} detail]
    set events [$child eval {set events}]
    if {$expected eq ""} {
        if {$failed} {error "$name unexpectedly failed: $detail"}
        foreach event {route checkpoint:routed_before_physopt.dcp physopt checkpoint:routed.dcp first_report} {
            if {[lsearch -exact $events $event]<0} {error "$name missing $event"}
        }
        if {[lsearch -exact $events checkpoint:routed.dcp]>[lsearch -exact $events first_report]} {
            error "Completed DCP must be saved BEFORE supplemental reports"
        }
    } else {
        if {!$failed || [string first $expected $detail]<0} {error "$name wrong failure: $detail"}
        if {$name eq "failed_report_saved_dcp"} {
            if {[lsearch -exact $events checkpoint:routed.dcp]<0} {error "Report failure lost routed DCP"}
        } elseif {[lsearch -exact $events route]>=0} {
            error "$name must fail before expensive route"
        }
    }
    interp delete $child
    incr passed
}
puts "PASS_NATIVE_BOARD_REPORT_RECOVERY_UNIT cases=$passed MOCKED_CONTROL_FLOW_NO_DCP_NO_HARDWARE_PROOF"
