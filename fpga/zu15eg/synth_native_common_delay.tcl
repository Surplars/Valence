# Dedicated cascade pin feasibility and source-synchronous IO timing only.
if {$argc<2 || $argc>3} {error "Expected SOURCE_DIR FRESH_OUT ?TOP?"}
lassign $argv src out top
if {$top eq ""} {set top native_tx_common_probe}
if {$top ni {native_tx_common_probe native_tx_clock_delay_probe}} {error "Tiny IO probe only"}
if {[file exists $out]} {error "Preserve evidence"}
file mkdir $out
cd $out
file copy [file join $src native_tx_common_delay.sv] compiled_source.sv
file copy [info script] executed_synth.tcl
set_param general.maxThreads 8
create_project -in_memory -part xczu15eg-ffvb1156-2-i
read_verilog -sv [file join $src native_tx_common_delay.sv]
synth_design -top $top -mode out_of_context -flatten_hierarchy none
create_clock -name raw_proxy -period 8 [get_ports raw_input]
create_clock -name ref_proxy -period 2 [get_ports ref_input]
if {$top eq "native_tx_clock_delay_probe"} {
    # Choose the same-symbol setup / next-symbol hold edge. Keep ALL actual
    # propagation through the clock DDR, cascade and OBUF. Offset the output
    # delays by the SAME edge-selection bias, so required times do not gain
    # that bias. Never set source latency: it would replace propagation here.
    create_generated_clock -name phy_tx_capture -source [get_pins clock_ddr/CLK] \
        -edges {1 2 3} -edge_shift {1.6 1.6 1.6} [get_ports eth_txc]
} else {
    create_generated_clock -name phy_tx_capture -source [get_pins clock_ddr/CLK] -divide_by 1 -invert [get_ports eth_txc]
}
set_clock_uncertainty 0.100 [get_clocks raw_proxy]
foreach {port pin} {{eth_txd[0]} AC11 {eth_txd[1]} AC12 {eth_txd[2]} AA6 {eth_txd[3]} AA12 eth_tx_ctl AB8 eth_txc AC8} {
    set_property PACKAGE_PIN $pin [get_ports $port]
    set_property IOSTANDARD LVCMOS18 [get_ports $port]
    set_property DRIVE 8 [get_ports $port]
    set_property SLEW FAST [get_ports $port]
}
set_property LOC BUFGCE_X0Y61 [get_cells raw_buffer]
set_property LOC BUFGCE_X0Y63 [get_cells ref_buffer]
set_property USER_CLOCK_ROOT X3Y2 [get_nets -of_objects [get_pins raw_buffer/O]]
set_property USER_CLOCK_ROOT X3Y2 [get_nets -of_objects [get_pins ref_buffer/O]]
set_false_path -from [get_ports reset]
foreach extra {{} {-clock_fall -add_delay}} {
    set bias 0
    if {$top eq "native_tx_clock_delay_probe"} {set bias 1.6}
    set_output_delay -clock phy_tx_capture -max [expr {1.250+$bias}] {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
    set_output_delay -clock phy_tx_capture -min [expr {-1.250+$bias}] {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
}
opt_design
write_checkpoint post_opt.dcp
place_design
route_design
write_checkpoint routed.dcp
set f [open structure.rpt w]
foreach c [get_cells -hier -filter {IS_PRIMITIVE}] {
    puts $f "$c REF=[get_property REF_NAME $c] LOC=[get_property LOC $c] BEL=[get_property BEL $c]"
}
close $f
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_io.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_clocks -file clocks.rpt
report_drc -file drc.rpt
if {$top eq "native_tx_clock_delay_probe"} {
    set original [list [get_property SLACK [get_timing_paths -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type max -max_paths 1]] \
        [get_property SLACK [get_timing_paths -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min -max_paths 1]]]
    create_generated_clock -name phy_tx_capture -source [get_pins clock_ddr/CLK] \
        -edges {1 2 3} -edge_shift {0.1 0.1 0.1} [get_ports eth_txc]
    foreach extra {{} {-clock_fall -add_delay}} {
        set_output_delay -clock phy_tx_capture -max 1.350 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
        set_output_delay -clock phy_tx_capture -min -1.150 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
    }
    report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file equivalent_offset_tx_io.rpt
    set equivalent [list [get_property SLACK [get_timing_paths -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type max -max_paths 1]] \
        [get_property SLACK [get_timing_paths -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min -max_paths 1]]]
    foreach a $original b $equivalent {if {abs($a-$b)>0.001} {error "Edge offset changed physical timing: $original $equivalent"}}
    puts "EQUIVALENT_EDGE_OFFSETS_PRESERVE_PHYSICAL_SLACK $original $equivalent IO_BUDGET_REMAINS_1.25NS"
}
puts "NATIVE_COMMON_DELAY_PAD_PROBE_COMPLETE NO_CPU_NO_BOARD_QUALIFICATION_NO_BIT"
close_design
