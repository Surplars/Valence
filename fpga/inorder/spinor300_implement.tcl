# Continue one frozen synthesis checkpoint through placement/routing exactly once.
if {$argc != 2} {error "usage: spinor300_implement.tcl FROZEN_SYNTH_DCP FRESH_OUTPUT"}
lassign $argv checkpoint output
set allowed [string tolower [file normalize E:/VM/Share/Valence-rtl/Valence-InOrder]]
foreach p [list $checkpoint $output] {
    if {![string match "${allowed}/*" [string tolower [file normalize $p]]]} {error "outside designated root"}
}
if {[file exists $output]} {error "fresh implementation evidence required"}
file mkdir $output
set_param general.maxThreads 8
puts "VIVADO_THREADS [get_param general.maxThreads]"
open_checkpoint $checkpoint
source [file join [file dirname [info script]] spinor_cdc.tcl]
spinor_cdc::apply $output
proc domain_states {clock root} {
    return [lsort -unique [concat [all_registers -clock $clock] \
        [get_cells -quiet -hierarchical -filter "NAME =~ $root/* && (REF_NAME =~ RAM* || REF_NAME =~ DSP*)"]]]
}
set cpu [domain_states i1_cpu300 dut/cpu]
set vpu [domain_states i1_vpu300 dut/vector]
spinor_cdc::coverage $cpu $vpu $output
foreach {name root} {cpu dut/cpu spinor dut/vector boundary dut/boundary mdu dut/cpu/core/mulDiv \
    icache dut/cpu/icache dcache dut/cpu/dcache} {
    set cells [get_cells -quiet -hierarchical -filter "NAME =~ $root/* && (REF_NAME =~ FD* || REF_NAME =~ RAM* || REF_NAME =~ DSP*)"]
    if {![llength $cells]} {error "module timing partition missing: $root"}
    group_path -name i1_$name -to $cells
}
write_checkpoint [file join $output constrained.dcp]
write_xdc [file join $output constrained.xdc]
report_exceptions -file [file join $output exceptions_before.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $output timing_synth.rpt]
report_cdc -details -file [file join $output cdc_synth.rpt]
opt_design -directive Explore
place_design -directive Explore
write_checkpoint [file join $output placed.dcp]
phys_opt_design -directive AggressiveExplore
# Refresh identical bounds on actual mapped/replicated sequential endpoints.
spinor_cdc::apply $output
route_design -directive Explore
write_checkpoint [file join $output routed.dcp]
set cpu [domain_states i1_cpu300 dut/cpu]
set vpu [domain_states i1_vpu300 dut/vector]
spinor_cdc::coverage $cpu $vpu $output
report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose \
    -file [file join $output timing_routed.rpt]
foreach {name states} [list cpu $cpu vpu $vpu] {
    report_timing -from $states -to $states -delay_type max -max_paths 50 -nworst 1 \
        -file [file join $output ${name}_setup.rpt]
    report_timing -from $states -to $states -delay_type min -max_paths 30 -nworst 1 \
        -file [file join $output ${name}_hold.rpt]
}
report_timing -from $cpu -to $vpu -delay_type max -max_paths 30 -nworst 1 \
    -file [file join $output cpu_to_vpu_setup.rpt]
report_timing -from $vpu -to $cpu -delay_type max -max_paths 30 -nworst 1 \
    -file [file join $output vpu_to_cpu_setup.rpt]
# Overlapping synthesis-time path groups can become empty after optimization.
# Report real routed module endpoints, without changing timing constraints.
foreach {group root} {cpu dut/cpu spinor dut/vector boundary dut/boundary mdu dut/cpu/core/mulDiv \
    icache dut/cpu/icache dcache dut/cpu/dcache} {
    set cells [get_cells -quiet -hierarchical -filter "NAME =~ $root/* && (REF_NAME =~ FD* || REF_NAME =~ RAM* || REF_NAME =~ DSP*)"]
    if {![llength $cells]} {error "routed module endpoints missing: $root"}
    report_timing -to $cells -delay_type max -max_paths 10 -nworst 1 \
        -file [file join $output ${group}_module_setup.rpt]
}
report_bus_skew -warn_on_violation -file [file join $output bus_skew.rpt]
report_cdc -details -file [file join $output cdc_routed.rpt]
report_clock_interaction -file [file join $output clock_interaction.rpt]
report_utilization -file [file join $output utilization_routed.rpt]
report_utilization -hierarchical -file [file join $output utilization_hierarchical.rpt]
report_route_status -file [file join $output route_status.rpt]
report_exceptions -file [file join $output exceptions.rpt]
report_exceptions -ignored -file [file join $output exceptions_ignored.rpt]
check_timing -verbose -file [file join $output check_timing.rpt]
write_xdc [file join $output routed.xdc]
set fd [open [file join $output internal_result.tsv] w]
puts $fd "domain\tsetup_ns\thold_ns"
foreach {name states} [list cpu $cpu vpu $vpu] {
    set max [get_timing_paths -from $states -to $states -delay_type max -max_paths 1]
    set min [get_timing_paths -from $states -to $states -delay_type min -max_paths 1]
    if {![llength $max] || ![llength $min]} {error "domain timing paths missing: $name"}
    puts $fd "$name\t[get_property SLACK $max]\t[get_property SLACK $min]"
}
close $fd
puts "I1_SPINOR300_ROUTED_DONE NO_BIT NO_BOARD_SIGNOFF"
close_design
