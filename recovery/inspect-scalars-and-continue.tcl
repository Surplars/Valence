set repo [file normalize [lindex $argv 0]]
set target [file normalize [lindex $argv 1]]
set out [file normalize [lindex $argv 2]]
set profile [lindex $argv 3]
cd $out
open_checkpoint $target
update_timing
source [file join $repo fpga common common_cdc.tcl]
set f [open [file join $repo fpga common recovery_map_constraints.tcl]];set text [read $f];close $f
eval [string range $text [string first {namespace eval board_prep} $text] [expr {[string first {puts "PREPARATION_TOOL} $text]-1}]]
board_prep::install_cache_helpers
set f [open scalar-census.tcllist w]
set failures {}
foreach c [get_cells -quiet -hier -filter {NAME =~ u_soc/crossing/* && REF_NAME =~ CdcLevel*}] {
 set h [get_property NAME $c]
 set first [format {%s/stages_reg[0]} $h]
 set status [catch {common_cdc::level $h} result]
 puts $f [list scalar $h status $status result $result]
 if {$status} {
  lappend failures [list $h $result]
  foreach tail {D CE CLR C} {
   set p [common_cdc::one get_pins $first/$tail]
   puts $f [list first_pin $first/$tail net_types [lsort -unique [get_property TYPE [get_nets -segments -of_objects $p]]] drivers [common_cdc::drivers $first/$tail]]
  }
  puts $f [list first_ref [get_property REF_NAME [get_cells $first]] first_init [get_property INIT [get_cells $first]]]
 }
 flush $f
}
puts $f [list all_scalar_failures $failures]
close $f
puts "SCALAR_CENSUS_COMPLETE failures=$failures DESIGN_REMAINS_OPEN"
flush stdout
set continuation [file join $out continue.tcl]
for {set i 0} {$i<900 && ![file exists $continuation]} {incr i} {after 1000}
if {![file exists $continuation]} {puts SCALAR_CONTINUATION_TIMEOUT_NO_IMPLEMENTATION;exit 2}
source $continuation
