# One matched implementation per reference/local/hashed predictor, with identical capture registers.
if {$argc ni {3 4}} { error "usage: prediction_ooc.tcl PAIRED_RTL_ROOT FRESH_REPORT_ROOT PERIOD_NS ?REFERENCE_ROUTED_DCP?" }
lassign $argv rtl output period referenceCheckpoint
set allowed [string tolower [file normalize E:/VM/Share/Valence-rtl/Valence-InOrder]]
set rtl [file normalize $rtl]
set output [file normalize $output]
foreach path [concat [list $rtl $output] [expr {$argc == 4 ? [list [file normalize $referenceCheckpoint]] : {}}]] {
    if {![string match "${allowed}/*" [string tolower $path]]} { error "path outside designated work root" }
}
if {[file exists $output]} { error "fresh evidence directory required" }
if {![string is double -strict $period] || $period <= 0.333} { error "explicit clock period required" }
proc valence_i1_prediction_partitions {} {
    # Physical optimization may replace/replicate cells. Never hold pre-route
    # object handles for report queries against the optimized design.
    set starts [all_fanin -flat -startpoints_only -to [get_ports -filter {DIRECTION == OUT}]]
    set captures [lsort -unique [get_cells -quiet -of_objects $starts -filter {REF_NAME =~ FD*}]]
    set storage [get_cells -hierarchical -filter {NAME =~ predictor/* && (REF_NAME =~ FD* || REF_NAME =~ RAM*)}]
    if {![llength $captures] || ![llength $storage]} { error "missing lookup/storage partition" }
    return [list $captures $storage]
}
file mkdir $output
set_param general.maxThreads 8
foreach role {reference local hashed} {
    set folder [file join $output $role]
    file mkdir $folder
    set sources [lsort [glob -nocomplain -directory [file join $rtl $role] *.sv]]
    if {![llength $sources]} { error "missing frozen RTL for $role" }
    if {$role eq "reference" && $argc == 4} {
        # Read-only reuse of the completed route after an earlier report error.
        open_checkpoint [file normalize $referenceCheckpoint]
        set clk [get_clocks -quiet i1_prediction_clock]
        if {[llength $clk] != 1 || [get_property PERIOD $clk] != $period} {
            error "reference checkpoint clock differs"
        }
        set source [get_property HD.CLK_SRC [get_ports clock]]
        write_checkpoint [file join $folder routed.dcp]
    } else {
        create_project -in_memory -part xczu15eg-ffvb1156-2-i
        read_verilog -sv $sources
        set context [open [file join $folder context.xdc] w]
        puts $context [format {create_clock -name i1_prediction_clock -period %s [get_ports clock]} $period]
        puts $context {set_clock_uncertainty -setup 0.100 [get_clocks i1_prediction_clock]}
        puts $context {set_input_delay -clock i1_prediction_clock -max 0.333 [get_ports -filter {DIRECTION == IN && NAME != clock}]}
        puts $context {set_input_delay -clock i1_prediction_clock -min 0.000 [get_ports -filter {DIRECTION == IN && NAME != clock}]}
        puts $context {set_output_delay -clock i1_prediction_clock -max 0.333 [get_ports -filter {DIRECTION == OUT}]}
        puts $context {set_output_delay -clock i1_prediction_clock -min 0.000 [get_ports -filter {DIRECTION == OUT}]}
        close $context
        read_xdc [file join $folder context.xdc]
        synth_design -top I1PredictionTimingTop -part xczu15eg-ffvb1156-2-i -mode out_of_context \
            -flatten_hierarchy rebuilt -directive Default
        write_checkpoint [file join $folder synthesized.dcp]
        set clk [get_clocks i1_prediction_clock]
        # A stricter synchronous module budget on the SAME clock, including LUTRAM feedback.
        # No datapath-only relaxation, false path, multicycle path or generated clock.
        set_max_delay [expr {$period - 0.333}] -from $clk -to $clk
        lassign [valence_i1_prediction_partitions] captures storage
        group_path -name i1_prediction_lookup -to $captures
        group_path -name i1_prediction_training -to $storage
        set ledger [open [file join $folder partition_coverage.csv] w]
        puts $ledger "group,endpoint_cells,max_delay_ns"
        puts $ledger "lookup,[llength $captures],[expr {$period - 0.333}]"
        puts $ledger "training,[llength $storage],[expr {$period - 0.333}]"
        close $ledger
        set sites [lsort -dictionary [get_sites -quiet BUFGCE_X0Y*]]
        if {![llength $sites]} { error "missing external clock context" }
        set source [lindex $sites [expr {[llength $sites] / 2}]]
        set_property HD.CLK_SRC $source [get_ports clock]
        write_checkpoint [file join $folder constrained.dcp]
        opt_design
        place_design -directive Default
        phys_opt_design -directive Default
        route_design -directive Default
        write_checkpoint [file join $folder routed.dcp]
    }
    # Re-query after route (also for DCP reuse); no stale synthesis handles.
    set clk [get_clocks i1_prediction_clock]
    lassign [valence_i1_prediction_partitions] captures storage
    set ledger [open [file join $folder partition_coverage_routed.csv] w]
    puts $ledger "group,endpoint_cells,max_delay_ns"
    puts $ledger "lookup,[llength $captures],[expr {$period - 0.333}]"
    puts $ledger "training,[llength $storage],[expr {$period - 0.333}]"
    close $ledger
    report_exceptions -file [file join $folder exceptions.rpt]
    report_utilization -file [file join $folder utilization_routed.rpt]
    report_utilization -hierarchical -file [file join $folder utilization_hierarchical.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose \
        -file [file join $folder timing_routed.rpt]
    foreach group {lookup training} endpoints [list $captures $storage] {
        report_timing -to $endpoints -delay_type max -max_paths 10 -nworst 1 \
            -file [file join $folder ${group}_setup.rpt]
        report_timing -to $endpoints -delay_type min -max_paths 10 -nworst 1 \
            -file [file join $folder ${group}_hold.rpt]
    }
    report_route_status -file [file join $folder route_status.rpt]
    report_drc -file [file join $folder drc.rpt]
    check_timing -verbose -file [file join $folder check_timing.rpt]
    # Clock-domain queries also include delay-associated I/O. Restrict this
    # metric to actual sequential boundaries, including distributed RAM cells.
    set sequential [lsort -unique [concat [all_registers -clock i1_prediction_clock] \
        [get_cells -hierarchical -filter {REF_NAME =~ RAM*}]]]
    report_timing -from $sequential -to $sequential -delay_type max -max_paths 10 \
        -file [file join $folder internal_setup.rpt]
    report_timing -from $sequential -to $sequential -delay_type min -max_paths 10 \
        -file [file join $folder internal_hold.rpt]
    set setup [get_timing_paths -from $sequential -to $sequential -delay_type max -max_paths 1]
    set hold [get_timing_paths -from $sequential -to $sequential -delay_type min -max_paths 1]
    if {![llength $setup] || ![llength $hold]} { error "missing synchronous internal paths" }
    set result [open [file join $folder result.json] w]
    puts $result [format {{"scope":"PREDICTOR_WITH_MATCHED_CAPTURE_ONLY","role":"%s","period_ns":%s,"internal_setup_slack_ns":%s,"internal_hold_slack_ns":%s,"mapped_lut_cells":%s,"ff_cells":%s,"dsp_cells":%s,"cpu_or_board_qualified":false}} \
        $role $period [get_property SLACK [lindex $setup 0]] [get_property SLACK [lindex $hold 0]] \
        [llength [get_cells -hierarchical -filter {REF_NAME =~ LUT*}]] \
        [llength [get_cells -hierarchical -filter {REF_NAME =~ FD*}]] \
        [llength [get_cells -hierarchical -filter {REF_NAME == DSP48E2}]]]
    close $result
    puts "I1_PREDICTION_OOC_DONE role=$role external_BUFGCE=$source NO_CPU_OR_BOARD_CLAIM"
    close_design
    catch {close_project}
}
puts "I1_PREDICTION_OOC_BATCH_DONE NO_BIT"
