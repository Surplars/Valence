# Private ODDR250 six-pad experiment. No board or bit qualification.
# Keep PHY setup/hold 1.250ns; no setup/hold multicycle or source-latency bias.
if {$argc<2 || $argc>3} {error "Expected SOURCE_DIRECTORY FRESH_OUTPUT_DIRECTORY ?IDENTICAL_PRIVATE_POST_SYNTH_DCP?"}
lassign $argv src out inherited
if {[file exists $out]} {error "Preserve existing evidence"}
file mkdir $out
foreach f {native_tx_quarter_ddr_probe.sv native_tx_reset_boundary.sv} {
    file copy [file join $src $f] [file join $out $f]
}
file copy [info script] [file join $out executed_synth.tcl]
set_param general.maxThreads 8
if {$inherited ne ""} {
    # Only the identical private six-pad DUT, never an old CPU/board proof.
    # Caller gates immutable short-proof and source identities first. Keep
    # the exact input checkpoint and repeat every real topology audit below.
    if {![file exists $inherited]} {error "Missing exact private post-synth checkpoint"}
    file copy $inherited [file join $out inherited_post_synth.dcp]
    open_checkpoint [file join $out inherited_post_synth.dcp]
    # NAME describes the checkpoint handle, not its RTL top module.
    if {[get_property TOP [current_design]] ne "native_tx_quarter_ddr_probe" ||
        [get_property PART [current_design]] ne "xczu15eg-ffvb1156-2-i" ||
        [get_property IS_BLOCK [current_design]] != 1} {error "Wrong inherited private DUT/part/OOC scope"}
} else {
    create_project -in_memory -part xczu15eg-ffvb1156-2-i
    foreach f {native_tx_quarter_ddr_probe.sv native_tx_reset_boundary.sv} {
        read_verilog -sv [file join $out $f]
    }
    synth_design -top native_tx_quarter_ddr_probe -mode out_of_context -flatten_hierarchy none
}
write_checkpoint [file join $out post_synth.dcp]
create_clock -name ui_proxy -period 4.000 [get_ports ui_pad]
foreach {cell name ratio} {word_buffer tx_word_125 4 quarter_buffer tx_quarter_250 2} {
    if {[get_property BUFGCE_DIVIDE [get_cells $cell]]!=$ratio} {error "Incorrect physical divider: $cell"}
    create_generated_clock -name $name -source [get_pins pll/CLKOUT0] -divide_by $ratio [get_pins $cell/O]
}
set source [get_pins clock_ddr/CLK]
set highClock [get_clocks -of_objects $source]
if {[llength $highClock]!=1 || abs([get_property PERIOD $highClock]-4)>0.001} {error "Expected actual CLK250"}
# The actual ODDR captures phase and its inverse on positive CLK250, then
# changes TXC only on negative edges: UI-word phases 2/6, period 8ns.
create_generated_clock -name phy_tx_capture -source $source -edges {2 4 6} [get_ports eth_txc]
lassign [get_property WAVEFORM [get_clocks phy_tx_capture]] rise fall
if {abs($rise-2)>0.001 || abs($fall-6)>0.001 || abs([get_property PERIOD [get_clocks phy_tx_capture]]-8)>0.001} {
    error "Wrong independently proved TXC waveform"
}
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
foreach c {reference_buffer word_buffer quarter_buffer} {
    set_property USER_CLOCK_ROOT $region [get_nets -of_objects [get_pins $c/O]]
}
set asyncPresets [get_pins -hier -filter {REF_PIN_NAME == PRE}]
if {![llength $asyncPresets]} {error "Missing reset-assertion endpoints"}
# External async assertion only. All functional reset releases remain timed.
set_false_path -from [get_ports {cold_reset tx_reset_request}] -to $asyncPresets
set_false_path -to [get_ports locked]
set_input_delay -clock tx_word_125 -max 1.000 [get_ports {symbols_low[*] symbols_high[*]}]
set_input_delay -clock tx_word_125 -min 0.000 [get_ports {symbols_low[*] symbols_high[*]}]
set outputs [get_ports {eth_txd[*] eth_tx_ctl}]
if {[llength $outputs]!=5} {error "Require five real PHY data/control pads"}
foreach extra {{} {-clock_fall -add_delay}} {
    set_output_delay -clock phy_tx_capture -max 1.250 {*}$extra $outputs
    set_output_delay -clock phy_tx_capture -min -1.250 {*}$extra $outputs
}
proc data_pin {cell index} {
    set cell [get_cells -quiet $cell]
    if {[llength $cell]!=1} {error "Missing actual ODDR cell"}
    set result {}
    foreach pin [get_pins -of_objects $cell] {
        set ref [get_property REF_PIN_NAME $pin]
        if {$ref eq [format {D[%d]} $index] || $ref eq "D$index"} {lappend result $pin}
    }
    if {[llength $result]!=1} {error "Missing actual ODDR data pin: $cell D$index"}
    return $result
}
proc audit_quarter_ddr {output} {
    set proof [open $output w]
    set serializers [get_cells -hier -filter {REF_NAME == OSERDESE3}]
    set lanes [get_cells -hier -filter {REF_NAME == OSERDESE3 && NAME =~ lanes*}]
    if {[llength $serializers]!=6 || [llength $lanes]!=5} {error "Require six actual dedicated ODDRs"}
    set clockNet [get_nets -of_objects [get_pins clock_ddr/CLK]]
    set resetNet [get_nets -of_objects [get_pins clock_ddr/RST]]
    if {[llength $clockNet]!=1 || [llength $resetNet]!=1} {error "Missing clock/reset net"}
    foreach c $serializers {
        if {[get_property ODDR_MODE $c] ne "TRUE" || [get_property OSERDES_D_BYPASS $c] ne "FALSE" ||
            [get_property IS_CLK_INVERTED $c] ni {0 1'b0} ||
            [get_property IS_RST_INVERTED $c] ni {{} 0 1'b0} ||
            [get_nets -of_objects [get_pins $c/CLK]] ne $clockNet ||
            [get_nets -of_objects [get_pins $c/RST]] ne $resetNet} {error "Not the proved dedicated ODDR250: $c"}
        puts $proof "$c SAME_REAL_CLK250_RESET ODDR_MODE_TRUE"
    }
    foreach c $lanes {
        set left [get_nets -of_objects [data_pin $c 0]]
        set right [get_nets -of_objects [data_pin $c 4]]
        if {[llength $left]!=1 || $left ne $right} {error "Actual D1/D2 pair differs: $c"}
        puts $proof "$c D0_D4_SAME_REAL_NET $left"
    }
    set phase [get_cells -quiet phase_high_reg]
    if {[llength $phase]!=1 || [get_property REF_NAME $phase] ne "FDPE" ||
        [get_property IS_C_INVERTED $phase] ni {{} 0 1'b0} ||
        [get_nets -of_objects [get_pins $phase/C]] ne $clockNet ||
        [get_nets -of_objects [get_pins $phase/PRE]] ne $resetNet ||
        [get_property TYPE [get_nets -of_objects [get_pins $phase/CE]]] ne "POWER"} {
        error "Missing unconditional same-clock preset-high phase counter"
    }
    set phaseQ [get_nets -of_objects [get_pins $phase/Q]]
    set inverse [get_nets -of_objects [get_pins $phase/D]]
    if {[get_nets -of_objects [data_pin clock_ddr 0]] ne $phaseQ ||
        [get_nets -of_objects [data_pin clock_ddr 4]] ne $inverse} {error "Actual TXC phase/inverse wiring changed"}
    set driver [get_pins -leaf -of_objects [get_nets -segments $inverse] -filter {DIRECTION == OUT}]
    if {[llength $driver]!=1} {error "Phase feedback must have one real driver"}
    set cell [get_cells -of_objects $driver]
    if {[get_property REF_NAME $cell] eq "INV"} {
        set input [get_pins $cell/I]
    } elseif {[get_property REF_NAME $cell] eq "LUT1" && [get_property INIT $cell] in {2'h1 2'b01}} {
        set input [get_pins $cell/I0]
    } else {error "Phase feedback is not exact logical inversion"}
    if {[get_nets -of_objects $input] ne $phaseQ} {error "Phase feedback does not invert its own Q"}
    puts $proof "TXC_NEGATIVE_EDGE_DIV2_PHASE_2_6 DATA_POSITIVE_PHASE_0_4"
    close $proof
    return $lanes
}
set lanes [audit_quarter_ddr [file join $out post_synth_identity.txt]]
foreach c $lanes {
    set oq [get_pins -of_objects $c -filter {REF_PIN_NAME == OQ}]
    if {[llength $oq]!=1} {error "Missing actual data OQ"}
    # No data transition on negative edges because physical D0 and D4 share
    # the same sampled net. ONLY data OQ-to-PHY arcs, no FF/reset exemption.
    set_false_path -fall_from $highClock -through $oq -to $outputs
}
opt_design
place_design
phys_opt_design -directive Explore
route_design
audit_quarter_ddr [file join $out routed_identity.txt]
write_checkpoint [file join $out routed.dcp]
write_xdc [file join $out actual_constraints.xdc]
report_timing -to $outputs -delay_type min_max -max_paths 10 -input_pins -file [file join $out tx_io.rpt]
set releases [concat [get_pins {clock_ddr/RST word_buffer/CLR quarter_buffer/CLR}] [get_pins -hier -filter {NAME =~ lanes* && REF_PIN_NAME == RST}]]
report_timing -to $releases -delay_type min_max -max_paths 16 -input_pins -file [file join $out timed_reset_release.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing_summary.rpt]
report_clocks -file [file join $out clocks.rpt]
report_drc -file [file join $out drc.rpt]
report_route_status -file [file join $out route_status.rpt]
report_exceptions -coverage -file [file join $out exception_coverage.rpt]
set result [open [file join $out tx_lanes.csv] w]
puts $result "pin,setup_ns,hold_ns"
set qualified 1
foreach port [lsort $outputs] {
    set maximum [get_timing_paths -to $port -delay_type max -max_paths 1]
    set minimum [get_timing_paths -to $port -delay_type min -max_paths 1]
    if {[llength $maximum]!=1 || [llength $minimum]!=1} {error "Missing real meaningful lane path: $port"}
    if {abs([get_property REQUIREMENT $maximum]-2)>0.001 || abs([get_property REQUIREMENT $minimum]+2)>0.001} {
        error "Pad edge relationship disagrees with independent transition oracle: $port"
    }
    set setup [get_property SLACK $maximum]
    set hold [get_property SLACK $minimum]
    puts $result "$port,$setup,$hold"
    if {$setup<0 || $hold<0} {set qualified 0}
}
close $result
puts "NATIVE_QUARTER_DDR_PAD_PROBE_COMPLETE lanes_pass=$qualified PHY_BUDGET_1.250NS NO_BOARD_PROOF_NO_BIT"
close_project
