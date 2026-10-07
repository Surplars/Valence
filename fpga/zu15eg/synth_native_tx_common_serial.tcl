# Private shared-CLK500 DATA8 TX pad experiment, not board proof or a bit.
# Every nibble occupies four serial bits. The independent UNISIM oracle
# checks all transitions, both PHY eyes, reset/relock, and five negative cases.
if {$argc!=2} {error "Expected SOURCE_DIRECTORY FRESH_OUTPUT_DIRECTORY"}
lassign $argv src out
if {[file exists $out]} {error "Preserve existing evidence"}
file mkdir $out
foreach f {native_tx_common_serial_probe.sv native_tx_reset_boundary.sv} {
    file copy [file join $src $f] [file join $out $f]
}
file copy [info script] [file join $out executed_synth.tcl]
set_param general.maxThreads 8
create_project -in_memory -part xczu15eg-ffvb1156-2-i
foreach f {native_tx_common_serial_probe.sv native_tx_reset_boundary.sv} {
    read_verilog -sv [file join $out $f]
}
synth_design -top native_tx_common_serial_probe -mode out_of_context -flatten_hierarchy none
write_checkpoint [file join $out post_synth.dcp]
create_clock -name ui_proxy -period 4.000 [get_ports ui_pad]
if {[get_property BUFGCE_DIVIDE [get_cells word_buffer]]!=4} {error "Incorrect physical word divider"}
create_generated_clock -name tx_word_125 -source [get_pins pll/CLKOUT0] -divide_by 4 [get_pins word_buffer/O]
set source [get_pins clock_serdes/CLK]
set highClock [get_clocks -of_objects $source]
if {[llength $highClock]!=1 || abs([get_property PERIOD $highClock]-2)>0.001} {error "Expected actual CLK500"}
# 3c and the real DATA8 latency produce TXC at raw+8/raw+12. Both edges
# are positive CLK500 edges; waveform 0/4 modulo the actual 8ns word.
create_generated_clock -name phy_tx_capture -source $source -edges {1 5 9} [get_ports eth_txc]
lassign [get_property WAVEFORM [get_clocks phy_tx_capture]] rise fall
if {abs($rise)>0.001 || abs($fall-4)>0.001 || abs([get_property PERIOD [get_clocks phy_tx_capture]]-8)>0.001} {
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
foreach c {reference_buffer word_buffer clock_buffer} {
    set_property USER_CLOCK_ROOT $region [get_nets -of_objects [get_pins $c/O]]
}
# Only explicit release-chain async assertion pins, never functional reset
# removal/recovery endpoints or data registers.
set asyncPresets [get_pins -hier -filter {REF_PIN_NAME == PRE}]
if {![llength $asyncPresets]} {error "Missing reset-assertion endpoints"}
set_false_path -from [get_ports {cold_reset tx_reset_request}] -to $asyncPresets
set_false_path -to [get_ports locked]
set_input_delay -clock tx_word_125 -max 1.000 [get_ports {symbols_low[*] symbols_high[*]}]
set_input_delay -clock tx_word_125 -min 0.000 [get_ports {symbols_low[*] symbols_high[*]}]
set outputs [get_ports {eth_txd[*] eth_tx_ctl}]
if {[llength $outputs]!=5} {error "Require five actual data/control pads"}
foreach extra {{} {-clock_fall -add_delay}} {
    set_output_delay -clock phy_tx_capture -max 1.250 {*}$extra $outputs
    set_output_delay -clock phy_tx_capture -min -1.250 {*}$extra $outputs
}
proc data_pin {cell index} {
    set cell [get_cells -quiet $cell]
    if {[llength $cell]!=1} {error "Missing actual serializer cell: D$index"}
    set result {}
    foreach pin [get_pins -of_objects $cell] {
        set ref [get_property REF_PIN_NAME $pin]
        if {$ref eq [format {D[%d]} $index] || $ref eq "D$index"} {lappend result $pin}
    }
    if {[llength $result]!=1} {error "Missing actual serializer pin: $cell D$index"}
    return $result
}
proc audit_common_serial {output} {
    set proof [open $output w]
    set serializers [get_cells -hier -filter {REF_NAME == OSERDESE3}]
    if {[llength $serializers]!=6} {error "Require six actual DATA8 serializers"}
    set lanes [get_cells -hier -filter {REF_NAME == OSERDESE3 && NAME =~ lanes*}]
    if {[llength $lanes]!=5} {error "Require five actual data serializers"}
    set serialNet [get_nets -of_objects [get_pins clock_serdes/CLK]]
    set wordNet [get_nets -of_objects [get_pins clock_serdes/CLKDIV]]
    set resetNet [get_nets -of_objects [get_pins clock_serdes/RST]]
    if {[llength $serialNet]!=1 || [llength $wordNet]!=1 || [llength $resetNet]!=1} {error "Missing clock/reset net"}
    foreach c $serializers {
        if {[get_property DATA_WIDTH $c]!=8 || [get_property IS_CLK_INVERTED $c] ni {0 1'b0} ||
            [get_property IS_CLKDIV_INVERTED $c] ni {0 1'b0} || [get_property IS_RST_INVERTED $c] ni {0 1'b0} ||
            [get_property ODDR_MODE $c] ne "FALSE" || [get_property OSERDES_D_BYPASS $c] ne "FALSE"} {
            error "Not the proved DATA8 architecture: $c"
        }
        foreach {pin expected} [list CLK $serialNet CLKDIV $wordNet RST $resetNet] {
            if {[get_nets -of_objects [get_pins $c/$pin]] ne $expected} {error "Not same real $pin net: $c"}
        }
        puts $proof "$c SAME_REAL_CLK500_CLKDIV125_RST $serialNet $wordNet $resetNet"
    }
    foreach c $lanes {
        foreach indexes {{0 1 2 3} {4 5 6 7}} {
            set shared {}
            foreach index $indexes {
                set actual [get_nets -of_objects [data_pin $c $index]]
                if {[llength $actual]!=1} {error "Missing quadruple net: $c D$index"}
                if {$shared eq ""} {set shared $actual}
                if {$actual ne $shared} {error "Quadruple broken: $c D$index"}
            }
            puts $proof "$c D$indexes SAME_REAL_QUADRUPLE $shared"
        }
    }
    for {set n 0} {$n<8} {incr n} {
        set expected [expr {($n>=2 && $n<=5) ? "POWER" : "GROUND"}]
        if {[get_property TYPE [get_nets -of_objects [data_pin clock_serdes $n]]] ne $expected} {
            error "Actual TXC word is not independently proved 3c: D$n"
        }
    }
    puts $proof "TXC_WORD_3C_RAW_PHASE_0_4 DATA_CHANGES_PHASE_2_6"
    close $proof
    return $lanes
}
set lanes [audit_common_serial [file join $out post_synth_identity.txt]]
foreach c $lanes {
    set oq [get_pins -of_objects $c -filter {REF_PIN_NAME == OQ}]
    if {[llength $oq]!=1} {error "Missing actual data OQ"}
    # Four identical serial bits prove no falling CLK500 edge changes OQ.
    set_false_path -fall_from $highClock -through $oq -to $outputs
    # Setup remains the native 2ns relationship. The CLK500 positive edge
    # coincident with TXC cannot change data: D2=D0 and D6=D4. The NEXT real
    # transition is one 2ns source cycle later. This HOLD-ONLY START multiplier
    # selects that launch edge; it never touches registers or reset paths.
    # UG903 2025.1: positive -hold -start moves the launch edge forward.
    set_multicycle_path 1 -hold -start -rise_from $highClock -through $oq -to $outputs
}
opt_design
place_design
phys_opt_design -directive Explore
route_design
audit_common_serial [file join $out routed_identity.txt]
write_checkpoint [file join $out routed.dcp]
write_xdc [file join $out actual_constraints.xdc]
report_timing -to $outputs -delay_type min_max -max_paths 10 -input_pins -file [file join $out tx_io.rpt]
set releases [concat [get_pins {clock_serdes/RST word_buffer/CLR}] [get_pins -hier -filter {NAME =~ lanes* && REF_PIN_NAME == RST}]]
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
puts "NATIVE_COMMON_SERIAL_PAD_PROBE_COMPLETE lanes_pass=$qualified PHY_BUDGET_1.250NS NO_BOARD_PROOF_NO_BIT"
close_project
