# Frozen pure cached CPU + Spinor + native CDC; synthesis phase of one implementation.
if {$argc != 2} {error "usage: spinor300_synth.tcl FROZEN_RTL FRESH_OUTPUT"}
lassign $argv rtl output
set allowed [string tolower [file normalize E:/VM/Share/Valence-rtl/Valence-InOrder]]
foreach p [list $rtl $output] {
    if {![string match "${allowed}/*" [string tolower [file normalize $p]]]} {error "outside designated root"}
}
if {[file exists $output]} {error "fresh synthesis output required"}
set sources [lsort [glob -nocomplain -directory $rtl *.sv]]
if {![llength $sources]} {error "frozen RTL missing"}
file mkdir $output
set_param general.maxThreads 8
puts "VIVADO_THREADS [get_param general.maxThreads]"
create_project -in_memory -part xczu15eg-ffvb1156-2-i
read_verilog -sv $sources
set fd [open [file join $output context.xdc] w]
puts $fd {create_clock -name i1_cpu300 -period 3.333333333 [get_ports cpuClock]}
puts $fd {create_clock -name i1_vpu300 -period 3.333333333 [get_ports vpuClock]}
puts $fd {set_clock_uncertainty -setup 0.100 [get_clocks {i1_cpu300 i1_vpu300}]}
puts $fd {set_clock_uncertainty -hold 0.080 [get_clocks {i1_cpu300 i1_vpu300}]}
# Synthetic OOC pad context only. External clock/reset/board timing is not signed off.
puts $fd {set_input_delay -clock i1_cpu300 -max 0.333 [get_ports -filter {DIRECTION == IN && NAME != cpuClock && NAME != vpuClock}]}
puts $fd {set_input_delay -clock i1_cpu300 -min 0.000 [get_ports -filter {DIRECTION == IN && NAME != cpuClock && NAME != vpuClock}]}
puts $fd {set_output_delay -clock i1_cpu300 -max 0.333 [get_ports -filter {DIRECTION == OUT && NAME != io_vpuTransportIdle}]}
puts $fd {set_output_delay -clock i1_cpu300 -min 0.000 [get_ports -filter {DIRECTION == OUT && NAME != io_vpuTransportIdle}]}
puts $fd {set_output_delay -clock i1_vpu300 -max 0.333 [get_ports io_vpuTransportIdle]}
puts $fd {set_output_delay -clock i1_vpu300 -min 0.000 [get_ports io_vpuTransportIdle]}
close $fd
read_xdc [file join $output context.xdc]
synth_design -top I1Spinor300Context -part xczu15eg-ffvb1156-2-i -mode out_of_context \
    -flatten_hierarchy rebuilt -directive Default
foreach {port site} {cpuClock BUFGCE_X0Y48 vpuClock BUFGCE_X0Y49} {
    if {[llength [get_sites -quiet $site]] != 1} {error "external clock source site missing: $site"}
    set_property HD.CLK_SRC $site [get_ports $port]
}
write_checkpoint [file join $output synthesized.dcp]
report_utilization -hierarchical -file [file join $output utilization_synth.rpt]
report_clocks -file [file join $output clocks.rpt]
set fd [open [file join $output cdc_registers.tsv] w]
puts $fd "name\tref\tclock\tasync_reg"
set selected [get_cells -quiet -hierarchical -filter {IS_PRIMITIVE == TRUE && REF_NAME =~ FD* && (NAME =~ dut/boundary/* || NAME =~ dut/error/* || NAME =~ dut/cpuRelease/* || NAME =~ dut/vpuRelease/*)}]
foreach cell [lsort $selected] {
    set pin [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME == C}]
    set clocks [get_clocks -quiet -of_objects $pin]
    puts $fd "[get_property NAME $cell]\t[get_property REF_NAME $cell]\t$clocks\t[get_property ASYNC_REG $cell]"
}
close $fd
puts "I1_SPINOR300_SYNTH_DONE NO_IMPL_NO_BIT"
close_design
close_project
