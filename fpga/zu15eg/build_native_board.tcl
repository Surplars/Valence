# Complete native-GMAC board, fixed clocks, real MIG/BMG/AXI CDC IP.
# Fresh root contains rtl/, board/, scripts/, firmware/ and ip-build/.
# Never opens/modifies the user's GUI project. Never releases a failed bit.
if {$argc < 2 || $argc > 5} {error "Expected CANDIDATE_ROOT VERIFIED_MIG_XCI OPTIONAL_ISA OPTIONAL_OWN_POST_SYNTH_DCP OPTIONAL_INCREMENTAL_ROUTED_REFERENCE"}
lassign $argv root mig isa resume reference
if {$resume eq "-"} {set resume ""}
if {$isa eq ""} {set isa rv64imac}
if {$isa ni {rv64imac rv64imafc rv64gc}} {error "Unsupported board ISA: $isa"}
set root [file normalize $root]
set mig [file normalize $mig]
if {$reference ne ""} {
    set reference [file normalize $reference]
    if {![file isfile $reference]} {error "Missing incremental routed reference"}
}
set out [file join $root implementation]
if {$resume ne ""} {
    set resume [file normalize $resume]
    if {$resume ne [file normalize [file join $root implementation post_synth_unconstrained.dcp]] || ![file exists $resume]} {
        error "Resume only this candidate's own completed synthesis, never an integer or external CPU DCP"
    }
    set out [file join $root implementation-resume-r2]
}
if {[file exists $out]} {error "Preserve previous implementation evidence; use fresh root"}
file mkdir $out
cd $out
set_param general.maxThreads 8
if {$resume eq ""} {
create_project -in_memory -part xczu15eg-ffvb1156-2-i
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
set iproot [file join $root ip-build board_ip.srcs sources_1 ip]
foreach name {blk_mem_gen_0 clk_wiz_ddr axi_clock_converter_ddr} {
    read_ip [file join $iproot $name $name.xci]
}
read_ip $mig
foreach {property value} {
    CONFIG.C0.DDR4_InputClockPeriod 5000 CONFIG.C0.DDR4_TimePeriod 1000
    CONFIG.C0.DDR4_AxiDataWidth 64 CONFIG.C0.DDR4_DataWidth 32
    CONFIG.C0.DDR4_AxiAddressWidth 31 CONFIG.C0.DDR4_AxiIDWidth 4
    CONFIG.C0.DDR4_AxiSelection true CONFIG.C0.DDR4_MemoryPart MT40A512M16LY-075
} {
    if {[get_property $property [get_ips ddr4_0]] ne $value} {error "MIG contract mismatch: $property"}
}
foreach {property value} {
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ 100.000
    CONFIG.CLKOUT2_REQUESTED_OUT_FREQ 50.000
    CONFIG.CLKOUT3_REQUESTED_OUT_FREQ 125.000
} {
    if {abs([get_property $property [get_ips clk_wiz_ddr]] - $value)>0.001} {error "Clock contract mismatch: $property"}
}
read_verilog -sv [glob [file join $root rtl *.sv]]
# The native wrapper instantiates its explicit PLL/DIV resources, not the
# legacy clk_wiz_eth IP. Validate the ACTUAL endpoint clocks after assembly.
foreach name {soc_top_gmac_ddr.sv native_rgmii.sv native_gmac_clocks.sv native_gmac_divided_clock.sv native_gmac_pll_pair.sv native_tx_common_delay.sv native_tx_reset_boundary.sv native_tx_word_reset_boundary.sv native_phy_board_control.sv native_phy_tx_init.sv} {
    read_verilog -sv [file join $root board $name]
}
# Synthesis uses vendor-generated actual clock definitions. Board/endpoint
# constraints are applied to the assembled netlist, with strict cardinalities.
synth_design -top soc_top_gmac_ddr -flatten_hierarchy none
set fpSystems [get_cells -quiet -hier -filter {REF_NAME == FloatingPointSystem}]
set expectedFp [expr {$isa eq "rv64imac" ? 0 : 1}]
if {[llength $fpSystems] != $expectedFp} {error "Actual synthesized FPU disagrees with ISA $isa"}
write_checkpoint post_synth_unconstrained.dcp
# Reopen once to expand LUTRAM leaves before CDC RAM startpoint tracing.
close_project
open_checkpoint post_synth_unconstrained.dcp
} else {
    open_checkpoint $resume
    set fpSystems [get_cells -quiet -hier -filter {REF_NAME == FloatingPointSystem}]
    set expectedFp [expr {$isa eq "rv64imac" ? 0 : 1}]
    if {[llength $fpSystems] != $expectedFp} {error "Resume FPU disagrees with ISA $isa"}
}
read_xdc [file join $root board board_ddr.xdc]
read_xdc [file join $root board pl_ddr4_pins.xdc]
read_xdc [file join $root board native_gmac_pins.xdc]
source [file join $root scripts native_board_constraints.tcl]
valence_native_board_constraints
set functional [get_cells -quiet -hier -filter {IS_BLACKBOX && NAME != dbg_hub}]
if {[llength $functional]} {error "Functional black boxes: $functional"}
foreach {pin hz} {u_soc/clock 100000000 u_soc/io_alwaysOnClock 50000000 u_soc/nativeBank/uart/uart/clock 50000000 u_soc/io_nativeGmac_rawTxClock 125000000 u_rgmii/delay_clock 500000000} {
    set clk [get_clocks -of_objects [get_pins $pin]]
    if {[llength $clk]!=1 || abs([get_property PERIOD $clk] - 1.0e9/$hz)>0.001} {error "Missing real clock on $pin"}
}
set missing {}
foreach port [get_ports] {
    if {[get_property PACKAGE_PIN $port] eq ""} {lappend missing $port}
    if {[get_property IOSTANDARD $port] in {"" DEFAULT}} {lappend missing $port}
}
if {[llength $missing]} {error "Unconstrained board I/O: $missing"}
report_io -file io.rpt
report_clocks -file clocks.rpt
report_utilization -hierarchical -file post_synth_utilization.rpt
report_cdc -details -file post_synth_cdc.rpt
write_checkpoint assembled.dcp
set_param general.maxThreads 1
opt_design
set_param general.maxThreads 8
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Unresolved black boxes after opt"}
# MIG PHY stitching restores source constraints. Repeat the SAME scoped,
# structurally audited CDC/reset contracts on the now-expanded complete design.
valence_native_board_constraints
write_checkpoint optimized.dcp
if {$reference ne ""} {
    # Placement/routing hints only. All current RTL and ROM have been newly
    # synthesized above; no donor CPU logic or timing exceptions are imported.
    read_checkpoint -incremental $reference
    report_incremental_reuse -file incremental_reuse.rpt
    puts "NATIVE_BOARD_INCREMENTAL_REFERENCE $reference"
}
place_design -directive Explore
phys_opt_design -directive Explore
write_checkpoint placed.dcp
report_timing_summary -delay_type min_max -file placed_timing.rpt
route_design -directive Explore -tns_cleanup
phys_opt_design -directive Explore
set quarter [get_cells -quiet centered_tx_clock.clock_dut/quarter_div]
# Always preserve the actual completed route before post-route audits/reports.
write_checkpoint routed.dcp
if {[llength $quarter]} {
    set pads [valence_quarter_tx_audit u_rgmii]
    set audit [open quarter_tx_identity.txt w]
    puts $audit "PASS_NATIVE_QUARTER_TX_TOPOLOGY ACTUAL_VALIDATED_DATA_PADS=$pads"
    close $audit
}
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_timing -delay_type max -max_paths 40 -input_pins -file setup_paths.rpt
report_timing -delay_type min -max_paths 30 -input_pins -file hold_paths.rpt
report_utilization -hierarchical -file utilization.rpt
report_clock_interaction -file clock_interaction.rpt
report_cdc -details -file cdc.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_route_status -file route_status.rpt
report_exceptions -coverage -file exception_coverage.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
report_clocks -file routed_clocks.rpt
set cpuClock [get_clocks -of_objects [get_pins u_soc/clock]]
report_timing -from $cpuClock -to $cpuClock -delay_type min_max -max_paths 20 -input_pins -file cpu_paths.rpt
# Query every physical lane independently: a report of only the globally
# worst lanes can hide an excluded endpoint or its missing hold check.
foreach direction {tx rx} {
    set report [file join $out ${direction}_io.rpt]
    set f [open $report w]; close $f
    set endpoints [get_ports [list eth_${direction}d\[*\] eth_${direction}_ctl]]
    if {[llength $endpoints]!=5} {error "Missing physical $direction lanes"}
    foreach port $endpoints {
        foreach delay {max min} {
            if {$direction eq "tx"} {
                set path [get_timing_paths -to $port -delay_type $delay -max_paths 1]
                if {[llength $path]!=1} {error "Untimed $direction/$delay endpoint: $port"}
                if {[llength $quarter]} {
                    set required [expr {$delay eq "max" ? 2.0 : -2.0}]
                    if {abs([get_property REQUIREMENT $path]-$required)>0.001} {error "Unproved actual TX edge relationship at $port"}
                }
                report_timing -to $port -delay_type $delay -max_paths 1 -input_pins -append -file $report
            } else {
                set path [get_timing_paths -from $port -delay_type $delay -max_paths 1]
                if {[llength $path]!=1} {error "Untimed $direction/$delay startpoint: $port"}
                report_timing -from $port -delay_type $delay -max_paths 1 -input_pins -append -file $report
            }
            if {[get_property SLACK $path] in {inf -inf}} {error "Invalid infinite $direction/$delay slack: $port"}
        }
    }
}
set clearNames {raw_div pad_div forward_div}
if {[llength $quarter]} {set clearNames {raw_div quarter_div}}
set clearPins {}
foreach name $clearNames {lappend clearPins [get_pins centered_tx_clock.clock_dut/$name/CLR]}
report_timing -to $clearPins -delay_type min_max -max_paths 12 -input_pins -file divider_clear.rpt
write_xdc -type timing routed_constraints.xdc
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
set wns [get_property SLACK $setup]
set whs [get_property SLACK $hold]
puts "NATIVE_BOARD_RESULT ISA=$isa WNS=$wns WHS=$whs CPU100 UART460800 GMAC125"
# Reports/checkpoint always remain. Do not issue write_bitstream just because
# synthesis finished. A separate signed review checks unconstrained endpoints,
# reset/CDC/Gray/payload coverage, pulse width, routing and DRC before release.
set status [open stage-result.txt w]
puts $status "ISA=$isa CPU_HZ=100000000 UART_BAUD=460800 WNS=$wns WHS=$whs"
puts $status "STATUS=ROUTED_REQUIRES_SIGNOFF NO_BIT_GENERATED"
close $status
close_design
