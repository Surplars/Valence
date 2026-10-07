# Combined tiny real-pad sweep. PHY setup/hold budget remains 1.250ns.
# Never use an OOC pad probe as whole-board STA/CDC/bit release evidence.
if {$argc < 2 || $argc > 3} {error "Expected SOURCE_SV FRESH_OUTPUT_DIRECTORY ?TOP?"}
lassign $argv src out top
if {$top eq ""} {set top native_tx_single_delay_probe}
if {$top ni {native_tx_single_delay_probe native_tx_single_clock_delay_probe}} {error "Tiny TX probe only"}
if {[file exists $out]} {error "Preserve existing evidence"}
file mkdir $out
file copy $src [file join $out compiled_source.sv]
file copy [info script] [file join $out executed_synth.tcl]
set_param general.maxThreads 8
set result [open [file join $out delay_sweep.csv] w]
puts $result "delay_ps,pin,setup_ns,hold_ns"
foreach delay {600 800 1000 1100} {
    set current [file join $out delay$delay]
    file mkdir $current
    create_project -in_memory -part xczu15eg-ffvb1156-2-i
    read_verilog -sv [file join $out compiled_source.sv]
    synth_design -top $top -generic DELAY_PS=$delay -mode out_of_context -flatten_hierarchy none
    create_clock -name raw_proxy -period 8.000 [get_ports raw_input]
    create_clock -name ref_proxy -period 2.000 [get_ports ref_input]
    set bias 0.0
    if {$top eq "native_tx_single_clock_delay_probe"} {
        # Edge-selection bias cancels IDENTICALLY in both output delays.
        # Actual DDR/ODELAY/OBUF propagation remains in the destination clock
        # path, not a replaced source latency. Verify another equivalent bias.
        set bias 1.0
        create_generated_clock -name phy_tx_capture -source [get_pins clock_ddr/CLK] \
            -edges {1 2 3} -edge_shift [list $bias $bias $bias] [get_ports eth_txc]
    } else {
        create_generated_clock -name phy_tx_capture -source [get_pins clock_ddr/CLK] \
            -divide_by 1 -invert [get_ports eth_txc]
    }
    set_clock_uncertainty 0.100 [get_clocks raw_proxy]
    foreach {port pin} {{eth_txd[0]} AC11 {eth_txd[1]} AC12 {eth_txd[2]} AA6 {eth_txd[3]} AA12 eth_tx_ctl AB8 eth_txc AC8} {
        set_property PACKAGE_PIN $pin [get_ports $port]
        set_property IOSTANDARD LVCMOS18 [get_ports $port]
        set_property DRIVE 8 [get_ports $port]
        set_property SLEW FAST [get_ports $port]
    }
    # Same real BITSLICE0 pad contract as production: reset remains asserted
    # until IDELAYCTRL RDY. This acknowledgement is not a DRC severity waiver.
    set_property UNAVAILABLE_DURING_CALIBRATION TRUE [get_ports {eth_txd[1]}]
    set_property LOC BUFGCE_X0Y61 [get_cells raw_buffer]
    set_property LOC BUFGCE_X0Y63 [get_cells ref_buffer]
    set_property USER_CLOCK_ROOT X3Y2 [get_nets -of_objects [get_pins raw_buffer/O]]
    set_property USER_CLOCK_ROOT X3Y2 [get_nets -of_objects [get_pins ref_buffer/O]]
    set_false_path -from [get_ports reset]
    foreach extra {{} {-clock_fall -add_delay}} {
        set_output_delay -clock phy_tx_capture -max [expr {1.250+$bias}] {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
        set_output_delay -clock phy_tx_capture -min [expr {-1.250+$bias}] {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
    }
    opt_design
    place_design
    route_design
    write_checkpoint [file join $current routed.dcp]
    report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max \
        -max_paths 10 -input_pins -file [file join $current tx_io.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $current timing_summary.rpt]
    report_clocks -file [file join $current clocks.rpt]
    report_drc -file [file join $current drc.rpt]
    foreach port [lsort [get_ports {eth_txd[*] eth_tx_ctl}]] {
        set maximum [get_timing_paths -to $port -delay_type max -max_paths 1]
        set minimum [get_timing_paths -to $port -delay_type min -max_paths 1]
        if {[llength $maximum] != 1 || [llength $minimum] != 1} {error "Missing physical lane path: $port"}
        puts $result "$delay,$port,[get_property SLACK $maximum],[get_property SLACK $minimum]"
    }
    if {$top eq "native_tx_single_clock_delay_probe"} {
        set original {}
        foreach port [lsort [get_ports {eth_txd[*] eth_tx_ctl}]] {
            foreach kind {max min} {
                lappend original [get_property SLACK [get_timing_paths -to $port -delay_type $kind -max_paths 1]]
            }
        }
        create_generated_clock -name phy_tx_capture -source [get_pins clock_ddr/CLK] \
            -edges {1 2 3} -edge_shift {0.1 0.1 0.1} [get_ports eth_txc]
        foreach extra {{} {-clock_fall -add_delay}} {
            set_output_delay -clock phy_tx_capture -max 1.350 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
            set_output_delay -clock phy_tx_capture -min -1.150 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
        }
        set equivalent {}
        foreach port [lsort [get_ports {eth_txd[*] eth_tx_ctl}]] {
            foreach kind {max min} {
                lappend equivalent [get_property SLACK [get_timing_paths -to $port -delay_type $kind -max_paths 1]]
            }
        }
        foreach a $original b $equivalent {
            if {abs($a-$b)>0.001} {error "Edge bias changed physical lane timing: $original $equivalent"}
        }
        report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max \
            -max_paths 10 -input_pins -file [file join $current equivalent_bias_tx_io.rpt]
        puts "EQUIVALENT_EDGE_BIASES_PRESERVE_ALL_TEN_TX_SLACKS BUDGET_1.250NS"
    }
    flush $result
    puts "NATIVE_SINGLE_DELAY_PAD_POINT_COMPLETE delay_ps=$delay"
    close_project
}
close $result
puts "NATIVE_SINGLE_DELAY_PAD_SWEEP_COMPLETE NO_BOARD_PROOF_NO_BIT"
