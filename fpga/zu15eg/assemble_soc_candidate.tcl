# Assemble immutable synthesized partitions into a fresh board netlist.
# Args: SOC_DCP IP_SOURCE_DIR TOP_SV BOARD_XDC DDR_PIN_XDC OUTPUT_DIR [CPU_HZ [MIG_XCI [FLOW]]]
if {$argc < 6 || $argc > 9} {error "Expected SOC_DCP IP_SOURCE_DIR TOP_SV BOARD_XDC DDR_PIN_XDC OUTPUT_DIR [CPU_HZ [MIG_XCI [FLOW]]]"}
lassign $argv soc_dcp ip_src top_sv board_xdc pin_xdc out_dir cpu_hz mig_xci flow
if {$flow eq ""} {set flow implement}
if {$flow ni {assemble implement}} {error "Expected assemble or implement flow"}
if {$cpu_hz eq ""} {set cpu_hz 50000000}
if {![string is integer -strict $cpu_hz] || $cpu_hz < 6000000 ||
    $cpu_hz > 200000000 || $cpu_hz % 1000000} {error "CPU_HZ must be whole MHz, 6..200 MHz"}
set cpu_period [expr {1.0e9 / $cpu_hz}]
foreach name {soc_dcp ip_src top_sv board_xdc pin_xdc out_dir} {set $name [file normalize [set $name]]}
file mkdir $out_dir
set_param general.maxThreads 8
create_project -in_memory -part xczu15eg-ffvb1156-2-i
add_files -norecurse $soc_dcp
set_property SCOPED_TO_CELLS u_soc [get_files $soc_dcp]
# XCI registers the already generated DCPs, nested MIG PHY/debug products, and
# non-OOC timing XDC together. Direct IP DCP loading omits those dependencies.
foreach name {ddr4_0 clk_wiz_ddr axi_clock_converter_ddr} {
    set xci [file join $ip_src $name $name.xci]
    if {$name eq "ddr4_0" && $mig_xci ne ""} {set xci [file normalize $mig_xci]}
    if {![file exists $xci]} {error "Missing existing IP descriptor: $xci"}
    read_ip $xci
}
read_verilog -sv $top_sv
synth_design -top soc_top_ddr -part xczu15eg-ffvb1156-2-i -flatten_hierarchy none
# The automatic MIG debug hub remains a black box until opt_design implements it.
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX && NAME != dbg_hub}]]} {
    error "Unresolved functional board partitions: [get_cells -quiet -hier -filter {IS_BLACKBOX && NAME != dbg_hub}]"
}
read_xdc $board_xdc
read_xdc $pin_xdc
set uart_regs [get_cells -quiet -hier -filter {NAME =~ */uart/rxMeta_reg || NAME =~ */uart/rxSync_reg}]
if {[llength $uart_regs] != 2} {error "Expected exactly two UART RX synchronizer registers"}
foreach cell $uart_regs {
    if {![get_property ASYNC_REG $cell]} {error "UART synchronizer constraint missing: $cell"}
}
set cpu [get_clocks -quiet clk_out1_clk_wiz_ddr]
if {[llength $cpu] != 1 || abs([get_property PERIOD $cpu] - $cpu_period) > 0.001} {
    error "Missing real $cpu_hz Hz CPU clock after assembling partitions"
}
report_clocks -file [file join $out_dir clocks.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out_dir assembled_timing.rpt]
write_checkpoint [file join $out_dir assembled.dcp]
puts "SOC_ASSEMBLY: partitions linked with real $cpu_hz Hz clock"
if {$flow eq "assemble"} {
    puts "SOC_ASSEMBLY: saved; placement/routing will use a separate bounded checkpoint continuation"
    close_design
    exit
}
opt_design
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Unresolved black boxes after opt_design"}
# Fail early on reset/clock assembly mistakes, before an expensive placement.
source [file join [file dirname [info script]] audit_reset_cdc.tcl]
audit_board_reset_cdc [file join $out_dir reset_cdc_audit.txt]
audit_cpu_reset_gate [file join $out_dir reset_gate_audit.txt]
place_design -directive Explore
write_checkpoint [file join $out_dir placed_before_phys_opt.dcp]
phys_opt_design -directive Explore
write_checkpoint [file join $out_dir placed.dcp]
report_timing_summary -delay_type min_max -file [file join $out_dir placed_timing.rpt]
route_design -directive Explore -tns_cleanup
phys_opt_design -directive Explore
write_checkpoint [file join $out_dir routed.dcp]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out_dir timing_summary.rpt]
report_timing -delay_type max -max_paths 30 -input_pins -file [file join $out_dir timing_paths.rpt]
report_timing -group clk_out1_clk_wiz_ddr -delay_type max -max_paths 30 -input_pins -file [file join $out_dir cpu_timing_paths.rpt]
report_timing -delay_type min -max_paths 10 -file [file join $out_dir hold_paths.rpt]
report_utilization -hierarchical -file [file join $out_dir utilization.rpt]
report_route_status -file [file join $out_dir route_status.rpt]
report_bus_skew -file [file join $out_dir bus_skew.rpt]
report_clock_interaction -file [file join $out_dir clock_interaction.rpt]
report_cdc -file [file join $out_dir cdc.rpt]
check_timing -verbose -file [file join $out_dir check_timing.rpt]
report_drc -file [file join $out_dir drc.rpt]
set cpu_setup [get_timing_paths -group clk_out1_clk_wiz_ddr -delay_type max -max_paths 1]
puts "DDR CPU $cpu_hz Hz: WNS=[get_property SLACK $cpu_setup] DATA_DELAY=[get_property DATAPATH_DELAY $cpu_setup]"
close_design
