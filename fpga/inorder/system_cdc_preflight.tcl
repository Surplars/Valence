set_param general.maxThreads 8
open_checkpoint [file join [file dirname [info script]] synth synthesized.dcp]
source [file join [file dirname [info script]] system_cdc.tcl]
set output [file join [file dirname [info script]] cdc-preflight]
file mkdir $output
spinor_cdc::apply $output
spinor_cdc::coverage $output
report_cdc -details -file [file join $output cdc.rpt]
write_checkpoint [file join $output constrained.dcp]
puts "SYSTEM_CDC_PREFLIGHT_PASS"
close_design
