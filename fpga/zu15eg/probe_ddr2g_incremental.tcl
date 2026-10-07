# Bounded alternative physical-reference import; current full DDR2G netlist
# is always the candidate's own clean optimized DCP. No constraints relaxed.
if {$argc != 2} {error "Expected PRIVATE_ROOT NORMALIZED_REFERENCE_DCP"}
lassign $argv root reference
foreach name {root reference} {set $name [file normalize [set $name]]}
set out [file join $root incremental-probe-r2]
if {[file exists $out]} {error "Preserve earlier probe"}
file mkdir $out
cd $out
set_param general.maxThreads 8
open_checkpoint [file join $root implementation optimized.dcp]
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]] ||
    [llength [get_cells -quiet -hier -filter {REF_NAME == FloatingPointSystem}]] != 1} {error "Wrong own complete SoC"}
write_xdc -type timing before_reference.xdc
# Force incremental selection skips rule/ML quality selection only. Timing
# constraints, current RTL and STA checks remain unchanged and mandatory.
read_checkpoint -incremental -force_incr -directive TimingClosure $reference
write_xdc -type timing after_reference.xdc
report_incremental_reuse -file incremental_reuse.rpt
write_checkpoint imported_reference.dcp
puts "PASS_CURRENT_DDR2G_INCREMENTAL_REFERENCE_IMPORT NO_BIT_NO_TIMING_QUALIFICATION"
close_design
