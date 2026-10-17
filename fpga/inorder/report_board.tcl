# Routed reports shared by the initial and resumed real-board implementation.
proc i1_report_real_board {root} {
    set reports [file join $root reports]
    write_checkpoint [file join $reports real_board_routed.dcp]
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $reports timing_summary.rpt]
    report_timing -delay_type max -max_paths 30 -input_pins -file [file join $reports setup_paths.rpt]
    report_timing -delay_type min -max_paths 30 -input_pins -file [file join $reports hold_paths.rpt]
    report_utilization -hierarchical -file [file join $reports utilization.rpt]
    report_io -file [file join $reports io.rpt]
    report_clocks -file [file join $reports clocks.rpt]
    report_clock_interaction -file [file join $reports clock_interaction.rpt]
    report_cdc -details -file [file join $reports cdc.rpt]
    report_bus_skew -warn_on_violation -file [file join $reports bus_skew.rpt]
    report_route_status -file [file join $reports route_status.rpt]
    report_drc -file [file join $reports drc.rpt]
    report_exceptions -coverage -file [file join $reports exceptions.rpt]
    check_timing -verbose -file [file join $reports check_timing.rpt]
    set cpu [get_clocks -of_objects [get_pins u_soc/io_clockIn]]
    report_timing -from $cpu -to $cpu -delay_type max -max_paths 20 \
        -file [file join $reports cpu_setup.rpt]
    report_timing -from $cpu -to $cpu -delay_type min -max_paths 20 \
        -file [file join $reports cpu_hold.rpt]
    foreach {direction ports} {tx {eth_txd[*] eth_tx_ctl} rx {eth_rxd[*] eth_rx_ctl}} {
        foreach port [get_ports $ports] {
            foreach delay {max min} {
                if {$direction eq "tx"} {
                    set p [get_timing_paths -to $port -delay_type $delay -max_paths 1]
                    report_timing -to $port -delay_type $delay -max_paths 1 \
                        -file [file join $reports [format "tx_%s_%s.rpt" [get_property NAME $port] $delay]]
                } else {
                    set p [get_timing_paths -from $port -delay_type $delay -max_paths 1]
                    report_timing -from $port -delay_type $delay -max_paths 1 \
                        -file [file join $reports [format "rx_%s_%s.rpt" [get_property NAME $port] $delay]]
                }
                if {[llength $p] != 1 || [get_property SLACK $p] in {inf -inf}} {
                    error "Untimed real RGMII I/O lane: $port $delay"
                }
            }
        }
    }
    set setup [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
    set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
    set f [open [file join $reports stage-result.txt] w]
    puts $f "REAL_BOARD CPU_HZ=300000000 MIG2GiB UI250 AXI64 UART460800 TRISPEED_GMAC USER2"
    puts $f "WNS=$setup WHS=$hold STATUS=ROUTED_REQUIRES_SIGNOFF NO_BIT_GENERATED"
    close $f
    puts "I1_REAL_BOARD_ROUTED WNS=$setup WHS=$hold CPU300 MIG_UI250 PHYSICAL_IO_INCLUDED"
    # No bit until timing, DRC, CDC/RDC and all physical IO scenarios pass.
}
