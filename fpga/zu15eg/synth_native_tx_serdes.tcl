# Tiny fixed-pad feasibility only. No whole-board qualification or bit.
# Common real PLL500/DIV125, no source-latency replacement, no delay bias.
if {$argc!=2} {error "Expected SOURCE_DIRECTORY FRESH_OUTPUT_DIRECTORY"}
lassign $argv src out
if {[file exists $out]} {error "Preserve existing evidence"}
file mkdir $out
foreach f {native_tx_serdes_probe.sv native_gmac_divided_clock.sv native_tx_reset_boundary.sv native_divided_clock_constraints.tcl} {
    file copy [file join $src $f] [file join $out $f]
}
file copy [info script] [file join $out executed_synth.tcl]
set_param general.maxThreads 8
create_project -in_memory -part xczu15eg-ffvb1156-2-i
foreach f {native_tx_serdes_probe.sv native_gmac_divided_clock.sv native_tx_reset_boundary.sv} {
    read_verilog -sv [file join $out $f]
}
synth_design -top native_tx_serdes_probe -mode out_of_context -flatten_hierarchy none
create_clock -name ui_proxy -period 4.000 [get_ports ui_pad]
# This fresh isolated design has no imported IP clock references to rename.
# Define clocks on the actual DIV outputs directly; production uses its
# separately tested reference-retention helper, not this private probe code.
set common [get_pins clocks/pll/CLKOUT0]
foreach {cell name} {raw_div valence_tx_raw_div pad_div valence_tx_pad_div} {
    if {[get_property BUFGCE_DIVIDE [get_cells clocks/$cell]]!=4} {error "Missing physical DIV4"}
    create_generated_clock -name $name -source $common -divide_by 4 [get_pins clocks/$cell/O]
}
create_generated_clock -name valence_tx_forward_div -source $common -edges {1 2 3} -edge_shift {2 5 8} [get_pins clocks/forward_div/O]
set serial [get_pins clock_serdes/CLK]
set parallel [get_pins clock_serdes/CLKDIV]
if {[get_property DATA_WIDTH [get_cells clock_serdes]]!=8} {error "Wrong serialization width"}
set serialClocks [get_clocks -of_objects $serial]
set parallelClocks [get_clocks -of_objects $parallel]
if {[llength $serialClocks]!=1 || abs([get_property PERIOD $serialClocks]-2)>0.001} {error "Missing physical CLK500"}
if {[llength $parallelClocks]!=1 || abs([get_property PERIOD $parallelClocks]-8)>0.001} {error "Missing physical CLKDIV125"}
# The independently measured serialization pattern/reset epoch produces TXC
# rising at master 2ns, falling at 6ns. Both are real rising edges of CLK500.
create_generated_clock -name phy_tx_capture -source $serial -edges {3 7 11} [get_ports eth_txc]
lassign [get_property WAVEFORM [get_clocks phy_tx_capture]] rise fall
if {abs($rise-2)>0.001 || abs($fall-6)>0.001 || abs([get_property PERIOD [get_clocks phy_tx_capture]]-8)>0.001} {error "Incorrect measured TXC waveform"}
set_clock_uncertainty 0.100 [get_clocks ui_proxy]
foreach {port pin} {{eth_txd[0]} AC11 {eth_txd[1]} AC12 {eth_txd[2]} AA6 {eth_txd[3]} AA12 eth_tx_ctl AB8 eth_txc AC8} {
    set_property PACKAGE_PIN $pin [get_ports $port]
    set_property IOSTANDARD LVCMOS18 [get_ports $port]
    set_property DRIVE 8 [get_ports $port]
    set_property SLEW FAST [get_ports $port]
}
set region [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AC8]]]
if {[llength $region]!=1} {error "Missing actual TX pad clock region"}
set pllSites [lsort -dictionary [get_sites -of_objects $region -filter {NAME =~ PLL_X*}]]
if {[llength $pllSites]!=2} {error "Missing local PLL"}
set_property LOC [lindex $pllSites 0] [get_cells clocks/pll]
foreach c {clocks/delay_buffer clocks/raw_div clocks/pad_div clocks/forward_div tx_serial_buffer} {
    set_property USER_CLOCK_ROOT $region [get_nets -of_objects [get_pins $c/O]]
}
set_property CLOCK_DELAY_GROUP VALENCE_SERDES_PAD [get_nets -of_objects [get_pins {clocks/pad_div/O tx_serial_buffer/O}]]
# Only external asynchronous assertion to PRE/PLL RST is exempt. The
# registered releases to DIV CLR and OSERDES RST remain fully timed.
set asyncPresets [get_pins -hier -filter {REF_PIN_NAME == PRE}]
if {![llength $asyncPresets]} {error "Missing asynchronous assertion endpoints"}
set_false_path -from [get_ports {cold_reset tx_reset_request}] -to $asyncPresets
set_false_path -to [get_ports locked]
set_input_delay -clock valence_tx_raw_div -max 1.000 [get_ports {symbols_low[*] symbols_high[*]}]
set_input_delay -clock valence_tx_raw_div -min 0.000 [get_ports {symbols_low[*] symbols_high[*]}]
foreach extra {{} {-clock_fall -add_delay}} {
    set_output_delay -clock phy_tx_capture -max 1.250 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
    set_output_delay -clock phy_tx_capture -min -1.250 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
}
opt_design
place_design
phys_opt_design -directive Explore
route_design
write_checkpoint [file join $out routed.dcp]
write_xdc [file join $out actual_constraints.xdc]
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file [file join $out tx_io.rpt]
report_timing -to [get_pins {clock_serdes/RST clocks/raw_div/CLR clocks/pad_div/CLR clocks/forward_div/CLR}] -delay_type min_max -max_paths 12 -input_pins -file [file join $out timed_reset_release.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing_summary.rpt]
report_clocks -file [file join $out clocks.rpt]
report_drc -file [file join $out drc.rpt]
report_route_status -file [file join $out route_status.rpt]
set result [open [file join $out tx_lanes.csv] w]
puts $result "pin,setup_ns,hold_ns"
set qualified 1
foreach port [lsort [get_ports {eth_txd[*] eth_tx_ctl}]] {
    set maximum [get_timing_paths -to $port -delay_type max -max_paths 1]
    set minimum [get_timing_paths -to $port -delay_type min -max_paths 1]
    if {[llength $maximum]!=1 || [llength $minimum]!=1} {error "Missing physical lane path: $port"}
    set setup [get_property SLACK $maximum]
    set hold [get_property SLACK $minimum]
    puts $result "$port,$setup,$hold"
    if {$setup<0 || $hold<0} {set qualified 0}
}
close $result
puts "NATIVE_SERDES_PAD_PROBE_COMPLETE lanes_pass=$qualified PHY_BUDGET_1.250NS NO_BOARD_PROOF_NO_BIT"
close_project
