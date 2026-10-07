# Normal synthesis/optimization of the proved TX boundary; never a CPU build.
if {$argc != 2} {error "Expected SHORT_PROOF FRESH_OUT"}
lassign $argv proof out
if {[file exists $out]} {error "Preserve existing evidence"}
file mkdir $out
cd $out
set here [file dirname [info script]]
file copy [info script] executed_tx_synth.tcl
foreach source {native_rx_clock.sv native_rgmii.sv} {
    file copy [file join $proof $source] $source
}
file copy [file join $here native_tx_isolation_probe.sv] compiled_probe.sv
set_param general.maxThreads 8
create_project -in_memory -part xczu15eg-ffvb1156-2-i
read_verilog -sv [list native_rx_clock.sv native_rgmii.sv compiled_probe.sv]
synth_design -top native_tx_isolation_probe -mode out_of_context -flatten_hierarchy none
create_clock -name ui250 -period 4.0 [get_ports ui_pad]
opt_design
set outputs [get_cells -hier -filter {REF_NAME == OSERDESE3}]
if {[llength $outputs]!=6} {error "TX boundary must normally lower to six ODDR-mode OSERDES"}
foreach c $outputs {
    if {![get_property ODDR_MODE $c]} {error "Unexpected normal output lowering"}
    set driver [get_pins -leaf -of_objects [get_nets -segments -of_objects [get_pins $c/CLK]] -filter {DIRECTION == OUT}]
    if {$driver ne "pad_buffer/O"} {error "Pad outputs not on isolated common tree: $c $driver"}
}
set rise [get_pins -of_objects [get_cells boundary/tx_control_ddr] -filter {REF_PIN_NAME == "D[0]"}]
set fall [get_pins -of_objects [get_cells boundary/tx_control_ddr] -filter {REF_PIN_NAME == "D[4]"}]
set rn [get_nets -segments -of_objects $rise]
set fn [get_nets -segments -of_objects $fall]
if {$rn ne $fn} {error "Registered fall symbol not merged when ER=0"}
set driver [get_pins -leaf -of_objects $rn -filter {DIRECTION == OUT}]
if {[get_property REF_NAME [get_cells -of_objects $driver]] ne "FDCE"} {error "Control symbols must come straight from the resettable stage FF"}
if {[get_property COMPENSATION [get_cells clock_dut/pll]] ne "INTERNAL"} {error "ETH PLL source topology drift"}
report_property -file control_stage.rpt [get_cells -of_objects $driver]
report_property -file control_ddr.rpt [get_cells boundary/tx_control_ddr]
report_property -file pll.rpt [get_cells clock_dut/pll]
report_utilization -hierarchical -file utilization.rpt
report_clocks -file clocks.rpt
write_checkpoint post_opt.dcp
puts "PASS_NATIVE_TX_ISOLATION_NORMAL_SYNTH SIX_PAD_DDRS_REGISTERED_CTL_NO_CPU_NO_BIT"
close_design
