# Private TX-only real-pad experiment. No bit or whole-board qualification.
# PHY budget is always 1.250ns. SDR-pair exemptions require actual net identity
# and the independent unused-edge/duplicate-breach UNISIM proof first.
if {$argc!=2} {error "Expected SOURCE_DIRECTORY FRESH_OUTPUT_DIRECTORY"}
lassign $argv src out
if {[file exists $out]} {error "Preserve existing evidence"}
file mkdir $out
foreach f {native_tx_sdr_probe.sv native_tx_reset_boundary.sv} {file copy [file join $src $f] [file join $out $f]}
file copy [info script] [file join $out executed_synth.tcl]
set_param general.maxThreads 8
create_project -in_memory -part xczu15eg-ffvb1156-2-i
foreach f {native_tx_sdr_probe.sv native_tx_reset_boundary.sv} {read_verilog -sv [file join $out $f]}
synth_design -top native_tx_sdr_probe -mode out_of_context -flatten_hierarchy none
write_checkpoint [file join $out post_synth.dcp]
set diagnostic [open [file join $out synthesized_serializer_properties.txt] w]
foreach cell [get_cells -hier -filter {REF_NAME == OSERDESE3}] {
    puts $diagnostic "CELL $cell"
    foreach property [lsort [list_property $cell]] {
        puts $diagnostic "$property = [get_property $property $cell]"
    }
    foreach pin [get_pins -of_objects $cell] {
        puts $diagnostic "PIN [get_property REF_PIN_NAME $pin] NET [get_nets -of_objects $pin]"
    }
}
close $diagnostic
create_clock -name ui_proxy -period 4.000 [get_ports ui_pad]
set common [get_pins pll/CLKOUT0]
foreach {cell name ratio} {word_buffer tx_word_125 4 data_buffer tx_sdr_250 2} {
    if {[get_property BUFGCE_DIVIDE [get_cells $cell]]!=$ratio} {error "Incorrect physical divider: $cell"}
    create_generated_clock -name $name -source $common -divide_by $ratio [get_pins $cell/O]
}
set clockSource [get_pins clock_serdes/CLK]
set highClock [get_clocks -of_objects $clockSource]
if {[llength $highClock]!=1 || abs([get_property PERIOD $highClock]-2)>0.001} {error "Expected real CLK500"}
# Actual UNISIM shows the SDR data symbols at raw+4/raw+8 and TXC at
# raw+6/raw+10. Both TXC edges are actual positive edges of CLK500.
create_generated_clock -name phy_tx_capture -source $clockSource -edges {7 11 15} [get_ports eth_txc]
lassign [get_property WAVEFORM [get_clocks phy_tx_capture]] rise fall
if {abs($rise-6)>0.001 || abs($fall-10)>0.001 || abs([get_property PERIOD [get_clocks phy_tx_capture]]-8)>0.001} {error "Wrong independently proved TXC waveform"}
set_clock_uncertainty 0.100 [get_clocks ui_proxy]
foreach {port pin} {{eth_txd[0]} AC11 {eth_txd[1]} AC12 {eth_txd[2]} AA6 {eth_txd[3]} AA12 eth_tx_ctl AB8 eth_txc AC8} {
    set_property PACKAGE_PIN $pin [get_ports $port]
    set_property IOSTANDARD LVCMOS18 [get_ports $port]
    set_property DRIVE 8 [get_ports $port]
    set_property SLEW FAST [get_ports $port]
}
set region [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AC8]]]
if {[llength $region]!=1} {error "Missing actual TX pad region"}
set pllSites [lsort -dictionary [get_sites -of_objects $region -filter {NAME =~ PLL_X*}]]
if {[llength $pllSites]!=2} {error "Missing pad-local PLL"}
set_property LOC [lindex $pllSites 0] [get_cells pll]
foreach c {reference_buffer word_buffer data_buffer clock_buffer} {
    set_property USER_CLOCK_ROOT $region [get_nets -of_objects [get_pins $c/O]]
}
set_property CLOCK_DELAY_GROUP VALENCE_SDR_PADS [get_nets -of_objects [get_pins {data_buffer/O clock_buffer/O}]]
# External async assertion only; release to DIV CLR, SERDES RST, and both
# edges of the local word registers remain timed and are reported below.
set asyncPresets [get_pins -hier -filter {REF_PIN_NAME == PRE}]
if {![llength $asyncPresets]} {error "Missing reset-assertion endpoints"}
set_false_path -from [get_ports {cold_reset tx_reset_request}] -to $asyncPresets
set_false_path -to [get_ports locked]
set_input_delay -clock tx_word_125 -max 1.000 [get_ports {symbols_low[*] symbols_high[*]}]
set_input_delay -clock tx_word_125 -min 0.000 [get_ports {symbols_low[*] symbols_high[*]}]
foreach extra {{} {-clock_fall -add_delay}} {
    set_output_delay -clock phy_tx_capture -max 1.250 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
    set_output_delay -clock phy_tx_capture -min -1.250 {*}$extra [get_ports {eth_txd[*] eth_tx_ctl}]
}
proc data_pin {cell index} {
    set result {}
    foreach pin [get_pins -of_objects $cell] {
        set ref [get_property REF_PIN_NAME $pin]
        if {$ref eq [format {D[%d]} $index] || $ref eq "D$index"} {lappend result $pin}
    }
    if {[llength $result]!=1} {error "Missing actual serializer data pin: $cell D$index"}
    return $result
}
set pairProof [open [file join $out synthesized_sdr_pairs.txt] w]
set lanes [get_cells -hier -filter {REF_NAME == OSERDESE3 && NAME =~ lanes*}]
if {[llength $lanes]!=5} {error "Require exactly five actual SDR data serializers"}
foreach c $lanes {
    if {[get_property DATA_WIDTH $c]!=4 || [get_property IS_CLK_INVERTED $c] ni {0 1'b0} ||
        [get_property IS_CLKDIV_INVERTED $c] ni {0 1'b0} || [get_property ODDR_MODE $c] ne "FALSE" ||
        [get_property OSERDES_D_BYPASS $c] ne "FALSE"} {
        error "Not the proved SDR2 architecture: $c; DATA_WIDTH=[get_property DATA_WIDTH $c], IS_CLK_INVERTED=[get_property IS_CLK_INVERTED $c], IS_CLKDIV_INVERTED=[get_property IS_CLKDIV_INVERTED $c], ODDR_MODE=[get_property ODDR_MODE $c], OSERDES_D_BYPASS=[get_property OSERDES_D_BYPASS $c]"
    }
    foreach {a b} {0 1 2 3} {
        set left [get_nets -of_objects [data_pin $c $a]]
        set right [get_nets -of_objects [data_pin $c $b]]
        if {[llength $left]!=1 || [llength $right]!=1 || $left ne $right} {error "SDR duplicate pair broken: $c D$a/D$b"}
        puts $pairProof "$c D$a/D$b SAME_REAL_NET $left"
    }
    set oq [get_pins -of_objects $c -filter {REF_PIN_NAME == OQ}]
    if {[llength $oq]!=1} {error "Missing actual SDR OQ"}
    # This is NOT a global clock exception. D0/D1 and D2/D3 share one real
    # net, so opposite CLK250 edge cannot change this lane's OQ. Scope only
    # to the output arc and its real PHY pad, never registers or reset.
    set_false_path -fall_from [get_clocks tx_sdr_250] -through $oq -to [get_ports {eth_txd[*] eth_tx_ctl}]
}
close $pairProof
opt_design
place_design
phys_opt_design -directive Explore
route_design
write_checkpoint [file join $out routed.dcp]
write_xdc [file join $out actual_constraints.xdc]
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file [file join $out tx_io.rpt]
set releases [get_pins {clock_serdes/RST word_buffer/CLR data_buffer/CLR}]
set releases [concat $releases [get_pins -hier -filter {NAME =~ lanes* && REF_PIN_NAME == RST}]]
report_timing -to $releases -delay_type min_max -max_paths 16 -input_pins -file [file join $out timed_reset_release.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing_summary.rpt]
report_clocks -file [file join $out clocks.rpt]
report_drc -file [file join $out drc.rpt]
report_route_status -file [file join $out route_status.rpt]
report_exceptions -coverage -file [file join $out exception_coverage.rpt]
set result [open [file join $out tx_lanes.csv] w]
puts $result "pin,setup_ns,hold_ns"
set qualified 1
foreach port [lsort [get_ports {eth_txd[*] eth_tx_ctl}]] {
    set maximum [get_timing_paths -to $port -delay_type max -max_paths 1]
    set minimum [get_timing_paths -to $port -delay_type min -max_paths 1]
    if {[llength $maximum]!=1 || [llength $minimum]!=1} {error "Missing real meaningful lane path: $port"}
    set setup [get_property SLACK $maximum]
    set hold [get_property SLACK $minimum]
    puts $result "$port,$setup,$hold"
    if {$setup<0 || $hold<0} {set qualified 0}
}
close $result
puts "NATIVE_SDR_PAD_PROBE_COMPLETE lanes_pass=$qualified PHY_BUDGET_1.250NS NO_BOARD_PROOF_NO_BIT"
close_project
