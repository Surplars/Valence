# Tiny standalone clock module only. Inspect normal AUTO lowering, not CPU.
if {$argc < 2 || $argc > 3} {error "Expected SOURCE_SV FRESH_OUTPUT_DIR ?CLOCK_TOP?"}
lassign $argv sv out top
if {$top eq ""} {set top native_rx_clock}
switch -- $top {
    native_rx_clock {set primitive mmcm; set pad pad_clock; set period 8.0; set feedback feedback_buffer; set compensation ZHOLD}
    native_eth_clock_probe {set primitive clock_dut/pll; set pad ui_pad; set period 4.0; set feedback ""; set compensation INTERNAL}
    native_gmac_clock_probe {set primitive clock_dut/mmcm; set pad ui_pad; set period 4.0; set feedback ""; set compensation INTERNAL}
    native_gmac_rx_clock {set primitive mmcm; set pad pad_clock; set period 8.0; set feedback feedback_buffer; set compensation ZHOLD}
    default {error "Clock module only; full SoC synthesis forbidden here"}
}
if {[file exists $out]} {error "Preserve existing evidence"}
file mkdir $out
cd $out
file copy $sv compiled_clock_source.sv
file copy [info script] executed_synth.tcl
set_param general.maxThreads 8
create_project -in_memory -part xczu15eg-ffvb1156-2-i
read_verilog -sv $sv
synth_design -top $top -mode out_of_context -flatten_hierarchy none
create_clock -name clock_input -period $period [get_ports $pad]
report_property [get_cells $primitive]
report_property -file primitive_post_synth.rpt [get_cells $primitive]
write_checkpoint post_synth.dcp
opt_design
report_property [get_cells $primitive]
report_property -file primitive_post_opt.rpt [get_cells $primitive]
if {[get_property COMPENSATION [get_cells $primitive]] ne $compensation} {
    error "Clock compensation differs from actual input/feedback topology"
}
if {$feedback ne "" && [llength [get_cells -quiet $feedback]] != 1} {error "Deskew feedback disappeared"}
report_clocks -file clocks.rpt
write_checkpoint post_opt.dcp
write_edif post_opt.edf
puts "NATIVE_RX_CLOCK_OOC_COMPLETE CLOCK_MODULE_ONLY_NO_CPU_OR_BIT"
close_design
