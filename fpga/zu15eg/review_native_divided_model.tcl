# Compare equivalent descriptions of the SAME proved DIV4 0ns/+2ns phases.
# Read-only: every case retains full physical propagation and +/-1.25ns IO.
if {$argc!=2} {error "Expected ROUTED_DCP FRESH_OUT"}
lassign $argv baseline out
if {[file exists $out]} {error "Preserve evidence"}
file mkdir $out
cd $out
file copy [info script] executed_model_review.tcl
set_param general.maxThreads 8
open_checkpoint $baseline
set ref [get_clocks -of_objects [get_pins native_tx_ref_pll/CLKOUT0]]
foreach {label source mode} {
    buffer_folded u_eth_clk_wiz/inst/clkout2_buf/O folded
    pll_folded native_tx_ref_pll/CLKOUT0 folded
    pll_divide native_tx_ref_pll/CLKOUT0 divide
} {
    file mkdir $label
    foreach {c name edges shifts} {
        u_eth_clk_wiz/inst/clkout1_buf valence_tx_raw_div {1 5 9} {0 0 0}
        native_tx90_forward_buffer valence_tx_forward_div {3 7 11} {2 2 2}
    } {
        if {$mode eq "folded" || $mode eq "divide"} {
            set offset [lindex $shifts 0]
            if {$mode eq "divide" && $offset==0} {
                create_generated_clock -name $name -source [get_pins $source] -divide_by 4 [get_pins $c/O]
            } else {
                # Same 8ns waveform, with matching rise/fall master traversal.
                create_generated_clock -name $name -source [get_pins $source] -edges {1 2 3} -edge_shift [list $offset [expr {$offset+3}] [expr {$offset+6}]] [get_pins $c/O]
            }
        } elseif {$mode eq "shift"} {
            create_generated_clock -name $name -source [get_pins $source] -edges {1 5 9} -edge_shift $shifts [get_pins $c/O]
        } else {
            create_generated_clock -name $name -source [get_pins $source] -edges $edges [get_pins $c/O]
        }
    }
    create_generated_clock -name phy_tx_capture -source [get_pins u_rgmii/tx_clock_ddr/CLK] -divide_by 1 [get_ports eth_txc]
    foreach extra {{} {-clock_fall -add_delay}} {
        set_output_delay -clock phy_tx_capture -max 1.250 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
        set_output_delay -clock phy_tx_capture -min -1.250 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
    }
    report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file $label/tx_io.rpt
    report_clocks -file $label/clocks.rpt
    check_timing -verbose -file $label/check_timing.rpt
}
puts "DIV4_MODEL_DEFINITION_REVIEW_COMPLETE NO_PHYSICAL_CHANGE_NO_BIT"
close_design
