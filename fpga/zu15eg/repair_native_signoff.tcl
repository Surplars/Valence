# Source-matched board-only ECO. Preserve all original primitive placements.
# No synthesis, full placement, functional false paths, or bit generation here.
if {$argc != 2} {error "Expected ROUTED_PARENT_DCP FRESH_OUTPUT_DIR"}
lassign $argv dcp out
if {[file exists $out]} {error "Preserve existing evidence"}
file mkdir $out
cd $out
set_param general.maxThreads 8
open_checkpoint $dcp
puts [help update_clock_routing]
puts [help route_design]
puts [help place_cell]
set frozen [dict create]
foreach cell [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}] {
    dict set frozen [get_property NAME $cell] [list [get_property LOC $cell] [get_property BEL $cell]]
}
# RX already has the exact soc_reset OR !aggregated_RDY expression. Reuse it
# for TX instead of adding a duplicate LUT; every replica participates.
set rxGate [get_cells {rx_reset_pipe[2]_i_1}]
if {[llength $rxGate]!=1 || [get_property INIT $rxGate] ne "4'hB"} {error "Unexpected RX gate"}
set rxReset [get_nets -of_objects [get_pins $rxGate/O]]
set ready [get_nets -of_objects [get_pins $rxGate/I1]]
set socReset [get_nets -of_objects [get_pins {reset_pipe_reg[2]/Q}]]
set rxSoc [get_nets -segments -of_objects [get_pins $rxGate/I0]]
if {[get_pins -leaf -of_objects $rxSoc -filter {DIRECTION == OUT}] ne {reset_pipe_reg[2]/Q}} {error "Wrong RX reset expression"}
set readySources [all_fanin -flat -startpoints_only -to [get_pins $rxGate/I1]]
if {[llength $readySources]!=3} {error "Expected three replicated calibration controllers"}
foreach pin $readySources {
    if {[get_property REF_PIN_NAME $pin] ne "RDY" || [get_property REF_NAME [get_cells -of_objects $pin]] ne "IDELAYCTRL"} {error "Unaudited aggregate RDY"}
}
set phyPins [get_pins {phy_reset_pipe_reg[0]/PRE phy_reset_pipe_reg[1]/PRE phy_reset_pipe_reg[2]/PRE}]
set txPins [get_pins {tx_reset_pipe_reg[0]/PRE tx_reset_pipe_reg[1]/PRE tx_reset_pipe_reg[2]/PRE}]
if {[llength $phyPins]!=3 || [llength $txPins]!=3} {error "Missing reset synchronizer stages"}
set phyReset [get_nets -of_objects [get_pins {phy_reset_pipe_reg[0]/PRE}]]
foreach pin $phyPins {if {[get_nets -of_objects $pin] ne $phyReset} {error "Non-common PHY assertion"}}
foreach pin $txPins {if {[get_nets -of_objects $pin] ne $socReset} {error "Non-common original TX assertion"}}
set mutable [concat [get_nets -segments [list $phyReset $socReset $ready $rxReset]] [get_cells -of_objects [concat $phyPins $txPins]]]
set oldDontTouch [dict create]
foreach obj $mutable {
    dict set oldDontTouch $obj [get_property DONT_TOUCH $obj]
    set_property DONT_TOUCH FALSE $obj
}
create_cell -reference LUT2 phy_calibration_reset_gate
set_property INIT 4'hB [get_cells phy_calibration_reset_gate]
for {set i 0} {$i<4} {incr i} {
    if {((0xB >> $i)&1) != (($i&1)!=0 || ($i&2)==0)} {error "Reset truth table fails"}
}
create_net phy_calibration_reset
connect_net -hier -net $phyReset -objects [get_pins phy_calibration_reset_gate/I0]
connect_net -hier -net $ready -objects [get_pins phy_calibration_reset_gate/I1]
connect_net -net phy_calibration_reset -objects [get_pins phy_calibration_reset_gate/O]
set resetCells [get_cells -of_objects [concat $phyPins $txPins]]
set_property ASYNC_REG FALSE $resetCells
disconnect_net -net $phyReset -objects $phyPins
connect_net -net phy_calibration_reset -objects $phyPins
disconnect_net -net $socReset -objects $txPins
connect_net -hier -net $rxReset -objects $txPins
set_property ASYNC_REG TRUE $resetCells
# Place just the one new LUT on an entirely free LUT pair near the PHY chain.
set target ""
foreach x {100 99 101 98 102} {
    foreach y {96 95 97 94 98} {
        foreach letter {A B C D E F G H} {
            set site SLICE_X${x}Y${y}
            set bel [get_bels -quiet $site/${letter}6LUT]
            set half [get_bels -quiet $site/${letter}5LUT]
            if {[llength $bel]==1 && [llength [get_cells -of_objects [concat $bel $half]]]==0} {
                set target $site/${letter}6LUT
                break
            }
        }
        if {$target ne ""} {break}
    }
    if {$target ne ""} {break}
}
if {$target eq ""} {error "No local free LUT pair; do not move CPU placement"}
place_cell [list phy_calibration_reset_gate $target]
dict for {obj value} $oldDontTouch {if {$value ne ""} {set_property DONT_TOUCH $value $obj}}
# Advanced post-placement clock ECO supported by installed Vivado 2025.1.
# Unroute ONLY the two raw global clocks; preserve all unrelated routes.
set region [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AA7]]]
if {[llength $region]!=1} {error "Missing pad clock region"}
set clocks {}
foreach path {rx_clock_buffer u_eth_clk_wiz/inst/clkout1_buf} {
    set net [get_nets -of_objects [get_pins $path/O]]
    if {[llength $net]!=1} {error "Missing immediate clock net"}
    puts "LOCAL_CLOCK_ROOT $net [get_property CLOCK_ROOT $net] -> $region"
    set_property USER_CLOCK_ROOT $region $net
    lappend clocks $net
}
write_checkpoint modified.dcp
route_design -unroute -nets $clocks
update_clock_routing
route_design -preserve
dict for {name expected} $frozen {
    set cell [get_cells $name]
    if {[llength $cell]!=1 || [list [get_property LOC $cell] [get_property BEL $cell]] ne $expected} {
        error "Original placement changed during board-only ECO: $name"
    }
}
puts "PLACEMENT_PRESERVED [dict size $frozen] ORIGINAL_PRIMITIVES new_luts=1"
write_checkpoint routed.dcp
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_io.rpt
report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file rx_io.rpt
set cpu [get_clocks -of_objects [get_pins u_soc/clock]]
set cpuRegs [all_registers -clock $cpu]
report_timing -from $cpuRegs -to $cpuRegs -delay_type min_max -max_paths 5 -input_pins -file cpu_internal.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_cdc -details -file cdc.rpt
report_route_status -file route_status.rpt
report_clock_interaction -file clock_interaction.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
puts "NATIVE_LOCAL_SIGNOFF_ECO_COMPLETE REQUIRES_SIGNOFF NO_BIT_GENERATED"
close_design
