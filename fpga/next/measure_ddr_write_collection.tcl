# Paired DDR bridge OOC implementation only. Not CPU/SoC/MIG/CDC signoff.
# Usage: vivado -mode batch -source this-file -tclargs RTL_DIR FRESH_REPORT_DIR
# RTL_DIR contains off.sv/on.sv from the exact paired shared-bridge FIRs.
if {$argc != 2} { error "usage: RTL_DIR FRESH_REPORT_DIR" }
set rtlRoot [file normalize [lindex $argv 0]]
set reportRoot [file normalize [lindex $argv 1]]
if {[file exists $reportRoot]} { error "refusing existing OOC report directory" }
file mkdir $reportRoot
set_param general.maxThreads 8
foreach side {off on} {
    set rtl [file join $rtlRoot "$side.sv"]
    if {![file isfile $rtl]} { error "missing source-bound RTL: $rtl" }
    set out [file join $reportRoot $side]
    file mkdir $out
    create_project -in_memory -part xczu15eg-ffvb1156-2-i
    read_verilog -sv $rtl
    synth_design -top TileLinkAxi4Bridge -mode out_of_context -flatten_hierarchy rebuilt
    write_checkpoint [file join $out synthesized.dcp]
    create_clock -name bridge_clk -period 10.000 [get_ports clock]
    # Identical assumed synchronous boundaries on both sides. Real integration
    # must re-establish its own timing paths; these are not false-path shortcuts.
    set dataInputs [get_ports -filter {DIRECTION == IN && NAME != clock && NAME != reset}]
    set_input_delay -clock bridge_clk -max 2.000 $dataInputs
    set_input_delay -clock bridge_clk -min 0.250 $dataInputs
    set_output_delay -clock bridge_clk -max 2.000 [all_outputs]
    set_output_delay -clock bridge_clk -min 0.250 [all_outputs]
    # Reset is excluded as an externally managed reset assumption for this OOC
    # experiment, not qualification of the SoC's actual reset timing/CDC.
    set_false_path -from [get_ports reset]
    report_utilization -file [file join $out synthesis_utilization.rpt]
    opt_design
    place_design
    phys_opt_design -directive Explore
    route_design -directive Explore
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing_summary.rpt]
    report_timing -delay_type max -max_paths 12 -input_pins -file [file join $out setup_paths.rpt]
    report_timing -delay_type min -max_paths 12 -input_pins -file [file join $out hold_paths.rpt]
    report_utilization -file [file join $out routed_utilization.rpt]
    report_drc -file [file join $out drc.rpt]
    write_checkpoint [file join $out routed.dcp]
    close_project
}
