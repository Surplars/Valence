# Normal synthesis of only the changed clock/reset boundaries, then inspect
# the saved complete board for legal local ECO resources. No CPU synthesis.
if {$argc != 3} {error "Expected SOURCE_DIR BASELINE_DCP FRESH_OUTPUT"}
lassign $argv src baseline out
if {[file exists $out]} {error "Preserve prior evidence"}
file mkdir $out
set taskBatchOutput $out
set savedArgc $argc
set savedArgv $argv
foreach {top folder} {native_gmac_clock_probe eth native_gmac_rx_clock rx} {
    set argc 3
    set argv [list [file join $src native_gmac_clocks.sv] [file join $taskBatchOutput $folder] $top]
    source [file join $src synth_native_rx_clock.tcl]
}
set argc $savedArgc
set argv $savedArgv
set out $taskBatchOutput
cd $out
create_project -in_memory -part xczu15eg-ffvb1156-2-i
read_verilog -sv [file join $src native_tx_reset_boundary.sv]
synth_design -top native_tx_reset_boundary -mode out_of_context -flatten_hierarchy none
create_clock -name raw -period 8 [get_ports clock_tx]
create_clock -name forward -period 8 -waveform {2 6} [get_ports clock_forward]
opt_design
write_checkpoint reset.dcp
write_edif reset.edf
set f [open reset_cells.rpt w]
foreach cell [get_cells -hier -filter IS_PRIMITIVE] {puts $f "$cell [get_property REF_NAME $cell] [get_property ASYNC_REG $cell]"}
close $f
close_project
open_checkpoint $baseline
set f [open available_resources.rpt w]
foreach name {MMCM_X0Y0 MMCM_X0Y1 MMCM_X0Y2 MMCM_X0Y3 MMCM_X0Y4 BUFGCE_X0Y61 BUFGCE_X0Y72 BUFGCE_X0Y73 BUFGCE_X0Y74 BUFGCE_X0Y75} {
    set site [get_sites -quiet $name]
    puts $f "$name REGION=[get_clock_regions -of_objects $site] OCCUPANT=[get_cells -of_objects $site]"
}
foreach name {native_rx_pll u_eth_clk_wiz/inst/clkout1_buf u_eth_clk_wiz/inst/clkout2_buf rx_clock_buffer u_rgmii/tx_clock_ddr} {
    report_property -file [string map {/ _} $name].rpt [get_cells $name]
    foreach pin [get_pins -of_objects [get_cells $name]] {puts $f "$pin NET=[get_nets -of_objects $pin]"}
}
foreach cell [get_cells -quiet {tx_reset_pipe_reg*}] {
    puts $f "$cell [get_property REF_NAME $cell] LOC=[get_property LOC $cell] BEL=[get_property BEL $cell]"
    foreach pin [get_pins -of_objects $cell] {puts $f "$pin NET=[get_nets -of_objects $pin]"}
}
close $f
close_design
puts "NATIVE_TX90_NORMAL_BOUNDARIES_COMPLETE NO_CPU_SYNTHESIS_NO_BIT"
