# Rewrite only a private implementation-reference checkpoint to the installed
# tool's current container format. No placement, routes, logic or exceptions
# are edited. The original reference is never overwritten.
if {$argc != 2} {error "Expected QUALIFIED_DONOR_DCP FRESH_PRIVATE_OUTPUT"}
lassign $argv donor output
foreach name {donor output} {set $name [file normalize [set $name]]}
if {![file isfile $donor] || [file exists $output]} {error "Expected donor and fresh output"}
file mkdir $output
set_param general.maxThreads 8
read_checkpoint -help
write_checkpoint -help
open_checkpoint $donor
if {[get_property PART [current_design]] ne "xczu15eg-ffvb1156-2-i" ||
    [llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Wrong donor design"}
report_timing_summary -delay_type min_max -file [file join $output donor_timing.rpt]
report_route_status -file [file join $output donor_route.rpt]
write_checkpoint [file join $output normalized_reference.dcp]
puts "NORMALIZED_REFERENCE_CONTAINER_ONLY NOT_A_CURRENT_RTL_IMPLEMENTATION"
close_design
