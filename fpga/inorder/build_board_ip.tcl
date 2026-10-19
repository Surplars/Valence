# Real ZU15EG IP project. The original GUI/OOO project is never opened.
# CPU300 / raw UART50 / raw MAC125 / pad250 / IDELAY500 share one MMCM.
if {$argc != 2} {error "usage: build_board_ip.tcl FRESH_BOARD_ROOT VERIFIED_MIG_XCI"}
lassign $argv root mig_source
set root [file normalize $root]
set mig_source [file normalize $mig_source]
if {![file isfile $mig_source]} {error "Missing actual MIG XCI"}
if {[file exists [file join $root project]]} {error "Preserve previous board project"}
file mkdir [file join $root ip-source ddr4_0]
file copy $mig_source [file join $root ip-source ddr4_0 ddr4_0.xci]
set_param general.maxThreads 8
create_project i1_board [file join $root project] -part xczu15eg-ffvb1156-2-i
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
import_ip -files [file join $root ip-source ddr4_0 ddr4_0.xci]
set actual_mig [file normalize [get_property IP_FILE [get_ips ddr4_0]]]
if {[string first [string tolower [file join $root project]] [string tolower $actual_mig]] != 0} {
    error "Imported MIG must belong to this isolated project: $actual_mig"
}
foreach {key expected} {
    CONFIG.C0.DDR4_InputClockPeriod 5000 CONFIG.C0.DDR4_TimePeriod 1000
    CONFIG.C0.DDR4_AxiDataWidth 64 CONFIG.C0.DDR4_DataWidth 32
    CONFIG.C0.DDR4_AxiAddressWidth 31 CONFIG.C0.DDR4_AxiIDWidth 4
    CONFIG.C0.DDR4_AxiSelection true CONFIG.C0.DDR4_MemoryPart MT40A512M16LY-075
} {
    if {[get_property $key [get_ips ddr4_0]] ne $expected} {
        error "MIG contract mismatch: $key"
    }
}
create_ip -name clk_wiz -vendor xilinx.com -library ip -version 6.0 -module_name clk_wiz_i1
set_property -dict [list CONFIG.PRIM_SOURCE No_buffer CONFIG.PRIM_IN_FREQ 250.000 \
    CONFIG.NUM_OUT_CLKS 5 CONFIG.CLKOUT1_REQUESTED_OUT_FREQ 300.000 \
    CONFIG.CLKOUT1_DRIVES BUFG CONFIG.CLKOUT2_USED true \
    CONFIG.CLKOUT2_REQUESTED_OUT_FREQ 50.000 CONFIG.CLKOUT2_DRIVES No_buffer \
    CONFIG.CLKOUT3_USED true CONFIG.CLKOUT3_REQUESTED_OUT_FREQ 125.000 \
    CONFIG.CLKOUT3_DRIVES No_buffer CONFIG.CLKOUT4_USED true \
    CONFIG.CLKOUT4_REQUESTED_OUT_FREQ 250.000 CONFIG.CLKOUT4_DRIVES BUFG \
    CONFIG.CLKOUT5_USED true CONFIG.CLKOUT5_REQUESTED_OUT_FREQ 500.000 \
    CONFIG.CLKOUT5_DRIVES BUFG CONFIG.USE_RESET true CONFIG.USE_LOCKED true \
    CONFIG.USE_DYN_RECONFIG false] [get_ips clk_wiz_i1]
create_ip -name axi_clock_converter -vendor xilinx.com -library ip -version 2.1 \
    -module_name axi_clock_converter_i1
set_property -dict [list CONFIG.PROTOCOL AXI4 CONFIG.ADDR_WIDTH 32 CONFIG.DATA_WIDTH 64 \
    CONFIG.ID_WIDTH 4 CONFIG.ACLK_ASYNC 1] [get_ips axi_clock_converter_i1]
generate_target all [get_ips]
set runs {}
foreach name {ddr4_0 clk_wiz_i1 axi_clock_converter_i1} {
    create_ip_run [get_ips $name]
    lappend runs [format "%s_synth_1" $name]
}
launch_runs $runs -jobs 2
foreach run $runs {
    wait_on_run $run
    if {[get_property PROGRESS [get_runs $run]] ne "100%"} {
        error "Actual board IP synthesis did not finish: $run"
    }
}
report_ip_status -file [file join $root ip-status.rpt]
puts "I1_REAL_BOARD_IP_COMPLETE MIG2GiB_AXI64_UI250 CPU300_RAW50_RAW125_PAD250_REF500"
close_project
