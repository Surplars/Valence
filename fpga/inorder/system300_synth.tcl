# Frozen managed CPU/Spinor/fabric/CMU. Functional receipt is a precondition.
if {$argc != 2} {error "usage: system300_synth.tcl FROZEN_RTL FRESH_OUTPUT"}
lassign $argv rtl output
set allowed [string tolower [file normalize E:/VM/Share/Valence-rtl/Valence-InOrder]]
foreach p [list $rtl $output] {
    if {![string match "${allowed}/*" [string tolower [file normalize $p]]]} {error "outside designated root"}
}
if {[file exists $output]} {error "fresh synthesis output required"}
file mkdir $output
set_param general.maxThreads 8
puts "VIVADO_THREADS [get_param general.maxThreads]"
create_project -in_memory -part xczu15eg-ffvb1156-2-i
read_verilog -sv [lsort [glob -directory $rtl *.sv]]
set fd [open [file join $output context.xdc] w]
puts $fd {create_clock -name i1_cpu300 -period 3.333333333 [get_ports rawCpuClock]}
puts $fd {create_clock -name i1_vpu300 -period 3.333333333 [get_ports rawVpuClock]}
puts $fd {create_clock -name i1_system300 -period 3.333333333 [get_ports systemClock]}
puts $fd {set_clock_uncertainty -setup 0.100 [get_clocks {i1_cpu300 i1_vpu300 i1_system300}]}
puts $fd {set_clock_uncertainty -hold 0.080 [get_clocks {i1_cpu300 i1_vpu300 i1_system300}]}
# OOC pad context; internal clock domains stay at 300 MHz. No board signoff.
puts $fd {set_input_delay -clock i1_system300 -max 0.333 [get_ports -filter {DIRECTION == IN && NAME != rawCpuClock && NAME != rawVpuClock && NAME != systemClock}]}
puts $fd {set_input_delay -clock i1_system300 -min 0.000 [get_ports -filter {DIRECTION == IN && NAME != rawCpuClock && NAME != rawVpuClock && NAME != systemClock}]}
puts $fd {set_output_delay -clock i1_system300 -max 0.333 [get_ports -filter {DIRECTION == OUT && NAME !~ io_retire* && NAME != io_protocolError}]}
puts $fd {set_output_delay -clock i1_system300 -min 0.000 [get_ports -filter {DIRECTION == OUT && NAME !~ io_retire* && NAME != io_protocolError}]}
puts $fd {set_output_delay -clock i1_cpu300 -max 0.333 [get_ports -filter {NAME =~ io_retire* || NAME == io_protocolError}]}
puts $fd {set_output_delay -clock i1_cpu300 -min 0.000 [get_ports -filter {NAME =~ io_retire* || NAME == io_protocolError}]}
close $fd
read_xdc [file join $output context.xdc]
synth_design -top I1System300Context -part xczu15eg-ffvb1156-2-i -mode out_of_context -flatten_hierarchy rebuilt -directive Default
# The always-on input has an external global source. Managed domains contain real BUFGCE cells.
# Three explicit global clock buffers are present in this port-capture context.
write_checkpoint [file join $output synthesized.dcp]
report_utilization -hierarchical -file [file join $output utilization_synth.rpt]
report_clocks -file [file join $output clocks.rpt]
set fd [open [file join $output cdc_registers.tsv] w]
puts $fd "name\tref\tclock\tasync_reg"
foreach cell [lsort [get_cells -quiet -hierarchical -filter {IS_PRIMITIVE == TRUE && (REF_NAME =~ FD* || REF_NAME =~ RAM* || REF_NAME =~ DSP* || REF_NAME =~ BUFG*)}]] {
    set pins [get_pins -quiet -of_objects $cell -filter {IS_CLOCK == TRUE}]
    puts $fd "[get_property NAME $cell]\t[get_property REF_NAME $cell]\t[get_clocks -quiet -of_objects $pins]\t[get_property ASYNC_REG $cell]"
}
close $fd
puts "I1_SYSTEM300_SYNTH_DONE NO_IMPL_NO_BIT"
close_design
close_project
