# One native batch for original GMII TX/RX/adapter only. No board/CPU/IP license.
# usage: vivado -mode batch -source ... -tclargs FROZEN_RTL FRESH_REPORT_ROOT
if {$argc < 2 || $argc > 3} { error "usage: vivado-self-gmac-frames.tcl FROZEN_RTL FRESH_REPORT_ROOT ?TX_REUSE_BATCH?" }
set rtl_root [file normalize [lindex $argv 0]]
set report_root [file normalize [lindex $argv 1]]
set reuse_tx [expr {$argc == 3 ? [file normalize [lindex $argv 2]] : ""}]
cd [file dirname [info script]]
set part xczu15eg-ffvb1156-2-i
if {[file exists $report_root]} { error "Preserve previous GMAC module evidence" }
file mkdir $report_root
set_param general.maxThreads 8
proc required_slack {paths label} {
    if {[llength $paths] != 1} { error "Expected a timing path for $label" }
    return [get_property SLACK [lindex $paths 0]]
}
foreach config {{tx GmiiFrameTx 8.0} {rx GmiiFrameRx 8.0} {adapter EthernetDmaFrameAdapter 10.0}} {
    lassign $config directory top period
    set source_files [glob [file join $rtl_root $directory *.sv]]
    if {[llength $source_files] == 0} { error "Missing frozen SV for $top" }
    set output [file join $report_root $top]
    file mkdir $output
    if {$directory eq "tx" && $reuse_tx ne ""} {
        set old_sources [glob [file join $reuse_tx rtl tx *.sv]]
        if {[llength $old_sources] != [llength $source_files]} { error "TX reuse dependency set changed" }
        foreach current $source_files {
            set previous [file join $reuse_tx rtl tx [file tail $current]]
            set a [open $current rb]
            set b [open $previous rb]
            set identical [expr {[read $a] eq [read $b]}]
            close $a
            close $b
            if {!$identical} { error "TX reuse RTL dependency changed: $current" }
        }
        set old_report [file join $reuse_tx reports $top]
        if {![file exists [file join $old_report result.json]] ||
            ![file exists [file join $old_report post_route.dcp]]} { error "Missing completed TX route" }
        foreach previous [glob [file join $old_report *]] {
            file copy $previous [file join $output [file tail $previous]]
        }
        set reuse_note [open [file join $output reused_from.txt] w]
        puts $reuse_note $old_report
        close $reuse_note
        puts "SELF_GMAC_TX_REUSED byte-identical RTL, no synthesis/place/route"
        continue
    }
    create_project -in_memory -part $part
    read_verilog -sv $source_files
    synth_design -top $top -part $part -mode out_of_context -flatten_hierarchy none
    if {[llength [get_cells -hier -quiet -filter {IS_BLACKBOX == 1}]] != 0} {
        error "Unresolved functional blackbox in original $top"
    }
    create_clock -name module_clock -period $period [get_ports clock]
    # All module signals, including synchronous reset, are local to this clock.
    # Zero boundary budgets are comparison-only, not PHY/CDC/I/O signoff.
    set inputs [get_ports -filter {DIRECTION == IN && NAME != clock}]
    set outputs [get_ports -filter {DIRECTION == OUT}]
    set_input_delay -clock module_clock 0 $inputs
    set_output_delay -clock module_clock 0 $outputs
    report_utilization -file [file join $output post_synth_utilization.rpt]
    write_checkpoint [file join $output post_synth.dcp]
    opt_design
    place_design
    route_design
    set start [all_registers -output_pins]
    set finish [all_registers -data_pins]
    set setup [get_timing_paths -delay_type max -from $start -to $finish -max_paths 1 -nworst 1]
    set hold [get_timing_paths -delay_type min -from $start -to $finish -max_paths 1 -nworst 1]
    set internal_wns [required_slack $setup "$top internal setup"]
    set internal_whs [required_slack $hold "$top internal hold"]
    set all_wns [required_slack [get_timing_paths -delay_type max -max_paths 1 -nworst 1] "$top all setup"]
    set all_whs [required_slack [get_timing_paths -delay_type min -max_paths 1 -nworst 1] "$top all hold"]
    report_timing_summary -report_unconstrained -file [file join $output post_route_timing.rpt]
    report_timing -delay_type max -from $start -to $finish -max_paths 10 -file [file join $output internal_setup.rpt]
    report_timing -delay_type min -from $start -to $finish -max_paths 10 -file [file join $output internal_hold.rpt]
    report_timing -delay_type max -max_paths 10 -file [file join $output all_setup.rpt]
    report_timing -delay_type min -max_paths 10 -file [file join $output all_hold.rpt]
    report_utilization -file [file join $output post_route_utilization.rpt]
    report_drc -file [file join $output post_route_drc.rpt]
    write_checkpoint [file join $output post_route.dcp]
    set result [open [file join $output result.json] w]
    set passed [expr {$internal_wns >= 0 && $internal_whs >= 0}]
    puts $result "\{"
    puts $result "  \"top\": \"$top\", \"part\": \"$part\", \"period_ns\": $period,"
    puts $result "  \"internal_setup_wns_ns\": $internal_wns, \"internal_hold_whs_ns\": $internal_whs,"
    puts $result "  \"all_setup_wns_ns\": $all_wns, \"all_hold_whs_ns\": $all_whs,"
    puts $result "  \"internal_timing_pass\": [expr {$passed ? {true} : {false}}],"
    puts $result "  \"zero_boundary_budget_only\": true, \"phy_cdc_or_board_signoff\": false"
    puts $result "\}"
    close $result
    puts "SELF_GMAC_MODULE_RESULT top=$top setup=$internal_wns hold=$internal_whs period=$period"
    close_project
}
puts "SELF_GMAC_MODULE_BATCH_COMPLETE"
