# Full project implementation with ACTUAL MIG, clock IP, AXI CDC and package I/O.
# Existing OOC/OOO checkpoints are never used as the board CPU.
if {$argc != 1} {error "usage: build_board.tcl STAGED_BOARD_ROOT"}
set root [file normalize [lindex $argv 0]]
set project [file join $root project i1_board.xpr]
if {![file isfile [file join $root board-manifest.json]] || ![file isfile $project]} {
    error "Staged real board and completed isolated IP project required"
}
set reports [file join $root reports]
if {[file exists $reports]} {error "Preserve previous board implementation evidence"}
file mkdir $reports
set_param general.maxThreads 8
open_project $project
foreach name {ddr4_0 clk_wiz_i1 axi_clock_converter_i1} {
    if {[get_property PROGRESS [get_runs [format "%s_synth_1" $name]]] ne "100%"} {
        error "Actual board IP not synthesized: $name"
    }
}
add_files -norecurse [glob [file join $root rtl *.sv]]
add_files -norecurse [glob [file join $root board *.sv]]
add_files -norecurse [file join $root rtl bootrom.hex]
set_property FILE_TYPE {Memory Initialization Files} [get_files */bootrom.hex]
add_files -fileset constrs_1 -norecurse [list \
    [file join $root board board_ddr.xdc] [file join $root board pl_ddr4_pins.xdc] \
    [file join $root board rgmii_pins.xdc]]
set_property top soc_top_i1_network_ddr [get_filesets sources_1]
set_property STEPS.SYNTH_DESIGN.ARGS.FLATTEN_HIERARCHY none [get_runs synth_1]
set_property STEPS.SYNTH_DESIGN.TCL.PRE [file join $root scripts prepare_board_mem.tcl] [get_runs synth_1]
set_property STEPS.OPT_DESIGN.TCL.PRE [file join $root scripts board_constraints.tcl] [get_runs impl_1]
set_property STEPS.PHYS_OPT_DESIGN.IS_ENABLED true [get_runs impl_1]
set_property STEPS.PLACE_DESIGN.ARGS.DIRECTIVE Explore [get_runs impl_1]
set_property STEPS.PHYS_OPT_DESIGN.ARGS.DIRECTIVE Explore [get_runs impl_1]
set_property STEPS.ROUTE_DESIGN.ARGS.DIRECTIVE Explore [get_runs impl_1]
update_compile_order -fileset sources_1
launch_runs synth_1 -jobs 2
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "Complete board synthesis failed"}
open_run synth_1
report_utilization -hierarchical -file [file join $reports post_synth_utilization.rpt]
write_checkpoint [file join $reports real_board_post_synth.dcp]
close_design
launch_runs impl_1 -to_step route_design -jobs 1
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {
    error "Complete board implementation failed; inspect actual impl_1 logs"
}
open_run impl_1
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
# Never write a bit until timing, DRC, CDC/RDC and every actual IO scenario
# have been reviewed. Short GSIM and a successful route are not board signoff.
close_project
