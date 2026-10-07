# OOC synthesis of one changed synchronous CPU-domain leaf, not a private model.
if {$argc != 2} {error "Expected PRIVATE_CANDIDATE_ROOT TOP"}
lassign $argv root top
set root [file normalize $root]
if {$top ni {CoherentLineCache EthernetPacketDma}} {error "Unexpected ECO partition"}
set out [file join $root partitions $top]
if {[file exists $out]} {error "Preserve prior partition"}
file mkdir $out
set_param general.maxThreads 8
create_project -in_memory -part xczu15eg-ffvb1156-2-i
read_verilog -sv [glob -directory [file join $root rtl] *.sv]
set xdc [file join $out clock.xdc]
set stream [open $xdc w]
puts $stream {create_clock -name leaf_cpu_clock -period 10.000 [get_ports clock]}
close $stream
read_xdc $xdc
synth_design -top $top -part xczu15eg-ffvb1156-2-i -mode out_of_context -flatten_hierarchy none
report_utilization -hierarchical -file [file join $out utilization.rpt]
report_timing_summary -delay_type min_max -file [file join $out timing_summary.rpt]
reset_timing
write_checkpoint [file join $out leaf.dcp]
write_edif [file join $out leaf.edf]
puts "PASS_NETBOOT_CHANGED_LEAF_SYNTH $top"
close_project
