# Syntax/connectivity proof of the actual board wrapper ONLY. CPU and vendor
# IP interfaces are explicit blackboxes; NEVER treat this DCP as a full board.
if {$argc!=5} {error "Expected BOARD_SOURCE_DIR EXPORTED_RTL IP_GEN MIG_STUB FRESH_OUT"}
lassign $argv src rtl ipgen migStub out
if {[file exists $out]} {error "Preserve previous boundary proof"}
file mkdir $out
cd $out
set f [open [file join $rtl BoardSocTop.sv] r]; set full [read $f]; close $f
set begin [string first {module BoardSocTop(} $full]
set finish [string first "\n);" $full $begin]
if {$begin<0 || $finish<$begin} {error "Unknown exported BoardSocTop interface"}
set f [open BoardSocTop_interface_only.sv w]
puts $f {(* black_box *)}
puts $f [string range $full $begin [expr {$finish+2}]]
puts $f {endmodule}
close $f
set_param general.maxThreads 8
create_project -in_memory -part xczu15eg-ffvb1156-2-i
read_verilog -sv BoardSocTop_interface_only.sv
foreach name {clk_wiz_ddr clk_wiz_eth axi_clock_converter_ddr} {read_verilog [file join $ipgen $name ${name}_stub.v]}
read_verilog $migStub
foreach name {soc_top_gmac_ddr.sv native_rgmii.sv native_gmac_clocks.sv native_gmac_divided_clock.sv native_gmac_pll_pair.sv native_tx_common_delay.sv native_tx_reset_boundary.sv native_tx_word_reset_boundary.sv native_phy_board_control.sv native_phy_tx_init.sv} {
    read_verilog -sv [file join $src $name]
}
read_verilog -sv [file join $rtl MdioClause22.sv]
synth_design -top soc_top_gmac_ddr -mode out_of_context -flatten_hierarchy none
set f [open wrapper_structure.rpt w]
foreach c [get_cells -hier -filter {REF_NAME == MMCME4_ADV || REF_NAME == PLLE4_ADV || REF_NAME == BUFGCE || REF_NAME == BUFGCE_DIV || REF_NAME == FDPE || IS_BLACKBOX}] {
    puts $f "$c REF=[get_property REF_NAME $c]"
}
close $f
set mmcms [get_cells -hier -filter {REF_NAME == MMCME4_ADV}]
if {[llength $mmcms]!=1 || [llength [get_cells -hier -filter {REF_NAME == PLLE4_ADV}]]!=1 || [llength [get_cells -hier -filter {REF_NAME == BUFGCE_DIV}]]!=2} {
    error "Default board requires REF500 PLL, word DIV4, quarter DIV2 and independent RX MMCM"
}
if {[llength [get_cells -quiet -hier -filter {REF_NAME == native_phy_tx_init || REF_NAME == native_phy_board_control}]]} {error "Default board must not initialize PHY in hardware"}
set resetStages [get_cells -hier -filter {REF_NAME == FDPE && NAME =~ *tx_release*}]
if {[llength $resetStages]!=3} {error "Default board requires one shared three-stage word TX reset epoch"}
set padClock [get_nets -of_objects [get_pins centered_tx_clock.clock_dut/quarter_div/O]]
set rawClock [get_nets -of_objects [get_pins centered_tx_clock.clock_dut/raw_div/O]]
if {[llength $padClock]!=1 || $padClock eq $rawClock} {error "Default board must isolate the TX pad tree"}
set padConsumers [get_pins -leaf -of_objects $padClock -filter {DIRECTION == IN && (REF_PIN_NAME == C || REF_PIN_NAME == CLK)}]
set ddrConsumers {}
foreach p $padConsumers {
    set c [get_cells -of_objects $p]
    if {[get_property REF_NAME $c] in {ODDRE1 OSERDESE3} && [string match u_rgmii/* [get_property NAME $c]]} {
        lappend ddrConsumers $c
    } elseif {![string match u_rgmii/quarter_tx_boundary.* [get_property NAME $c]] || [get_property REF_NAME $c] ni {FDCE FDPE}} {
        error "Unexpected pad clock consumer: $p"
    }
}
if {[llength $ddrConsumers]!=6} {error "All six dedicated DDRs must share the quarter clock"}
source [file join $src native_quarter_clock_constraints.tcl]
create_clock -name quarter_structure_proxy -period 4.0 [get_pins centered_tx_clock.clock_dut/quarter_div/O]
valence_quarter_tx_audit u_rgmii
puts "PAD_CLOCK_SIX_DDR_CONSUMERS_AND_LOCAL_PHASE_PAYLOAD $padConsumers"
write_checkpoint interface_only.dcp
puts "PASS_NATIVE_BOARD_WRAPPER_INTERFACE_ONLY SOFTWARE_PHY_DEFAULT_NO_CPU_OR_IP_IMPLEMENTATION"
close_design
