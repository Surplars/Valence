# Combined peripheral-only ECO. AUTO RTL must have normal-synthesis BUF_IN
# evidence; no attribute-only timing pass, no CPU synthesis or bit generation.
error "Historical rejected candidate: PLLE4 fine phase assumed MMCM granularity. Use the legal MMCM/PLL swap candidate instead."
if {$argc != 5} {error "Expected ROUTED_PARENT RX_SHORT RX_OOC ETH_OOC FRESH_OUTPUT"}
lassign $argv dcp proof rxOoc ethOoc out
if {[file exists $out]} {error "Preserve existing evidence"}
proc read_evidence {path} {
    set f [open $path r]; set value [read $f]; close $f; return $value
}
set receipt [read_evidence [file join $proof receipt.json]]
foreach required {{"status": "PASS_NATIVE_RX_DESKEW_SHORT"} {"delay_ps": 200} {"rx_phase_degrees": -11.25} {"rx_vco_hz": 1000000000} {"bypass_lock": "PASS"} {"corrupt_tx": "PASS"} {"corrupt_rx": "PASS"}} {
    if {![string match *$required* $receipt]} {error "Required short evidence missing: $required"}
}
foreach eye {positive eye_early eye_late} {
    set log [read_evidence [file join $proof $eye.log]]
    if {![string match {*PASS_RGMII_DDR_BOUNDARY*} $log] || [string match {*Fatal:*} $log]} {error "PHY eye case failed: $eye"}
}
set clockSource [read_evidence [file join $proof native_rx_clock.sv]]
foreach {dir modules} [list $rxOoc {native_rx_clock} $ethOoc {native_eth_clock native_eth_clock_probe}] {
    set compiled [read_evidence [file join $dir compiled_clock_source.sv]]
    foreach module $modules {
        set pattern [format {(?s)module %s\(.*?endmodule} $module]
        if {![regexp $pattern $compiled oldBody] || ![regexp $pattern $clockSource newBody] || $oldBody ne $newBody} {error "Used clock module differs from normal OOC: $module"}
    }
    if {![regexp -line {^COMPENSATION\s+string\s+false\s+BUF_IN\s*$} [read_evidence [file join $dir primitive_post_opt.rpt]]]} {
        error "Normal synthesis/opt did not retain physical BUF_IN feedback"
    }
}
if {![regexp -line {^CLKOUT0_PHASE\s+double\s+false\s+-11\.250\s*$} [read_evidence [file join $rxOoc primitive_post_opt.rpt]]]} {error "RX phase evidence mismatch"}
file mkdir $out
cd $out
file copy [info script] executed_feedback_eco.tcl
file copy [file join $proof native_rx_clock.sv] experimental_clock_source.sv
set_param general.maxThreads 8
open_checkpoint $dcp
set frozen [dict create]
foreach cell [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}] {
    dict set frozen $cell [list [get_property LOC $cell] [get_property BEL $cell]]
}
set region [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AA7]]]
set rxPll [get_cells native_rx_pll]
set rxFb [get_cells native_rx_feedback_buffer]
set ethMmcm [get_cells u_eth_clk_wiz/inst/mmcme4_adv_inst]
if {[llength $region]!=1 || [llength $rxPll]!=1 || [llength $rxFb]!=1 || [llength $ethMmcm]!=1} {error "Parent peripheral clocks missing"}
if {[get_clock_regions -of_objects [get_sites [get_property LOC $rxPll]]] ne $region} {error "PLL not in PHY bank"}
foreach {property expected} {CLKIN1_PERIOD 4.0 CLKFBOUT_MULT_F 4.0 DIVCLK_DIVIDE 1 CLKOUT0_DIVIDE_F 8.0 CLKOUT1_DIVIDE 2 CLKOUT0_PHASE 0.0 CLKOUT1_PHASE 0.0} {
    set actual [get_property $property $ethMmcm]
    puts "PARENT_ETH_ATTRIBUTE $property $actual"
    if {abs($actual-$expected)>0.001} {error "ETH MMCM differs from normally synthesized candidate: $property"}
}
set ethFbi [get_pins $ethMmcm/CLKFBIN]
set feedbackInput [get_nets -of_objects $ethFbi]
set driver [get_pins -leaf -of_objects [get_nets -segments $feedbackInput] -filter {DIRECTION == OUT}]
if {$driver ne "$ethMmcm/CLKFBOUT" && !([get_property COMPENSATION $ethMmcm] eq "INTERNAL" && [get_property TYPE $feedbackInput] eq "GROUND")} {
    error "Unexpected parent MMCM feedback: $driver"
}
puts "PARENT_ETH_FEEDBACK $driver [get_property COMPENSATION $ethMmcm]"
set oldFeedback [get_nets -quiet -of_objects [get_pins $ethMmcm/CLKFBOUT]]
if {[llength $oldFeedback]>1} {error "Ambiguous MMCM feedback output"}
set occupied {}
foreach cell [get_cells -hier -filter {REF_NAME == BUFGCE && LOC != ""}] {
    if {[regexp {BUFGCE_X0Y([0-9]+)} [get_property LOC $cell] -> y]} {lappend occupied [expr {$y%24}]}
}
set fbSites {}
foreach site [lsort -dictionary [get_sites -of_objects $region -filter {SITE_TYPE == BUFGCE}]] {
    if {[llength [get_cells -quiet -of_objects $site]]==0 && [regexp {BUFGCE_X0Y([0-9]+)} $site -> y] && [expr {$y%24}] ni $occupied} {
        lappend fbSites $site
    }
}
if {[llength $fbSites]==0} {error "No available local feedback candidate; preserve CPU"}
set ethRaw [get_nets -of_objects [get_pins u_eth_clk_wiz/inst/clkout1_buf/O]]
set rxRaw [get_nets -of_objects [get_pins rx_clock_buffer/O]]
set ethSource [get_nets -of_objects [get_pins $ethMmcm/CLKOUT0]]
set rxSource [get_nets -of_objects [get_pins native_rx_pll/CLKOUT0]]
set rxFeedback [get_nets -of_objects [get_pins native_rx_feedback_buffer/O]]
route_design -unroute -nets [concat $ethRaw $rxRaw $ethSource $rxSource $oldFeedback $rxFeedback]
set_property DONT_TOUCH TRUE $rxFb
# These attributes are the normal AUTO-lowering results proved above. Feedback
# topology, same-region clock roots, phase and actual routing must match too.
set_property COMPENSATION BUF_IN $rxPll
set_property -dict {CLKFBOUT_MULT 8 CLKOUT0_DIVIDE 8 CLKOUT0_PHASE -11.25} $rxPll
create_cell -reference BUFGCE native_eth_feedback_buffer
set_property -dict {CE_TYPE SYNC DONT_TOUCH TRUE} [get_cells native_eth_feedback_buffer]
set power [get_nets -of_objects [get_pins rx_clock_buffer/CE]]
if {[get_property TYPE $power] ne "POWER"} {error "Clock CE source not constant high"}
connect_net -net $power -objects [get_pins native_eth_feedback_buffer/CE]
set touch ""
if {$oldFeedback ne ""} {set touch [get_property DONT_TOUCH $oldFeedback]}
set inputTouch [get_property DONT_TOUCH $feedbackInput]
set_property DONT_TOUCH FALSE $feedbackInput
disconnect_net -net $feedbackInput -objects $ethFbi
if {$inputTouch ne ""} {set_property DONT_TOUCH $inputTouch $feedbackInput}
if {$oldFeedback eq ""} {
    create_net native_eth_feedback
    set oldFeedback [get_nets native_eth_feedback]
    connect_net -hier -net $oldFeedback -objects [get_pins $ethMmcm/CLKFBOUT]
} else {set_property DONT_TOUCH FALSE $oldFeedback}
connect_net -hier -net $oldFeedback -objects [get_pins native_eth_feedback_buffer/I]
create_net native_eth_feedback_buffered
connect_net -hier -net native_eth_feedback_buffered -objects [list [get_pins native_eth_feedback_buffer/O] $ethFbi]
if {$touch ne ""} {set_property DONT_TOUCH $touch $oldFeedback}
set_property COMPENSATION BUF_IN $ethMmcm
set ethFeedback [get_nets native_eth_feedback_buffered]
set_property USER_CLOCK_ROOT $region [concat $rxRaw $rxFeedback $ethRaw $ethFeedback]
set_property CLOCK_DELAY_GROUP VALENCE_RX_FEEDBACK [concat $rxRaw $rxFeedback]
set_property CLOCK_DELAY_GROUP VALENCE_TX_FEEDBACK [concat $ethRaw $ethFeedback]
set txSource [get_pins u_rgmii/tx_clock_ddr/CLK]
set master [get_clocks -of_objects $txSource]
if {[llength $master]!=1 || abs([get_property PERIOD $master]-8.0)>0.001} {error "Invalid real TX CLK master"}
create_generated_clock -name phy_tx_capture -source $txSource -edges {1 2 3} -edge_shift {2.0 2.0 2.0} [get_ports eth_txc]
set_property UNAVAILABLE_DURING_CALIBRATION TRUE [get_ports {eth_txd[1]}]
set resetPort [get_ports c0_ddr4_reset_n]
set resetStarts [filter [all_fanin -flat -startpoints_only -to $resetPort] {REF_PIN_NAME == C}]
if {[llength $resetStarts]!=1 || $resetStarts ne {u_ddr/inst/u_ddr4_mem_intfc/u_ddr_cal_top/cal_RESET_n_reg[0]/C}} {error "MIG asynchronous reset leg changed"}
set_max_delay -datapath_only 20.0 -from $resetStarts -to $resetPort
write_checkpoint modified.dcp
set legal 0
foreach site $fbSites {
    puts "ETH_FEEDBACK_SITE_TRY $site"
    set_property IS_LOC_FIXED FALSE [get_cells native_eth_feedback_buffer]
    place_cell [list native_eth_feedback_buffer $site]
    if {![catch {update_clock_routing} detail]} {set legal 1; break}
    puts "ETH_FEEDBACK_SITE_REJECTED $site $detail"
}
if {!$legal} {error "No legal feedback clock route; no timing pass claimed"}
write_checkpoint clocks_updated.dcp
route_design -preserve
dict for {name expected} $frozen {
    if {[list [get_property LOC [get_cells $name]] [get_property BEL [get_cells $name]]] ne $expected} {error "Original data/CPU placement changed: $name"}
}
puts "ORIGINAL_PLACEMENTS_PRESERVED [dict size $frozen] ONLY_NEW_ETH_FEEDBACK_BUFFER_PLACED"
set rxClock [get_clocks -of_objects [get_pins {u_rgmii/receive[0].rx_ddr/C}]]
if {[llength $rxClock]!=1 || abs([get_property PERIOD $rxClock]-8.0)>0.001} {error "RX clock not 125MHz"}
foreach direction {rx tx} {
    if {$direction eq "rx"} {set ports [get_ports {eth_rxd[*] eth_rx_ctl}]; set option -from} else {set ports [get_ports {eth_txd[*] eth_tx_ctl}]; set option -to}
    foreach port $ports {
        foreach delay {max min} {
            set path [get_timing_paths $option $port -delay_type $delay -max_paths 1]
            if {[llength $path]!=1 || ![string is double -strict [get_property SLACK $path]] || [get_property SLACK $path] eq "inf"} {error "Untimed boundary: $port $delay"}
            puts "IO_COVERAGE $port $delay [get_property SLACK $path]"
        }
    }
}
write_checkpoint routed.dcp
report_property -file rx_primitive.rpt $rxPll
report_property -file eth_primitive.rpt $ethMmcm
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file rx_io.rpt
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_io.rpt
report_timing -delay_type min -slack_lesser_than 0 -max_paths 30 -input_pins -file failing_hold.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_cdc -details -file cdc.rpt
report_route_status -file route_status.rpt
report_clocks -file clocks.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
puts "NATIVE_FEEDBACK_CLOCK_ECO_COMPLETE NO_CPU_SYNTHESIS_OR_BIT"
close_design
