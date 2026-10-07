# Isolated board IP build. Never opens or changes the user's GUI project.
# Args: COE OUTPUT_DIR CPU_HZ [native-gmac]
if {$argc != 3 && $argc != 4} {error "Expected COE OUTPUT_DIR CPU_HZ [native-gmac]"}
lassign $argv coe out cpu_hz mode
if {$mode ne "" && $mode ne "native-gmac"} {error "Unknown board clock topology"}
if {![string is integer -strict $cpu_hz] || $cpu_hz < 6000000 ||
    $cpu_hz > 200000000 || $cpu_hz % 1000000} {error "Expected whole MHz, 6..200 MHz"}
set coe [file normalize $coe]
set out [file normalize $out]
if {![file isfile $coe]} {error "Missing ROM initialization: $coe"}
if {[file exists [file join $out board_ip.xpr]]} {error "Use a fresh IP output directory"}
set_param general.maxThreads 8
create_project board_ip $out -part xczu15eg-ffvb1156-2-i
create_ip -name clk_wiz -vendor xilinx.com -library ip -version 6.0 -module_name clk_wiz_ddr
set_property -dict [list CONFIG.PRIM_SOURCE No_buffer CONFIG.PRIM_IN_FREQ 250.000 \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ [format %.3f [expr {$cpu_hz / 1.0e6}]] \
    CONFIG.USE_RESET true CONFIG.USE_LOCKED true CONFIG.USE_DYN_RECONFIG false] [get_ips clk_wiz_ddr]
if {$mode eq "native-gmac"} {
    if {$cpu_hz != 100000000} {error "Native managed wake budgets qualified for CPU100/AON50/TX125"}
    set_property -dict [list CONFIG.CLKOUT2_USED true CONFIG.CLKOUT2_REQUESTED_OUT_FREQ 50.000 \
        CONFIG.CLKOUT3_USED true CONFIG.CLKOUT3_REQUESTED_OUT_FREQ 125.000 \
        CONFIG.NUM_OUT_CLKS 3] [get_ips clk_wiz_ddr]
    # Separate local Ethernet MMCM: preserve CPU/AON topology, generate a
    # legal UltraScale+ IDELAYCTRL reference (DS925 requires 300..800MHz).
    create_ip -name clk_wiz -vendor xilinx.com -library ip -version 6.0 -module_name clk_wiz_eth
    set_property -dict [list CONFIG.PRIM_SOURCE No_buffer CONFIG.PRIM_IN_FREQ 250.000 \
        CONFIG.CLKOUT1_REQUESTED_OUT_FREQ 125.000 CONFIG.CLKOUT2_USED true \
        CONFIG.CLKOUT2_REQUESTED_OUT_FREQ 500.000 CONFIG.NUM_OUT_CLKS 2 \
        CONFIG.USE_RESET true CONFIG.USE_LOCKED true CONFIG.USE_DYN_RECONFIG false] [get_ips clk_wiz_eth]
}
create_ip -name blk_mem_gen -vendor xilinx.com -library ip -version 8.4 -module_name blk_mem_gen_0
set_property -dict [list \
    CONFIG.Interface_Type Native CONFIG.Memory_Type Dual_Port_ROM \
    CONFIG.Enable_32bit_Address false CONFIG.EN_SLEEP_PIN false \
    CONFIG.Assume_Synchronous_Clk true CONFIG.Write_Width_A 32 \
    CONFIG.Write_Depth_A 32768 CONFIG.Enable_A Use_ENA_Pin \
    CONFIG.Write_Width_B 32 CONFIG.Read_Width_B 32 CONFIG.Enable_B Use_ENB_Pin \
    CONFIG.Register_PortA_Output_of_Memory_Primitives false \
    CONFIG.Register_PortA_Output_of_Memory_Core false \
    CONFIG.Register_PortB_Output_of_Memory_Primitives false \
    CONFIG.Register_PortB_Output_of_Memory_Core false \
    CONFIG.Load_Init_File true CONFIG.Coe_File $coe \
    CONFIG.Use_RSTA_Pin false CONFIG.Use_RSTB_Pin false] [get_ips blk_mem_gen_0]
create_ip -name axi_clock_converter -vendor xilinx.com -library ip -version 2.1 -module_name axi_clock_converter_ddr
set_property -dict [list CONFIG.PROTOCOL AXI4 CONFIG.ADDR_WIDTH 32 CONFIG.DATA_WIDTH 64 \
    CONFIG.ID_WIDTH 4 CONFIG.ACLK_ASYNC 1] [get_ips axi_clock_converter_ddr]
generate_target all [get_ips]
set names {clk_wiz_ddr blk_mem_gen_0 axi_clock_converter_ddr}
if {$mode eq "native-gmac"} {lappend names clk_wiz_eth}
set runs {}
foreach name $names {create_ip_run [get_ips $name]; lappend runs ${name}_synth_1}
launch_runs $runs -jobs 3
foreach name $names {
    wait_on_run ${name}_synth_1
    if {[get_property PROGRESS [get_runs ${name}_synth_1]] ne "100%"} {error "IP synthesis failed: $name"}
    set dest [file join $out board_ip.gen sources_1 ip $name ${name}.dcp]
    if {![file exists $dest]} {
        file copy [file join [get_property DIRECTORY [get_runs ${name}_synth_1]] ${name}.dcp] $dest
    }
}
report_ip_status -file [file join $out ip_status.rpt]
puts "BOARD_IP: CPU_HZ=$cpu_hz ROM_BYTES=131072 AXI_ASYNC=1 COMPLETE"
close_project
