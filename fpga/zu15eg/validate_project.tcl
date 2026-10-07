# Short hardware checks: only RAM synthesis, followed by board RTL elaboration.
# This is NOT post-route timing signoff and never builds a bitstream.
set rtl_dir {E:/VM/Share/Valence-rtl/board-40m}
set report_dir [file join $rtl_dir reports]
file mkdir $report_dir
set_param general.maxThreads 8
create_project -in_memory -part xczu15eg-ffvb1156-2-i
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
read_verilog -sv [glob -directory $rtl_dir *.sv]
synth_design -top SynchronousDataRam -mode out_of_context -flatten_hierarchy rebuilt
create_clock -name ram_clock -period 25.000 [get_ports clock]
report_utilization -file [file join $report_dir ram_synth_utilization.rpt]
report_timing_summary -file [file join $report_dir ram_synth_timing.rpt]
set urams [get_cells -hier -filter {REF_NAME =~ URAM288*}]
puts "BOARD40: memory-only synthesis contains [llength $urams] UltraRAM blocks"
if {[llength $urams] != 32} {error "1 MiB x64 memory must map to 32 UltraRAM blocks"}
close_project
open_project {D:/TOOLS/projects/vivadoProjects/ZU15EG/ZU15EG.xpr}
synth_design -rtl -name rtl_1 -top soc_top
puts "BOARD40: complete board RTL elaboration passed (not full synthesis/timing)"
close_project
