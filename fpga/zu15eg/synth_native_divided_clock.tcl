if {$argc!=3} {error "Expected SOURCE_DIR BASE_DCP FRESH_OUTPUT"}
lassign $argv src baseline out
if {[file exists $out]} {error "Preserve evidence"}
file mkdir $out
cd $out
file copy [info script] executed_synth.tcl
file copy [file join $src native_gmac_divided_clock.sv] compiled_clock_source.sv
set_param general.maxThreads 8
create_project -in_memory -part xczu15eg-ffvb1156-2-i
read_verilog -sv [file join $src native_gmac_divided_clock.sv]
synth_design -top native_gmac_divided_probe -mode out_of_context -flatten_hierarchy none
create_clock -name ui_proxy -period 4 [get_ports ui_pad]
opt_design
source [file join $src native_divided_clock_constraints.tcl]
valence_divided_tx_clocks clock_dut
if {[get_property COMPENSATION [get_cells clock_dut/pll]] ne "INTERNAL"} {error "Unexpected normal PLL compensation"}
write_checkpoint post_opt.dcp
write_edif post_opt.edf
report_clocks -file clocks.rpt
check_timing -verbose -file check_timing.rpt
set f [open structure.rpt w]
foreach c [get_cells -hier -filter {IS_PRIMITIVE}] {
    puts $f "$c REF=[get_property REF_NAME $c]"
    report_property -append -file primitive_properties.rpt $c
    foreach p [get_pins -of_objects $c] {puts $f "$p NET=[get_nets -quiet -of_objects $p]"}
}
close $f
close_design
if {$baseline ne "NONE"} {
    open_checkpoint $baseline
    set f [open resources.rpt w]
    foreach s [get_sites -filter {NAME =~ BUFGCE_DIV_X* || NAME =~ BUFGCE_X0Y*}] {
        puts $f "$s REGION=[get_clock_regions -of_objects $s] OCCUPANT=[get_cells -quiet -of_objects $s]"
    }
    close $f
    close_design
}
puts "PASS_NATIVE_DIVIDED_CLOCK_OOC NO_CPU_SYNTHESIS_NO_BIT"
