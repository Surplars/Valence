# One CPU synthesis, real MAC/ROM linking, then one CPU route. No board/bit claim.
# CORE_RTL SOC_RTL ETHERNET_XCI ROM_DCP ROM_STUB FRESH_REPORT_ROOT
if {$argc ni {6 7}} { error "Expected CORE_RTL SOC_RTL ETHERNET_XCI ROM_DCP ROM_STUB REPORT_ROOT ?resume|link-only?" }
set mode [expr {$argc == 7 ? [lindex $argv 6] : "fresh"}]
if {$mode ni {fresh resume link-only}} { error "Unsupported stage" }
set resume [expr {$mode ne "fresh"}]
set link_only [expr {$mode eq "link-only"}]
lassign $argv batch_core batch_soc ethernet_xci rom_dcp rom_stub batch_reports
foreach name {batch_core batch_soc ethernet_xci rom_dcp rom_stub batch_reports} {
    set $name [file normalize [set $name]]
}
cd $batch_soc
if {[file exists $batch_reports] && !$resume} { error "Fresh report directory required" }
file mkdir $batch_reports
set scripts [file dirname [info script]]
set core_reports [file join $batch_reports MachineCore]
set soc_reports [file join $batch_reports EthernetSocTop]
if {$link_only} { set soc_reports [file join $batch_reports EthernetSocTop_cdc_r2] }
file mkdir $soc_reports
set_param general.maxThreads 8
if {$link_only} { set_param general.maxThreads 4 }
# Same OOC clock convention; production compiler-pruned ports differ from old bare CPU reports.
if {!$resume} {
set argc 6
set argv [list $batch_core xczu15eg-ffvb1156-2-i 10.0 MachineCore synth $core_reports]
source [file join $scripts .. vivado-module-ooc.tcl]
write_edif [file join $core_reports cpu.edf]
close_project
} else {
    foreach file {post_synth.dcp cpu.edf} {
        if {![file exists [file join $core_reports $file]]} { error "Cannot resume: CPU synthesis proof missing" }
    }
}

# Export the already initialized real BMG; do not regenerate the user's IP.
if {![file exists [file join $soc_reports rom.edf]]} {
    open_checkpoint $rom_dcp
    write_edif [file join $soc_reports rom.edf]
    close_project
}

# A real synthesized CPU partition replaces a temporary port-only declaration.
# This avoids a second full CPU synthesis; unresolved black boxes are forbidden.
if {$resume && [file exists [file join $soc_reports wrapper_post_synth.dcp]]} {
    open_checkpoint [file join $soc_reports wrapper_post_synth.dcp]
} else {
set stream [open [file join $batch_soc MachineCore.sv] r]
set cpu_rtl [read $stream]
close $stream
if {![regexp {(?s)(module MachineCore\s*\(.*?\);)} $cpu_rtl -> header]} {
    error "Cannot extract actual CPU interface"
}
set cpu_stub [file join $soc_reports cpu_partition_stub.v]
set stream [open $cpu_stub w]
puts $stream "(* black_box = \"yes\" *) $header\nendmodule"
close $stream
create_project -in_memory -part xczu15eg-ffvb1156-2-i
set sources {}
foreach file [glob [file join $batch_soc *.sv]] {
    if {[file tail $file] ne "MachineCore.sv"} { lappend sources $file }
}
read_verilog -sv $sources
read_verilog $cpu_stub
read_verilog $rom_stub
# Vivado propagates the generated hierarchical IP DCPs and license metadata.
read_ip $ethernet_xci
set clocks [file join $soc_reports synthesis_clocks.xdc]
set stream [open $clocks w]
puts $stream {create_clock -name cpu_clock -period 10.0 [get_ports clock]}
puts $stream {create_clock -name ethernet_clock -period 8.0 [get_ports io_ethernetClock]}
puts $stream {create_clock -name ethernet_ref_clock -period 3.0 [get_ports io_ethernetRefClock]}
close $stream
read_xdc $clocks
synth_design -top EthernetSocTop -mode out_of_context -flatten_hierarchy none
write_checkpoint [file join $soc_reports wrapper_post_synth.dcp]
}
# Native MAC XDC binds the PHY clock. Do not redefine it or create a virtual substitute.
set phy_clock [get_clocks -quiet -of_objects [get_ports io_rgmiiRxc]]
if {[llength $phy_clock] != 1 || abs([get_property PERIOD $phy_clock] - 8.0) > 0.001} {
    error "Actual PHY RX clock is missing or not the 1G 8ns configuration"
}
set cpu_cell [get_cells -quiet -hier -filter {REF_NAME == MachineCore}]
set rom_cell [get_cells -quiet soc/platform/rom/memory]
if {[llength $cpu_cell] != 1 || ![get_property IS_BLACKBOX $cpu_cell]} { error "CPU partition contract changed" }
if {[llength $rom_cell] != 1 || ![get_property IS_BLACKBOX $rom_cell]} { error "ROM contract changed" }
update_design -cells $cpu_cell -from_file [file join $core_reports cpu.edf]
update_design -cells $rom_cell -from_file [file join $soc_reports rom.edf]
set unresolved [get_cells -quiet -hier -filter {IS_BLACKBOX}]
if {[llength $unresolved]} { error "Unresolved actual IP in integration: $unresolved" }
source [file join $scripts cdc_constraints.tcl]
set bridges [get_cells -quiet -hier -filter {REF_NAME =~ RegisterClockDomainBridge*}]
if {[llength $bridges] != 2} { error "Expected actual UART and Ethernet CDC bridges" }
foreach bridge $bridges { valence_register_cdc_constraints $bridge 8.0 }
set streams [get_cells -quiet -hier -filter {REF_NAME =~ StreamClockDomainFifo*}]
if {[llength $streams] ni {0 4}} { error "Expected zero (external DMA) or four network stream FIFOs" }
foreach fifo $streams { valence_stream_cdc_constraints $fifo 8.0 }
puts "ETHERNET_DMA_STREAM_CDC_COUNT [llength $streams]"
# IRQ sources are registered in the peripheral domain before the CPU synchronizers.
set irq_captures [get_cells -quiet -hier -filter {NAME =~ */ethernetIrq_irq/stages_reg?0? || NAME =~ */uartIrq_synchronizer/stages_reg?0?}]
if {[llength $irq_captures] != 2} { error "Actual IRQ synchronizer count changed" }
foreach capture $irq_captures {
    set ends [get_pins -of_objects $capture -filter {REF_PIN_NAME == D}]
    set sources [get_cells -of_objects [all_fanin -flat -startpoints_only -to $ends]]
    valence_cdc_bus $sources $capture 8.0 registered_irq_level
}
report_utilization -hierarchical -file [file join $soc_reports post_synth_utilization.rpt]
report_timing_summary -report_unconstrained -file [file join $soc_reports post_synth_timing.rpt]
report_cdc -details -file [file join $soc_reports post_synth_cdc.rpt]
report_clock_interaction -file [file join $soc_reports post_synth_clock_interaction.rpt]
write_checkpoint [file join $soc_reports integrated_post_synth.dcp]
puts "ETHERNET_SOC_REAL_IP_SYNTH_COMPLETE"
close_project
if {$link_only} { puts "ETHERNET_LINK_ONLY_COMPLETE; cached identical CPU reused, no CPU CAD"; exit }

open_checkpoint [file join $core_reports post_synth.dcp]
opt_design
place_design
report_utilization -file [file join $core_reports post_place_utilization.rpt]
report_timing_summary -report_unconstrained -file [file join $core_reports post_place_timing.rpt]
write_checkpoint [file join $core_reports post_place.dcp]
route_design
report_utilization -file [file join $core_reports post_route_utilization.rpt]
report_timing_summary -report_unconstrained -file [file join $core_reports post_route_timing.rpt]
report_timing -delay_type max -max_paths 30 -file [file join $core_reports post_route_paths.rpt]
report_timing -delay_type min -max_paths 10 -file [file join $core_reports post_route_hold_paths.rpt]
source [file join $scripts .. vivado-module-path-details.tcl]
valence_module_path_details $core_reports
write_checkpoint [file join $core_reports post_route.dcp]
close_project
puts "ETHERNET_CPU_BATCH_COMPLETE; OOC is not whole-board timing qualification"
