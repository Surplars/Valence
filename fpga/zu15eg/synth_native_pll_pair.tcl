# Tiny normal synthesis plus existing-device resource inspection. No CPU synth.
if {$argc != 3} {error "Expected SOURCE_DIR BASE_DCP FRESH_OUTPUT"}
lassign $argv src baseline out
if {[file exists $out]} {error "Preserve existing evidence"}
file mkdir $out
cd $out
file copy [file join $src native_gmac_pll_pair.sv] compiled_clock_source.sv
file copy [info script] executed_synth.tcl
set_param general.maxThreads 8
create_project -in_memory -part xczu15eg-ffvb1156-2-i
read_verilog -sv [file join $src native_gmac_pll_pair.sv]
synth_design -top native_gmac_pll_pair_probe -mode out_of_context -flatten_hierarchy none
create_clock -name ui_proxy -period 4 [get_ports ui_pad]
opt_design
foreach c {clock_dut/tx_pll clock_dut/delay_pll} {
    if {[get_property REF_NAME [get_cells $c]] ne "PLLE4_ADV" || [get_property COMPENSATION [get_cells $c]] ne "INTERNAL"} {
        error "Unexpected normal PLL lowering"
    }
    set_property PHASESHIFT_MODE WAVEFORM [get_cells $c]
    report_property -file [string map {/ _} $c].rpt [get_cells $c]
}
report_clocks -file clocks.rpt
write_checkpoint post_opt.dcp
write_edif post_opt.edf
close_design
open_checkpoint $baseline
set f [open resources.rpt w]
foreach s [get_sites -filter {SITE_TYPE == PLL || SITE_TYPE == PLLE4_ADV || NAME =~ PLL_X* || NAME =~ BUFGCE_X0Y*}] {
    puts $f "$s REGION=[get_clock_regions -of_objects $s] OCCUPANT=[get_cells -quiet -of_objects $s]"
}
close $f
close_design
puts "PASS_NATIVE_PLL_PAIR_OOC NORMAL_COMPENSATION_INTERNAL NO_CPU_SYNTHESIS_NO_BIT"
