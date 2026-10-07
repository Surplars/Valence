# Synthesis-only diagnosis of the exported SoC with true RTL hierarchy retained.
# vivado -mode batch -source vivado-hierarchy-audit.tcl -tclargs RTL_DIRECTORY FULL_PART PERIOD_NS TOP
if {$argc != 4} {
    error "usage: vivado-hierarchy-audit.tcl RTL_DIRECTORY FULL_PART PERIOD_NS TOP"
}
set rtl_dir [file normalize [lindex $argv 0]]
set target_part [lindex $argv 1]
set period_ns [lindex $argv 2]
set top_module [lindex $argv 3]
if {$top_module ni {CompactSocTimingTop CurrentSocTimingTop}} {
    error "Unsupported top module"
}
if {![string is double -strict $period_ns] || $period_ns <= 0} {
    error "PERIOD_NS must be positive"
}
set matched_parts [get_parts -quiet $target_part]
if {[llength $matched_parts] != 1 || [get_property NAME $matched_parts] ne $target_part} {
    error "Specify an exact installed FPGA part"
}
cd $rtl_dir
set source_files [glob -nocomplain *.sv]
if {[llength $source_files] == 0} { error "No exported SystemVerilog files" }
create_project -in_memory -part $target_part
set_param general.maxThreads 8
read_verilog -sv $source_files
synth_design -top $top_module -part $target_part -mode out_of_context \
    -flatten_hierarchy none -verilog_define ENABLE_INITIAL_MEM_
create_clock -name core_clock -period $period_ns [get_ports clock]
file mkdir reports
report_utilization -file reports/post_synth_utilization.rpt
report_utilization -hierarchical -file reports/post_synth_hierarchical_utilization.rpt
report_timing_summary -report_unconstrained -file reports/post_synth_timing.rpt
report_timing -delay_type max -max_paths 30 -file reports/post_synth_paths.rpt
puts "Hierarchy audit complete; placement skipped"
