# Local TX clock ECO from the routed TX90 parent. Never re-place CPU/RX logic.
if {$argc != 4} {error "Expected BASE_DCP SHORT_PROOF NORMAL_OOC FRESH_OUTPUT"}
lassign $argv baseline proof normal out
if {[file exists $out]} {error "Preserve existing evidence"}
proc pair_text {p} {set f [open $p r]; set s [read $f]; close $f; return $s}
set receipt [pair_text [file join $proof receipt.json]]
foreach expected {{"status": "PASS_NATIVE_TX90_SHORT"} {"clock_architecture": "local_pll_pair"} {"hardware_phy_init_enabled": false}} {
    if {![string match *$expected* $receipt]} {error "Short proof missing $expected"}
}
if {[pair_text [file join $normal compiled_clock_source.sv]] ne [pair_text [file join $proof native_gmac_pll_pair.sv]]} {error "Normal/short source mismatch"}
file mkdir $out
cd $out
file copy [info script] executed_pll_pair_eco.tcl
file copy [file join $proof native_gmac_pll_pair.sv] native_gmac_pll_pair.sv
set_param general.maxThreads 8
open_checkpoint [file join $normal post_opt.dcp]
set templates [dict create]
foreach {old new} {clock_dut/tx_pll native_tx_pll clock_dut/delay_pll native_delay_pll} {
    set c [get_cells $old]
    if {[get_property COMPENSATION $c] ne "INTERNAL" || [get_property REF_NAME $c] ne "PLLE4_ADV"} {error "Wrong PLL compensation"}
    set props [dict create]
    foreach key [list_property $c] {
        if {[regexp {^(CLKFBOUT_|CLKIN_PERIOD$|CLKOUT[01]_|CLKOUTPHY_MODE$|DIVCLK_DIVIDE$|COMPENSATION$|REF_JITTER$|IS_.*_INVERTED$|STARTUP_WAIT$)} $key]} {
            dict set props $key [get_property $key $c]
        }
    }
    dict set templates $new $props
}
set luts [get_cells -hier -filter {REF_NAME == LUT2}]
if {[llength $luts]!=1 || [get_property INIT $luts] ne "4'h8"} {error "Normal lock AND lowering unproved"}
close_design
open_checkpoint $baseline
proc pair_net {p} {set n [get_nets -of_objects [get_pins $p]]; if {[llength $n]!=1} {error "Missing connection $p"}; return $n}
set old [get_cells native_eth_mmcm]
if {[get_property REF_NAME $old] ne "MMCME4_ADV" || [get_property CLKOUT1_PHASE $old]!=90} {error "Wrong TX90 physical parent"}
set raw [get_cells u_eth_clk_wiz/inst/clkout1_buf]
set ref [get_cells u_eth_clk_wiz/inst/clkout2_buf]
set fwd [get_cells native_tx90_forward_buffer]
set rx [get_cells u_eth_clk_wiz/inst/mmcme4_adv_inst]
if {[get_property COMPENSATION $rx] ne "ZHOLD" || [get_property CLKOUT0_PHASE $rx]!=22.5} {error "Wrong RX parent"}
set input [pair_net $old/CLKIN1]
set cold [pair_net $old/RST]
set ground [pair_net $old/CLKFBIN]
set lock [pair_net $old/LOCKED]
set rawSource [pair_net $old/CLKOUT0]
set fwdSource [pair_net $old/CLKOUT1]
set refSource [pair_net $old/CLKOUT2]
set rawOutput [pair_net $raw/O]
set refOutput [pair_net $ref/O]
set fwdOutput [pair_net $fwd/O]
set gateOutput [pair_net u_soc/nativeBank/gmac/txManaged_gate/buffer/O]
set frozen [dict create]
foreach c [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}] {
    if {$c ni [list $old $raw $ref $fwd]} {dict set frozen $c [list [get_property LOC $c] [get_property BEL $c]]}
}
set clockNets [list $rawSource $fwdSource $refSource $rawOutput $refOutput $fwdOutput $gateOutput]
set saved [dict create]
foreach n [get_nets -segments [concat $clockNets [list $input $cold $ground $lock]]] {
    dict set saved $n [get_property DONT_TOUCH $n]
    set_property DONT_TOUCH FALSE $n
}
route_design -unroute -nets $clockNets
foreach p [get_pins -of_objects $old] {
    set n [get_nets -quiet -of_objects $p]
    if {[llength $n]} {disconnect_net -net $n -objects $p}
}
remove_cell $old
foreach name {native_tx_pll native_delay_pll} {
    create_cell -reference PLLE4_ADV $name
    dict for {key value} [dict get $templates $name] {set_property $key $value [get_cells $name]}
    set_property PHASESHIFT_MODE WAVEFORM [get_cells $name]
    foreach p [get_pins -of_objects [get_cells $name] -filter {DIRECTION == IN}] {
        switch -- [get_property REF_PIN_NAME $p] {
            CLKIN {set n $input}
            RST {set n $cold}
            default {set n $ground}
        }
        connect_net -hier -net $n -objects $p
    }
    set n ${name}_locked
    create_net $n
    connect_net -hier -net $n -objects [get_pins $name/LOCKED]
}
foreach {pin net} [list native_tx_pll/CLKOUT0 $rawSource native_tx_pll/CLKOUT1 $fwdSource native_delay_pll/CLKOUT0 $refSource] {
    connect_net -hier -net $net -objects [get_pins $pin]
}
create_cell -reference LUT2 native_eth_lock_and
set_property INIT 4'h8 [get_cells native_eth_lock_and]
connect_net -hier -net native_tx_pll_locked -objects [get_pins native_eth_lock_and/I0]
connect_net -hier -net native_delay_pll_locked -objects [get_pins native_eth_lock_and/I1]
connect_net -hier -net $lock -objects [get_pins native_eth_lock_and/O]
set region [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AC8]]]
set pllSites [lsort -dictionary [get_sites -of_objects $region -filter {NAME =~ PLL_X*}]]
if {[llength $pllSites]!=2} {error "Expected two pad-local PLL sites"}
foreach name {native_tx_pll native_delay_pll} site $pllSites {
    if {[llength [get_cells -quiet -of_objects $site]]} {error "PLL site occupied $site"}
    place_cell [list $name $site]
}
set buffers [list $raw $fwd $ref]
set tracks {}
foreach c [get_cells -hier -filter {REF_NAME == BUFGCE && LOC != ""}] {
    if {$c ni $buffers && [regexp {BUFGCE_X0Y([0-9]+)} [get_property LOC $c] -> y]} {lappend tracks [expr {$y%24}]}
}
foreach c $buffers {
    set target ""
    foreach s [lsort -dictionary [get_sites -of_objects $region -filter {SITE_TYPE == BUFGCE}]] {
        if {[llength [get_cells -quiet -of_objects $s]]==0 && [regexp {BUFGCE_X0Y([0-9]+)} $s -> y] && [expr {$y%24}] ni $tracks} {
            set target $s; lappend tracks [expr {$y%24}]; break
        }
    }
    if {$target eq ""} {error "No free local global clock track"}
    set_property IS_LOC_FIXED FALSE $c
    set_property CLOCK_REGION $region $c
    place_cell [list $c $target]
    set_property USER_CLOCK_ROOT $region [pair_net $c/O]
    puts "LOCAL_PLL_BUFFER $c $target ROOT=$region"
}
set lockSite ""
foreach s [lsort -dictionary [get_sites -of_objects $region -filter {SITE_TYPE == SLICEL || SITE_TYPE == SLICEM}]] {
    if {[llength [get_cells -quiet -of_objects $s]]==0} {set lockSite $s; break}
}
if {$lockSite eq ""} {error "No local empty LUT site"}
place_cell [list native_eth_lock_and $lockSite/A6LUT]
set_property CLOCK_DELAY_GROUP VALENCE_TX_PHASE_PAIR [get_nets [list $rawOutput $fwdOutput]]
set_property CLOCK_DELAY_GROUP VALENCE_MAC_TX_SERIAL $gateOutput
dict for {n v} $saved {if {$v ne "" && [llength [get_nets -quiet $n]]} {set_property DONT_TOUCH $v [get_nets $n]}}
create_generated_clock -name phy_tx_capture -source [get_pins u_rgmii/tx_clock_ddr/CLK] -divide_by 1 [get_ports eth_txc]
foreach extra {{} {-clock_fall -add_delay}} {
    set_output_delay -clock phy_tx_capture -max 1.250 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
    set_output_delay -clock phy_tx_capture -min -1.250 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
}
write_checkpoint modified.dcp
update_clock_routing
route_design -preserve
dict for {c expected} $frozen {
    if {[list [get_property LOC [get_cells $c]] [get_property BEL [get_cells $c]]] ne $expected} {error "Unrelated placement changed $c"}
}
puts "ORIGINAL_PLACEMENTS_PRESERVED [dict size $frozen] CPU_RX_UNCHANGED"
write_checkpoint routed.dcp
foreach c {native_tx_pll native_delay_pll} {report_property -file ${c}.rpt [get_cells $c]}
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
puts "NATIVE_PLL_PAIR_ECO_COMPLETE NO_CPU_SYNTHESIS_NO_BIT"
close_design
