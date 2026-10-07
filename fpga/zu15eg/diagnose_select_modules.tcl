# Diagnostic only: frozen helper RTL, virtual 10ns I/O budget, no CPU/bit.
if {$argc != 2} {error "Expected RTL_DIR OUTPUT_DIR"}
lassign $argv rtl_dir out
set rtl_dir [file normalize $rtl_dir]
set out [file normalize $out]
file mkdir $out
set_param general.maxThreads 8
foreach top {CircularIssueSelector IntegerAlu ParallelCompletionPayload} {
    set started [clock seconds]
    set local_out [file join $out $top]
    file mkdir $local_out
    puts "SELECT_PROBE: begin top=$top"
    create_project -in_memory -part xczu15eg-ffvb1156-2-i
    foreach name {CircularIssueSelector IntegerAlu IntegerBitManip ParallelCompletionPayload} {
        read_verilog -sv [file join $rtl_dir $name.sv]
    }
    set xdc [file join $local_out io_clock.xdc]
    set stream [open $xdc w]
    puts $stream {create_clock -name probe_virtual -period 10.000}
    puts $stream {set_input_delay 0 -clock probe_virtual [get_ports -filter {DIRECTION == IN}]}
    puts $stream {set_output_delay 0 -clock probe_virtual [get_ports -filter {DIRECTION == OUT}]}
    close $stream
    read_xdc $xdc
    synth_design -top $top -part xczu15eg-ffvb1156-2-i -mode out_of_context \
        -flatten_hierarchy none -debug_log
    if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Helper black box remains"}
    report_utilization -hierarchical -file [file join $local_out utilization.rpt]
    report_timing_summary -delay_type min_max -file [file join $local_out timing.rpt]
    report_timing -max_paths 5 -nworst 1 -file [file join $local_out paths.rpt]
    write_checkpoint [file join $local_out helper.dcp]
    puts "SELECT_PROBE: end top=$top elapsed_seconds=[expr {[clock seconds] - $started}]"
    close_project
}
puts "SELECT_PROBE: complete; isolated helpers do not establish full-backend timing"
