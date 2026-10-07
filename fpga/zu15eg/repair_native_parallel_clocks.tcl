# Board-only ECO from routed checkpoint; preserve CPU and all data placements.
# No bit generation. Actual PHY contract remains 2ns nominal / +/-1.75ns.
if {$argc != 2} {error "Expected ROUTED_PARENT_DCP FRESH_OUTPUT_DIR"}
lassign $argv dcp out
set here [file dirname [info script]]
if {[file exists $out]} {error "Preserve existing evidence"}
file mkdir $out
cd $out
set_param general.maxThreads 8
open_checkpoint $dcp
set gates {u_soc/nativeBank/gmac/txManaged_gate/buffer u_soc/nativeBank/gmac/rxManaged_gate/buffer}
set frozen [dict create]
foreach cell [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}] {
    if {$cell ni $gates} {dict set frozen $cell [list [get_property LOC $cell] [get_property BEL $cell]]}
}
# ODDR_MODE uses CLK here; CLKDIV is unused and has no propagated master.
# A generated clock on CLKDIV silently removes TX from STA. Fail closed.
set source [get_pins -quiet u_rgmii/tx_clock_ddr/CLK]
set masters [get_clocks -quiet -of_objects $source]
if {[llength $source]!=1 || [llength $masters]!=1 || abs([get_property PERIOD $masters]-8.0)>0.001} {
    error "Forwarded clock requires one valid 125MHz master on actual CLK"
}
create_generated_clock -name phy_tx_capture -source $source -edges {1 2 3} -edge_shift {2.0 2.0 2.0} [get_ports eth_txc]
foreach edge {rise fall} {
    set args {}
    if {$edge eq "fall"} {set args {-clock_fall -add_delay}}
    set_output_delay -clock phy_tx_capture {*}$args -max 1.750 [get_ports {eth_txd[*] eth_tx_ctl}]
    set_output_delay -clock phy_tx_capture {*}$args -min -1.750 [get_ports {eth_txd[*] eth_tx_ctl}]
}
set clocks {}
foreach pin {rx_clock_buffer/O u_eth_clk_wiz/inst/clkout1_buf/O u_soc/nativeBank/gmac/txManaged_gate/buffer/O u_soc/nativeBank/gmac/rxManaged_gate/buffer/O rx_clock_buffer/I u_eth_clk_wiz/inst/clkout1_buf/I} {
    set net [get_nets -of_objects [get_pins $pin]]
    if {[llength $net]!=1} {error "Missing clock segment: $pin"}
    lappend clocks $net
}
route_design -unroute -nets $clocks
source [file join $here native_parallel_clocks.tcl]
valence_native_parallel_clocks
set region [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AA7]]]
if {[llength $region]!=1} {error "Missing physical clock region"}
# Move only the two peripheral BUFGCE cells if they are outside Bank66.
foreach gate $gates {
    set currentRegion [get_clock_regions -of_objects [get_sites [get_property LOC [get_cells $gate]]]]
    if {$currentRegion ne $region} {
        set target ""
        foreach site [get_sites -of_objects $region -filter {SITE_TYPE == BUFGCE}] {
            if {[llength [get_cells -quiet -of_objects $site]]==0} {set target $site; break}
        }
        if {$target eq ""} {error "No free peripheral clock buffer"}
        puts "PERIPHERAL_BUFG_MOVE $gate [get_property LOC [get_cells $gate]] -> $target"
        place_cell [list $gate $target]
    }
}
set rawOutputs [get_nets -of_objects [get_pins {rx_clock_buffer/O u_eth_clk_wiz/inst/clkout1_buf/O}]]
set managedOutputs [get_nets -of_objects [get_pins -of_objects [get_cells $gates] -filter {REF_PIN_NAME == O}]]
set_property USER_CLOCK_ROOT $region [concat $rawOutputs $managedOutputs]
set_property UNAVAILABLE_DURING_CALIBRATION TRUE [get_ports {eth_txd[1]}]
set resetPort [get_ports c0_ddr4_reset_n]
set resetStarts [filter [all_fanin -flat -startpoints_only -to $resetPort] {REF_PIN_NAME == C}]
if {[llength $resetStarts]!=1 || [get_property NAME $resetStarts] ne {u_ddr/inst/u_ddr4_mem_intfc/u_ddr_cal_top/cal_RESET_n_reg[0]/C}} {error "MIG reset output mapping changed"}
# RESET_n is asynchronous (not a DDR data pin). Bound its physical leg to
# 20ns; retain MIG's initialization sequencing, which is measured in us.
set_max_delay -datapath_only 20.0 -from $resetStarts -to $resetPort
update_clock_routing
route_design -preserve
dict for {name expected} $frozen {
    set cell [get_cells $name]
    if {[llength $cell]!=1 || [list [get_property LOC $cell] [get_property BEL $cell]] ne $expected} {error "Data placement changed: $name"}
}
puts "DATA_PLACEMENT_PRESERVED [dict size $frozen] ONLY_TWO_PERIPHERAL_BUFGS_MAY_MOVE"
write_checkpoint routed.dcp
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_io.rpt
report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file rx_io.rpt
report_timing -delay_type min -slack_lesser_than 0 -max_paths 30 -input_pins -file failing_hold.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_cdc -details -file cdc.rpt
report_route_status -file route_status.rpt
report_clocks -file clocks.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
puts "NATIVE_PARALLEL_CLOCK_ECO_COMPLETE NO_BIT_GENERATED"
close_design
