# Same synthesized, constrained checkpoint: partition timing reports, never another synthesis.
if {$argc != 2} { error "usage: report_fd_paths.tcl CONSTRAINED_DCP REPORT_ROOT" }
set checkpoint [file normalize [lindex $argv 0]]
set output [file normalize [lindex $argv 1]]
if {![file isdirectory $output]} { error "completed report directory required" }
set_param general.maxThreads 8
open_checkpoint $checkpoint
foreach {name pattern} {
    csr soc/core/core/csr/*
    instruction_translation soc/core/it/*
    data_translation soc/core/dt/*
    dcache soc/core/dcache/*
} {
    set path [file join $output "setup_${name}_synth.rpt"]
    if {[file exists $path]} { error "preserve previous partition report" }
    set endpoints [get_cells -quiet -hierarchical -filter "IS_SEQUENTIAL == 1 && NAME =~ $pattern"]
    if {[llength $endpoints] == 0} { error "missing timing partition $name" }
    report_timing -from [get_clocks orbital_i1_cpu] -to $endpoints -delay_type max \
        -max_paths 10 -nworst 1 -file $path
}
set endpoint_path [file join $output setup_non_fp_endpoint_synth.rpt]
if {[file exists $endpoint_path]} { error "preserve previous non-FP endpoint report" }
set endpoints [get_cells -quiet -hierarchical -filter {
    IS_SEQUENTIAL == 1 && NAME =~ soc/* &&
    NAME !~ soc/core/core/execute/* && NAME !~ soc/core/core/fpr/*
}]
# This does NOT emulate an F/D-disabled synthesis: FP-origin paths can still
# reach these endpoints, and all current decoding/CSR/state remains present.
report_timing -from [get_clocks orbital_i1_cpu] -to $endpoints -delay_type max \
    -max_paths 30 -nworst 1 -file $endpoint_path
foreach name {hold_synth.rpt bscan_bus_skew_synth.rpt} {
    if {[file exists [file join $output $name]]} { error "preserve previous supplementary report" }
}
report_timing -delay_type min -max_paths 30 -nworst 1 -file [file join $output hold_synth.rpt]
report_bus_skew -file [file join $output bscan_bus_skew_synth.rpt]
puts "I1_FD_PARTITION_REPORTS_DONE NO_SYNTHESIS NO_CONSTRAINT_CHANGES"
close_design
