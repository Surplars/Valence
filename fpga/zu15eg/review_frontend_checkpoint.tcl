# Compare two already-routed CPU checkpoints; no synth/place/route or constraint edits.
if {$argc != 3} {
    error "usage: review_frontend_checkpoint.tcl BASELINE_DCP CANDIDATE_DCP FRESH_OUTPUT"
}
set output [file normalize [lindex $argv 2]]
if {[file exists $output]} { error "Preserve previous report-only evidence" }
file mkdir $output
set inputs [list [file normalize [lindex $argv 0]] [file normalize [lindex $argv 1]]]
set labels {baseline candidate}
foreach checkpoint $inputs label $labels {
    open_checkpoint $checkpoint
    set clocks [get_clocks]
    if {[llength $clocks] != 1 || [get_property PERIOD $clocks] != 10.0} {
        error "Expected the unchanged single-clock 10 ns CPU constraint"
    }
    set reportDir [file join $output $label]
    file mkdir $reportDir
    set metrics [open [file join $reportDir path_metrics.tsv] w]
    puts $metrics "family\tslack_ns\tdata_delay_ns\tlogic_levels\tstartpoint\tendpoint"
    foreach family {pc_to_packet_ce head_to_memory_address} {
        if {$family eq "pc_to_packet_ce"} {
            set sources [get_cells -quiet -hierarchical -filter {NAME =~ core/pc_reg*}]
            set sinks [get_cells -quiet -hierarchical -filter {NAME =~ core/fetchPacket/supplyPc_reg*}]
            set sinkPin CE
        } else {
            set sources [get_cells -quiet -hierarchical -filter {NAME =~ core/backend/head_reg*}]
            set sinks [get_cells -quiet -hierarchical -filter {NAME =~ core/backend/stagedMemoryAddress_reg*}]
            set sinkPin D
        }
        set starts [get_pins -of_objects $sources -filter {REF_PIN_NAME == C}]
        set ends [get_pins -of_objects $sinks -filter "REF_PIN_NAME == $sinkPin"]
        if {![llength $starts] || ![llength $ends]} { error "Missing $family register pins" }
        set paths [get_timing_paths -delay_type max -from $starts -to $ends -max_paths 1]
        if {[llength $paths] != 1} { error "Missing $family timing path" }
        set path [lindex $paths 0]
        puts $metrics [join [list $family [get_property SLACK $path] \
            [get_property DATAPATH_DELAY $path] [get_property LOGIC_LEVELS $path] \
            [get_property STARTPOINT_PIN $path] [get_property ENDPOINT_PIN $path]] "\t"]
        report_timing -delay_type max -from $starts -to $ends -max_paths 5 \
            -file [file join $reportDir ${family}.rpt]
    }
    close $metrics
    close_project
}
puts "FRONTEND_CHECKPOINT_REVIEW_COMPLETE"
