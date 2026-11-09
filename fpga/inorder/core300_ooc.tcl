# Full cached CPU plus complete registered port context, one frozen role per call.
if {$argc != 2} {error "usage: core300_ooc.tcl FROZEN_CORE_RTL FRESH_OUTPUT"}
lassign $argv rtl output
set allowed [string tolower [file normalize E:/VM/Share/Valence-rtl/Valence-InOrder]]
foreach path [list $rtl $output] {
    if {![string match "${allowed}/*" [string tolower [file normalize $path]]]} {error "outside designated root"}
}
if {[file exists $output]} {error "fresh evidence required"}
set sources [lsort [glob -nocomplain -directory $rtl *.sv]]
if {![llength $sources]} {error "missing frozen core RTL"}
file mkdir $output
set_param general.maxThreads 8
puts "VIVADO_THREADS [get_param general.maxThreads]"
create_project -in_memory -part xczu15eg-ffvb1156-2-i
read_verilog -sv $sources
set fd [open [file join $output context.xdc] w]
puts $fd {create_clock -name i1_cpu300 -period 3.333333333 [get_ports clock]}
puts $fd {set_clock_uncertainty -setup 0.100 [get_clocks i1_cpu300]}
puts $fd {set_clock_uncertainty -hold 0.080 [get_clocks i1_cpu300]}
puts $fd {set_input_delay -clock i1_cpu300 -max 0.333 [get_ports -filter {DIRECTION == IN && NAME != clock}]}
puts $fd {set_input_delay -clock i1_cpu300 -min 0.000 [get_ports -filter {DIRECTION == IN && NAME != clock}]}
puts $fd {set_output_delay -clock i1_cpu300 -max 0.333 [get_ports -filter {DIRECTION == OUT}]}
puts $fd {set_output_delay -clock i1_cpu300 -min 0.000 [get_ports -filter {DIRECTION == OUT}]}
close $fd
read_xdc [file join $output context.xdc]
synth_design -top I1Core300Context -part xczu15eg-ffvb1156-2-i -mode out_of_context \
    -flatten_hierarchy rebuilt -directive Default
write_checkpoint [file join $output synthesized.dcp]
# Path groups partition actual synchronous endpoints; every group retains the same 300 MHz clock.
# No false paths, multicycle exceptions, virtual phases, or manufactured I/O latency offsets.
foreach {name root} {predictor cpu/core/predictor mdu cpu/core/mulDiv icache cpu/icache dcache cpu/dcache} {
    set ends [get_cells -quiet -hierarchical -filter "NAME =~ ${root}/* && (REF_NAME =~ FD* || REF_NAME =~ RAM* || REF_NAME =~ DSP*)"]
    if {![llength $ends]} {error "missing actual module partition $root"}
    group_path -name i1_$name -to $ends
}
set sites [lsort -dictionary [get_sites -quiet BUFGCE_X0Y*]]
set source [lindex $sites [expr {[llength $sites]/2}]]
set_property HD.CLK_SRC $source [get_ports clock]
write_checkpoint [file join $output constrained.dcp]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $output timing_synth.rpt]
set states [lsort -unique [concat [all_registers -clock i1_cpu300] \
    [get_cells -hierarchical -filter {REF_NAME =~ RAM* || REF_NAME =~ DSP*}]]]
report_timing -from $states -to $states -delay_type max -max_paths 30 -nworst 1 \
    -file [file join $output synchronous_synth.rpt]
report_utilization -hierarchical -file [file join $output utilization_synth.rpt]
opt_design -directive Explore
place_design -directive Explore
write_checkpoint [file join $output placed.dcp]
phys_opt_design -directive AggressiveExplore
route_design -directive Explore
write_checkpoint [file join $output routed.dcp]
set states [lsort -unique [concat [all_registers -clock i1_cpu300] \
    [get_cells -hierarchical -filter {REF_NAME =~ RAM* || REF_NAME =~ DSP*}]]]
report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose \
    -file [file join $output timing_routed.rpt]
report_timing -from $states -to $states -delay_type max -max_paths 50 -nworst 1 \
    -file [file join $output synchronous_setup.rpt]
report_timing -from $states -to $states -delay_type min -max_paths 30 -nworst 1 \
    -file [file join $output synchronous_hold.rpt]
foreach group {predictor mdu icache dcache} {
    report_timing -group i1_$group -delay_type max -max_paths 15 -nworst 1 \
        -file [file join $output ${group}_setup.rpt]
}
report_utilization -file [file join $output utilization_routed.rpt]
report_utilization -hierarchical -file [file join $output utilization_hierarchical.rpt]
report_route_status -file [file join $output route_status.rpt]
report_exceptions -file [file join $output exceptions.rpt]
check_timing -verbose -file [file join $output check_timing.rpt]
set setup [get_timing_paths -from $states -to $states -delay_type max -max_paths 1]
set hold [get_timing_paths -from $states -to $states -delay_type min -max_paths 1]
if {![llength $setup] || ![llength $hold]} {error "missing complete synchronous paths"}
set fd [open [file join $output result.json] w]
puts $fd [format {{"scope":"FULL_CACHED_CPU_WITH_ALL_PORT_CAPTURE_REGISTERS","target_hz":300000000,"setup_slack_ns":%s,"hold_slack_ns":%s,"external_clock_site":"%s","top_level_pad_timing_qualified":false,"board_qualified":false}} \
    [get_property SLACK [lindex $setup 0]] [get_property SLACK [lindex $hold 0]] $source]
close $fd
puts "I1_FULL_CORE300_IMPLEMENTATION_DONE NO_BIT"
close_design
close_project
