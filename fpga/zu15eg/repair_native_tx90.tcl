# Local physical TXC+2ns ECO, software-owned PHY/MDIO. CPU netlist unchanged.
if {$argc!=6} {error "Expected BASE_DCP TX_SHORT ETH_OOC RX_OOC RESET_OOC FRESH_OUT"}
lassign $argv baseline proof ethOoc rxOoc resetOoc out
if {[file exists $out]} {error "Preserve previous evidence"}
proc tx90_text {p} {set f [open $p r]; set s [read $f]; close $f; return $s}
set receipt [tx90_text [file join $proof receipt.json]]
foreach expected {{"status": "PASS_NATIVE_TX90_SHORT"} {"physical_tx_phase_ns": 2.0} {"hardware_phy_init_enabled": false}} {
    if {![string match *$expected* $receipt]} {error "Short proof missing: $expected"}
}
foreach dir [list $ethOoc $rxOoc] {
    if {[tx90_text [file join $dir compiled_clock_source.sv]] ne [tx90_text [file join $proof native_gmac_clocks.sv]]} {error "Clock source mismatch"}
}
foreach {dir mode} [list $ethOoc INTERNAL $rxOoc ZHOLD] {
    if {![regexp -line [format {^COMPENSATION\s+string\s+false\s+%s\s*$} $mode] [tx90_text [file join $dir primitive_post_opt.rpt]]]} {error "Normal MMCM compensation unproved"}
}
file mkdir $out
cd $out
file copy [info script] executed_tx90_eco.tcl
foreach name {native_gmac_clocks.sv native_rgmii.sv native_tx_reset_boundary.sv} {file copy [file join $proof $name] $name}
set_param general.maxThreads 8
# Read actual normal lowering, not guessed primitive parameters.
open_checkpoint [file join $ethOoc post_opt.dcp]
set properties [dict create]
set template [get_cells clock_dut/mmcm]
foreach key [list_property $template] {
    if {[regexp {^(CLKFBOUT_|CLKIN[12]_PERIOD|CLKOUT[0-6]_|DIVCLK_DIVIDE$|COMPENSATION$|BANDWIDTH$|REF_JITTER[12]$|IS_.*_INVERTED$|SS_|STARTUP_WAIT$)} $key]} {
        dict set properties $key [get_property $key $template]
    }
}
if {[dict get $properties CLKOUT1_PHASE]!=90 || [dict get $properties CLKOUT0_DIVIDE_F]!=8 || [dict get $properties CLKOUT2_DIVIDE]!=2} {error "Wrong ETH clock lowering"}
close_design
open_checkpoint [file join $resetOoc reset.dcp]
set resetProperties [dict create]
for {set n 0} {$n<3} {incr n} {
    set c [get_cells [format {tx_forward_reset_pipe_reg[%d]} $n]]
    if {[get_property REF_NAME $c] ne "FDPE" || ![get_property ASYNC_REG $c]} {error "Unexpected normal reset lowering"}
    dict set resetProperties $n [list INIT [get_property INIT $c] IS_C_INVERTED [get_property IS_C_INVERTED $c] ASYNC_REG TRUE]
}
close_design
open_checkpoint $baseline
proc tx90_net {p} {set n [get_nets -of_objects [get_pins $p]]; if {[llength $n]!=1} {error "Missing connection $p"}; return $n}
set pll [get_cells native_rx_pll]
set raw [get_cells u_eth_clk_wiz/inst/clkout1_buf]
set ref [get_cells u_eth_clk_wiz/inst/clkout2_buf]
set rx [get_cells u_eth_clk_wiz/inst/mmcme4_adv_inst]
if {[get_property REF_NAME $pll] ne "PLLE4_ADV" || [get_property COMPENSATION $pll] ne "INTERNAL" ||
    [get_property COMPENSATION $rx] ne "ZHOLD" || [get_property CLKOUT0_PHASE $rx]!=22.5} {error "Wrong physical baseline"}
if {[llength [get_cells -quiet native_tx_pad_buffer]]} {error "Use non-isolated qualified parent"}
set input [tx90_net $pll/CLKIN]
set cold [tx90_net $pll/RST]
set ground [tx90_net $pll/CLKFBIN]
set power [tx90_net $raw/CE]
if {[get_property TYPE $ground] ne "GROUND" || [get_property TYPE $power] ne "POWER"} {error "Not normal constant clock pins"}
set txSource [tx90_net $pll/CLKOUT0]
set refSource [tx90_net $pll/CLKOUT1]
set lock [tx90_net $pll/LOCKED]
set rawOutput [tx90_net $raw/O]
set refOutput [tx90_net $ref/O]
set gateOutput [tx90_net u_soc/nativeBank/gmac/txManaged_gate/buffer/O]
set forwarded [get_pins u_rgmii/tx_clock_ddr/CLK]
if {[tx90_net $forwarded] ni [get_nets -segments $rawOutput]} {error "Unexpected original forward source"}
set sr [tx90_net u_rgmii/tx_clock_ddr/RST]
set assertion [tx90_net {tx_reset_pipe_reg[0]/PRE}]
set oldReset [get_cells {tx_reset_pipe_reg[0]}]
set frozen [dict create]
foreach c [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}] {
    if {$c ni [list $pll $raw $ref]} {dict set frozen $c [list [get_property LOC $c] [get_property BEL $c]]}
}
set oldClockNets [list $txSource $refSource $rawOutput $refOutput $gateOutput]
set mutable [get_nets -segments [concat $oldClockNets [list $input $cold $ground $power $lock $sr $assertion]]]
set saved [dict create]
foreach n $mutable {dict set saved $n [get_property DONT_TOUCH $n]; set_property DONT_TOUCH FALSE $n}
route_design -unroute -nets $oldClockNets
# Only old PLL leaves are removed; UI, cold reset and constants are NOT globally unrouted.
foreach p [get_pins -of_objects $pll] {
    set nets [get_nets -quiet -of_objects $p]
    if {[llength $nets]} {disconnect_net -net $nets -objects $p}
}
remove_cell $pll
create_cell -reference MMCME4_ADV native_eth_mmcm
dict for {key value} $properties {set_property $key $value [get_cells native_eth_mmcm]}
set_property PHASESHIFT_MODE WAVEFORM [get_cells native_eth_mmcm]
set_property CLOCK_DEDICATED_ROUTE SAME_CMT_COLUMN [get_nets -of_objects [get_pins u_ddr/inst/u_ddr4_infrastructure/u_bufg_divClk/O]]
foreach p [get_pins -of_objects [get_cells native_eth_mmcm] -filter {DIRECTION == IN}] {
    set leaf [get_property REF_PIN_NAME $p]
    switch -glob -- $leaf {
        CLKIN1 {set net $input}
        RST {set net $cold}
        CLKINSEL {set net $power}
        default {set net $ground}
    }
    connect_net -hier -net $net -objects $p
}
foreach {pin net} [list CLKOUT0 $txSource CLKOUT2 $refSource LOCKED $lock] {connect_net -hier -net $net -objects [get_pins native_eth_mmcm/$pin]}
create_net native_tx90_forward_source
connect_net -hier -net native_tx90_forward_source -objects [get_pins native_eth_mmcm/CLKOUT1]
create_cell -reference BUFGCE native_tx90_forward_buffer
set_property -dict [list CE_TYPE [get_property CE_TYPE $raw] SIM_DEVICE ULTRASCALE_PLUS DONT_TOUCH TRUE] [get_cells native_tx90_forward_buffer]
connect_net -hier -net native_tx90_forward_source -objects [get_pins native_tx90_forward_buffer/I]
connect_net -hier -net $power -objects [get_pins native_tx90_forward_buffer/CE]
create_net native_tx90_forward_clock
connect_net -hier -net native_tx90_forward_clock -objects [get_pins native_tx90_forward_buffer/O]
disconnect_net -net [tx90_net $forwarded] -objects $forwarded
connect_net -hier -net native_tx90_forward_clock -objects $forwarded
# Three actual FDPEs for forward-phase reset, matching normal small-module lowering.
create_net native_tx90_forward_reset
for {set n 0} {$n<3} {incr n} {
    set name [format {native_tx90_forward_reset_pipe_reg[%d]} $n]
    create_cell -reference FDPE $name
    set_property -dict [dict get $resetProperties $n] [get_cells $name]
    connect_net -hier -net native_tx90_forward_clock -objects [get_pins $name/C]
    connect_net -hier -net $power -objects [get_pins $name/CE]
    connect_net -hier -net $assertion -objects [get_pins $name/PRE]
    if {$n==0} {set dn $ground} else {set dn [format {native_tx90_forward_reset_stage_%d} [expr {$n-1}]]}
    if {$n==2} {set qn native_tx90_forward_reset} else {set qn [format {native_tx90_forward_reset_stage_%d} $n]; create_net $qn}
    connect_net -hier -net $dn -objects [get_pins $name/D]
    connect_net -hier -net $qn -objects [get_pins $name/Q]
    set_false_path -to [get_pins $name/PRE]
}
disconnect_net -net $sr -objects [get_pins u_rgmii/tx_clock_ddr/RST]
connect_net -hier -net native_tx90_forward_reset -objects [get_pins u_rgmii/tx_clock_ddr/RST]
# Select an unoccupied adjacent CMT and three legal tracks. Freeze all CPU/data.
set ioRegion [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AC8]]]
if {![regexp {^(X[0-9]+)Y([0-9]+)$} $ioRegion -> column row]} {error "Unknown PHY region"}
set ethRegion [get_clock_regions ${column}Y[expr {$row+1}]]
set ethSite [get_sites -of_objects $ethRegion -filter {NAME =~ MMCM*}]
if {[llength $ethSite]!=1 || [llength [get_cells -quiet -of_objects $ethSite]]} {error "No free adjacent MMCM"}
place_cell [list native_eth_mmcm $ethSite]
set buffers [list $raw $ref native_tx90_forward_buffer]
set occupied {}
foreach c [get_cells -hier -filter {REF_NAME == BUFGCE && LOC != ""}] {
    if {$c ni $buffers && [regexp {BUFGCE_X0Y([0-9]+)} [get_property LOC $c] -> y]} {lappend occupied [expr {$y%24}]}
}
foreach c $buffers {
    set site ""
    foreach s [lsort -dictionary [get_sites -of_objects $ethRegion -filter {SITE_TYPE == BUFGCE}]] {
        if {[llength [get_cells -quiet -of_objects $s]]==0 && [regexp {BUFGCE_X0Y([0-9]+)} $s -> y] && [expr {$y%24}] ni $occupied} {
            set site $s; lappend occupied [expr {$y%24}]; break
        }
    }
    if {$site eq ""} {error "No free Ethernet clock track"}
    set_property IS_LOC_FIXED FALSE [get_cells $c]
    set_property CLOCK_REGION $ethRegion [get_cells $c]
    place_cell [list $c $site]
    set_property USER_CLOCK_ROOT $ioRegion [tx90_net $c/O]
    puts "ETH_CLOCK_BUFFER $c $site ROOT=$ioRegion"
}
# Place the three new reset FFs close to the retained raw-phase chain; no full place_design.
set slice [get_property LOC $oldReset]
set regionSlices [lsort -dictionary [get_sites -of_objects $ioRegion -filter {SITE_TYPE == SLICEL || SITE_TYPE == SLICEM}]]
regexp {SLICE_X([0-9]+)Y([0-9]+)} $slice -> originX originY
set candidates {}
foreach s $regionSlices {
    regexp {SLICE_X([0-9]+)Y([0-9]+)} $s -> x y
    lappend candidates [list [expr {abs($x-$originX)+abs($y-$originY)}] $s]
}
set target ""
foreach candidate [lsort -integer -index 0 $candidates] {
    set s [lindex $candidate 1]
    if {[llength [get_cells -quiet -of_objects [get_sites $s]]]==0} {set target $s; break}
}
if {$target eq ""} {error "No empty local reset slice"}
for {set n 0} {$n<3} {incr n} {
    set name [format {native_tx90_forward_reset_pipe_reg[%d]} $n]
    set bel [lindex {AFF BFF CFF} $n]
    place_cell [list $name $target/$bel]
}
set_property CLOCK_DELAY_GROUP VALENCE_TX_PHASE_PAIR [get_nets [list $rawOutput native_tx90_forward_clock]]
set_property CLOCK_DELAY_GROUP VALENCE_MAC_TX_SERIAL $gateOutput
dict for {net value} $saved {if {$value ne "" && [llength [get_nets -quiet $net]]} {set_property DONT_TOUCH $value [get_nets $net]}}
create_generated_clock -name phy_tx_capture -source [get_pins u_rgmii/tx_clock_ddr/CLK] -divide_by 1 [get_ports eth_txc]
foreach edge {rising falling} {
    set extra {}
    if {$edge eq "falling"} {set extra {-clock_fall -add_delay}}
    set_output_delay -clock phy_tx_capture -max 1.250 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
    set_output_delay -clock phy_tx_capture -min -1.250 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
}
write_checkpoint modified.dcp
update_clock_routing
route_design -preserve
dict for {name expected} $frozen {
    if {[list [get_property LOC [get_cells $name]] [get_property BEL [get_cells $name]]] ne $expected} {error "Unrelated placement changed: $name"}
}
puts "ORIGINAL_PLACEMENTS_PRESERVED [dict size $frozen] ONLY_ETH_PLL_AND_TWO_ETH_BUFG_REPLACED_MOVED"
write_checkpoint routed.dcp
report_property -file eth_mmcm.rpt [get_cells native_eth_mmcm]
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_io.rpt
report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file rx_io.rpt
report_timing -delay_type max -max_paths 20 -input_pins -file setup_paths.rpt
report_timing -delay_type min -max_paths 20 -input_pins -file hold_paths.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_cdc -details -file cdc.rpt
report_route_status -file route_status.rpt
report_clocks -file clocks.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
puts "NATIVE_TX90_SOFTWARE_PHY_ECO_COMPLETE NO_BIT_GENERATED"
close_design
