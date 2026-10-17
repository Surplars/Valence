# One fresh small bare-core synthesis batch. Never opens a board project or emits a bit.
if {$argc != 2} { error "usage: synth_ooc.tcl RTL_ROOT FRESH_REPORT_ROOT" }
set rtl_root [file normalize [lindex $argv 0]]
set report_root [file normalize [lindex $argv 1]]
if {[file exists $report_root]} { error "refusing to overwrite existing OOC evidence: $report_root" }
file mkdir $report_root
set_param general.maxThreads 4
foreach profile {rv64-dsp rv64-no-m rv64-lutram} {
    set input [file join $rtl_root $profile]
    set files [lsort [glob -nocomplain -directory $input *.sv]]
    if {[llength $files] == 0} { error "missing frozen RTL for $profile" }
    set out [file join $report_root $profile]
    file mkdir $out
    create_project -in_memory -part xczu15eg-ffvb1156-2-i
    read_verilog -sv $files
    read_xdc [file join $rtl_root ooc.xdc]
    synth_design -top FiveStageCore -part xczu15eg-ffvb1156-2-i -mode out_of_context \
        -flatten_hierarchy rebuilt -directive Default
    write_checkpoint [file join $out synthesized.dcp]
    report_utilization -file [file join $out utilization.rpt]
    report_utilization -hierarchical -file [file join $out hierarchical_utilization.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing_synth.rpt]
    report_timing -delay_type max -max_paths 20 -nworst 2 -file [file join $out setup_synth.rpt]
    set bram36 [get_cells -hierarchical -filter {REF_NAME == RAMB36E2}]
    set bram18 [get_cells -hierarchical -filter {REF_NAME == RAMB18E2}]
    set dsps [get_cells -hierarchical -filter {REF_NAME == DSP48E2}]
    set ramfile [open [file join $out ram_dsp_mapping.txt] w]
    puts $ramfile "profile=$profile"
    puts $ramfile "scope=BARE_CORE_SYNTHESIS_ONLY_NOT_ROUTED_NOT_SOC"
    puts $ramfile "RAMB36E2=[llength $bram36] RAMB18E2=[llength $bram18] DSP48E2=[llength $dsps]"
    foreach cell [concat $bram36 $bram18 $dsps] { puts $ramfile "$cell [get_property REF_NAME $cell]" }
    close $ramfile
    if {$profile != "rv64-lutram" && [llength $bram36] + [llength $bram18] < 2} {
        error "two replicated RF banks did not map to block RAM: $profile"
    }
    if {$profile == "rv64-no-m" && [llength $dsps] != 0} { error "disabled M left DSP resources" }
    if {$profile == "rv64-dsp" && [llength $dsps] == 0} { error "DSP multiplier was not inferred" }
    puts "ORBITAL_I1_OOC_SYNTH_PASS profile=$profile bram36=[llength $bram36] bram18=[llength $bram18] dsp=[llength $dsps]"
    close_project
}
puts "ORBITAL_I1_OOC_BATCH_PASS_SYNTHESIS_ONLY_NO_BIT"
