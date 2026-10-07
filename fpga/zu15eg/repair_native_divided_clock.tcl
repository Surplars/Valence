# Historical two-DIV ECO entry. The three-DIV pad-isolated candidate must use
# finish_native_divided_clock.tcl with the saved two-DIV routed checkpoint.
if {$argc!=4} {error "Expected TX90_PARENT SHORT_PROOF NORMAL_OOC FRESH_OUT"}
lassign $argv baseline proof normal out
if {[file exists $out]} {error "Preserve evidence"}
proc div_text {p} {set f [open $p r]; set s [read $f]; close $f; return $s}
set receipt [div_text [file join $proof receipt.json]]
foreach token {{"status": "PASS_NATIVE_TX90_SHORT"} {"clock_architecture": "common_ref500_div4_phases"} {"hardware_phy_init_enabled": false}} {
    if {![string match *$token* $receipt]} {error "Current divider short proof absent: $token"}
}
if {[div_text [file join $normal compiled_clock_source.sv]] ne [div_text [file join $proof native_gmac_divided_clock.sv]]} {error "Normal/short source mismatch"}
file mkdir $out
cd $out
file copy [info script] executed_divided_eco.tcl
file copy [file join $proof native_gmac_divided_clock.sv] compiled_clock_source.sv
set_param general.maxThreads 8
open_checkpoint [file join $normal post_opt.dcp]
if {[llength [get_cells -quiet clock_dut/pad_div]]} {
    error "Three-DIV source requires finish_native_divided_clock.tcl; do not apply the historical two-DIV graph"
}
set cells [dict create]
set connections [dict create]
set map [dict create clock_dut/pll native_tx_ref_pll clock_dut/raw_div u_eth_clk_wiz/inst/clkout1_buf \
    clock_dut/forward_div native_tx90_forward_buffer clock_dut/delay_buffer u_eth_clk_wiz/inst/clkout2_buf]
foreach c [get_cells -hier -filter {IS_PRIMITIVE && NAME =~ clock_dut/* && REF_NAME != GND && REF_NAME != VCC}] {
    # Store plain names: Vivado object handles become null on close_design.
    set taskNormalName [get_property NAME $c]
    if {![dict exists $map $taskNormalName]} {dict set map $taskNormalName [string map {clock_dut/ native_tx_divider_ / _} $taskNormalName]}
    set props [dict create]
    foreach key [list_property $c] {
        if {[regexp {^(INIT$|ASYNC_REG$|IS_.*_INVERTED$|SIM_DEVICE$|CE_TYPE$|BUFGCE_DIVIDE$|CLKFBOUT_|CLKIN_PERIOD$|CLKOUT[01]_|CLKOUTPHY_MODE$|DIVCLK_DIVIDE$|COMPENSATION$|REF_JITTER$|STARTUP_WAIT$)} $key]} {
            set value [get_property $key $c]
            if {$value ne ""} {dict set props $key $value}
        }
    }
    dict set cells $taskNormalName [list [get_property REF_NAME $c] $props]
    foreach p [get_pins -of_objects $c] {
        set n [get_nets -quiet -of_objects $p]
        if {![llength $n]} {continue}
        set type [get_property TYPE $n]
        if {$type eq "GROUND"} {set key GROUND} elseif {$type eq "POWER"} {set key POWER} else {set key [get_property NAME $n]}
        dict set connections [list $taskNormalName [get_property REF_PIN_NAME $p]] $key
    }
}
if {[get_property COMPENSATION [get_cells clock_dut/pll]] ne "INTERNAL"} {error "Unproved PLL compensation"}
foreach c [get_cells {clock_dut/phase_reset_reg[*]}] {
    if {[get_property REF_NAME $c] ne "FDPE" || [get_property IS_C_INVERTED $c] ni {{} 0 1'b0} || ![get_property ASYNC_REG $c]} {error "Phase release is not own-clock rising-edge FDPE"}
}
set normalSpecial [dict create]
foreach {pin semantic} {clock_dut/pll/CLKIN INPUT clock_dut/pll/RST COLD clock_dut/pll/CLKOUT0 REFSOURCE \
    clock_dut/raw_div/O RAWOUTPUT clock_dut/forward_div/O FORWARDOUTPUT clock_dut/delay_buffer/O REFOUTPUT \
    clock_dut/locked_INST_0/O LOCK} {
    dict set normalSpecial [get_property NAME [get_nets -of_objects [get_pins $pin]]] $semantic
}
# Force complete serialization while the normal-design objects are alive.
set cells [string range "${cells} " 0 end-1]
set map [string range "${map} " 0 end-1]
set connections [string range "${connections} " 0 end-1]
set normalSpecial [string range "${normalSpecial} " 0 end-1]
close_design
open_checkpoint $baseline
proc div_net {p} {set n [get_nets -of_objects [get_pins $p]]; if {[llength $n]!=1} {error "Missing parent connection $p"}; return $n}
set old [get_cells native_eth_mmcm]
set raw [get_cells u_eth_clk_wiz/inst/clkout1_buf]
set fwd [get_cells native_tx90_forward_buffer]
set ref [get_cells u_eth_clk_wiz/inst/clkout2_buf]
if {[get_property REF_NAME $old] ne "MMCME4_ADV" || [get_property CLKOUT1_PHASE $old]!=90} {error "Wrong TX90 parent"}
set semantic [dict create INPUT [div_net $old/CLKIN1] COLD [div_net $old/RST] \
    GROUND [div_net $old/CLKFBIN] POWER [div_net $raw/CE] LOCK [div_net $old/LOCKED] \
    REFSOURCE [div_net $old/CLKOUT2] RAWOUTPUT [div_net $raw/O] \
    FORWARDOUTPUT [div_net $fwd/O] REFOUTPUT [div_net $ref/O]]
set rawSource [div_net $raw/I]
set fwdSource [div_net $fwd/I]
set gate [div_net u_soc/nativeBank/gmac/txManaged_gate/buffer/O]
set frozen [dict create]
set original [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}]
foreach c [get_property NAME $original] loc [get_property LOC $original] bel [get_property BEL $original] {
    if {$c ni [list $old $raw $fwd $ref]} {dict set frozen $c [list $loc $bel]}
}
set clockNets [list $rawSource $fwdSource [dict get $semantic REFSOURCE] [dict get $semantic RAWOUTPUT] \
    [dict get $semantic FORWARDOUTPUT] [dict get $semantic REFOUTPUT] $gate]
set saved [dict create]
foreach n [get_nets -segments [concat $clockNets [dict values $semantic]]] {
    dict set saved $n [get_property DONT_TOUCH $n]
    set_property DONT_TOUCH FALSE $n
}
route_design -unroute -nets $clockNets
foreach c [list $old $raw $fwd] {
    set_property DONT_TOUCH FALSE [get_cells $c]
    foreach p [get_pins -of_objects $c] {
        set n [get_nets -quiet -of_objects $p]
        if {[llength $n]} {disconnect_net -net $n -objects $p}
    }
    remove_cell $c
}
set netmap [dict create GROUND [dict get $semantic GROUND] POWER [dict get $semantic POWER]]
dict for {n key} $normalSpecial {dict set netmap $n [dict get $semantic $key]}
dict for {oldName spec} $cells {
    set name [dict get $map $oldName]
    lassign $spec kind props
    if {$oldName ne "clock_dut/delay_buffer"} {
        create_cell -reference $kind $name
        dict for {key value} $props {set_property $key $value [get_cells $name]}
    }
}
set index 0
dict for {pin key} $connections {
    lassign $pin oldName leaf
    if {$oldName eq "clock_dut/delay_buffer"} {continue}
    if {![dict exists $netmap $key]} {
        set n native_tx_divider_signal_$index; incr index
        create_net $n
        dict set netmap $key $n
    }
    connect_net -hier -net [dict get $netmap $key] -objects [get_pins [dict get $map $oldName]/$leaf]
}
set region [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AC8]]]
set pllSite [lindex [lsort -dictionary [get_sites -of_objects $region -filter {NAME =~ PLL_X*}]] 0]
if {[llength [get_cells -quiet -of_objects $pllSite]]} {error "Pad-local PLL occupied"}
place_cell [list native_tx_ref_pll $pllSite]
set divSites [lsort -dictionary [get_sites -of_objects $region -filter {SITE_TYPE == BUFGCE_DIV}]]
if {[llength $divSites]<2} {error "No local divider sites"}
foreach c [list [dict get $map clock_dut/raw_div] [dict get $map clock_dut/forward_div]] site [lrange $divSites 0 1] {
    if {[llength [get_cells -quiet -of_objects $site]]} {error "Local divider occupied"}
    place_cell [list $c $site]
    set_property USER_CLOCK_ROOT $region [div_net $c/O]
    puts "COMMON_SOURCE_DIVIDER $c LOC=$site ROOT=$region"
}
# Keep REFCLK local and off the DIV4-associated tracks (0,6), RX/CMU tracks.
set occupied {0 6}
foreach c [get_cells -hier -filter {REF_NAME == BUFGCE && LOC != ""}] {
    if {$c ne $ref && [regexp {BUFGCE_X0Y([0-9]+)} [get_property LOC $c] -> y]} {lappend occupied [expr {$y%24}]}
}
set refSite ""
foreach s [lsort -dictionary [get_sites -of_objects $region -filter {SITE_TYPE == BUFGCE}]] {
    if {[llength [get_cells -quiet -of_objects $s]]==0 && [regexp {BUFGCE_X0Y([0-9]+)} $s -> y] && [expr {$y%24}] ni $occupied} {set refSite $s; break}
}
if {$refSite eq ""} {error "No independent REF500 track"}
set_property IS_LOC_FIXED FALSE $ref
set_property CLOCK_REGION $region $ref
place_cell [list $ref $refSite]
set_property USER_CLOCK_ROOT $region [dict get $semantic REFOUTPUT]
# Place only the five new phase-release/lock controls near CMT, never CPU.
set slices [get_sites -of_objects $region -filter {SITE_TYPE == SLICEL || SITE_TYPE == SLICEM}]
set origin [get_property LOC [get_cells {tx_reset_pipe_reg[0]}]]
regexp {SLICE_X([0-9]+)Y([0-9]+)} $origin -> originX originY
set candidates {}
foreach s $slices {
    regexp {SLICE_X([0-9]+)Y([0-9]+)} $s -> x y
    lappend candidates [list [expr {abs($x-$originX)+abs($y-$originY)}] $s]
}
set target ""
foreach candidate [lsort -integer -index 0 $candidates] {
    set s [lindex $candidate 1]
    if {[llength [get_cells -quiet -of_objects $s]]==0} {set target $s; break}
}
if {$target eq ""} {error "No phase control slice"}
set ffBels {AFF BFF CFF}
set lutBels {D6LUT E6LUT}
dict for {oldName spec} $cells {
    lassign $spec kind props
    set c [dict get $map $oldName]
    if {$kind eq "FDPE"} {
        place_cell [list $c $target/[lindex $ffBels 0]]; set ffBels [lrange $ffBels 1 end]
        set_false_path -to [get_pins $c/PRE]
    } elseif {$kind eq "LUT2"} {
        place_cell [list $c $target/[lindex $lutBels 0]]; set lutBels [lrange $lutBels 1 end]
    }
}
dict for {n value} $saved {if {$value ne "" && [llength [get_nets -quiet $n]]} {set_property DONT_TOUCH $value [get_nets $n]}}
foreach {c name edges} [list [dict get $map clock_dut/raw_div] valence_tx_raw_div {1 5 9} [dict get $map clock_dut/forward_div] valence_tx_forward_div {3 7 11}] {
    create_generated_clock -name $name -source [get_pins $c/I] -edges $edges [get_pins $c/O]
}
set_property CLOCK_DELAY_GROUP VALENCE_TX_PHASE_PAIR [get_nets [list [dict get $semantic RAWOUTPUT] [dict get $semantic FORWARDOUTPUT]]]
set_property CLOCK_DELAY_GROUP VALENCE_MAC_TX_SERIAL $gate
create_generated_clock -name phy_tx_capture -source [get_pins u_rgmii/tx_clock_ddr/CLK] -divide_by 1 [get_ports eth_txc]
foreach extra {{} {-clock_fall -add_delay}} {
    set_output_delay -clock phy_tx_capture -max 1.250 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
    set_output_delay -clock phy_tx_capture -min -1.250 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
}
write_checkpoint modified.dcp
update_clock_routing
route_design -preserve
set actual [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}]
foreach c [get_property NAME $actual] loc [get_property LOC $actual] bel [get_property BEL $actual] {
    if {[dict exists $frozen $c] && [list $loc $bel] ne [dict get $frozen $c]} {error "Unrelated placement changed $c"}
}
puts "ORIGINAL_PLACEMENTS_PRESERVED [dict size $frozen] CPU_RX_UNCHANGED"
write_checkpoint routed.dcp
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_io.rpt
report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file rx_io.rpt
set controls [get_cells -hier -filter {NAME =~ native_tx_divider_* && REF_NAME == FDPE}]
report_timing -from $controls -delay_type min_max -max_paths 12 -input_pins -file phase_release.rpt
report_timing -to [get_pins [list [dict get $map clock_dut/raw_div]/CLR [dict get $map clock_dut/forward_div]/CLR]] -delay_type min_max -max_paths 8 -input_pins -file divider_clear.rpt
report_timing -delay_type max -max_paths 20 -input_pins -file setup_paths.rpt
report_timing -delay_type min -max_paths 20 -input_pins -file hold_paths.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_cdc -details -file cdc.rpt
report_route_status -file route_status.rpt
report_clocks -file clocks.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
puts "NATIVE_COMMON_SOURCE_DIV4_ECO_COMPLETE NO_CPU_SYNTHESIS_NO_BIT"
close_design
