# Prepare only clock, initialized ROM, and UART partitions for the 45/50 MHz FIFO UART A/B.
# Args: RTL_DIR COE OUTPUT_DIR CPU_HZ
if {$argc != 4} {error "Expected RTL_DIR COE OUTPUT_DIR CPU_HZ"}
lassign $argv rtl_dir coe out cpu_hz
if {$cpu_hz ni {45000000 50000000}} {error "This release supports 45/50 MHz only"}
set clock_mhz [format %.3f [expr {$cpu_hz/1000000.0}]]
foreach var {rtl_dir coe out} {set $var [file normalize [set $var]]}
file mkdir $out
set_param general.maxThreads 8
set gen_dir [file join $out ip-build reclock_ip.gen sources_1 ip]
if {![file exists [file join $gen_dir blk_mem_gen_0 blk_mem_gen_0.dcp]] ||
    ![file exists [file join $gen_dir clk_wiz_ddr clk_wiz_ddr.dcp]]} {
set project_file [file join $out ip-build reclock_ip.xpr]
if {[file exists $project_file]} {open_project $project_file} else {
    create_project reclock_ip [file join $out ip-build] -part xczu15eg-ffvb1156-2-i
}
if {![llength [get_ips -quiet clk_wiz_ddr]]} {
    create_ip -name clk_wiz -vendor xilinx.com -library ip -version 6.0 -module_name clk_wiz_ddr
}
set_property -dict [list CONFIG.PRIM_SOURCE No_buffer CONFIG.PRIM_IN_FREQ 250.000 \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ $clock_mhz CONFIG.USE_RESET true CONFIG.USE_LOCKED true] [get_ips clk_wiz_ddr]
if {![llength [get_ips -quiet blk_mem_gen_0]]} {
    create_ip -name blk_mem_gen -vendor xilinx.com -library ip -version 8.4 -module_name blk_mem_gen_0
}
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
generate_target all [get_ips {clk_wiz_ddr blk_mem_gen_0}]
foreach name {clk_wiz_ddr blk_mem_gen_0} {
    if {![llength [get_runs -quiet ${name}_synth_1]]} {create_ip_run [get_ips $name]}
}
launch_runs {clk_wiz_ddr_synth_1 blk_mem_gen_0_synth_1} -jobs 2
foreach run {clk_wiz_ddr_synth_1 blk_mem_gen_0_synth_1} {
    wait_on_run $run
    if {[get_property PROGRESS [get_runs $run]] ne "100%"} {error "IP synthesis failed: $run"}
    set name [string range $run 0 end-8]
    set destination [file join $gen_dir $name ${name}.dcp]
    if {![file exists $destination]} {
        set checkpoint [file join [get_property DIRECTORY [get_runs $run]] ${name}.dcp]
        if {![file exists $checkpoint]} {error "Missing completed IP checkpoint: $checkpoint"}
        file copy $checkpoint $destination
    }
}
set gen_dir [file join $out ip-build reclock_ip.gen sources_1 ip]
puts "RECLOCK: CLOCK_DCP=[file join $gen_dir clk_wiz_ddr clk_wiz_ddr.dcp]"
puts "RECLOCK: ROM_DCP=[file join $gen_dir blk_mem_gen_0 blk_mem_gen_0.dcp]"
close_project
}
create_project -in_memory -part xczu15eg-ffvb1156-2-i
read_verilog -sv [list [file join $rtl_dir UartConsole.sv] [file join $rtl_dir Queue2_RegisterResponse.sv] [file join $rtl_dir ram_2x65.sv]]
synth_design -top UartConsole -mode out_of_context -part xczu15eg-ffvb1156-2-i -flatten_hierarchy none
set uart_sync [get_cells -quiet {rxMeta_reg rxSync_reg}]
if {[llength $uart_sync] != 2} {error "UART synchronizer mismatch"}
set_property ASYNC_REG TRUE $uart_sync
write_checkpoint [file join $out uart.dcp]
write_edif [file join $out uart.edf]
close_project
# This routed baseline has one implementation-added reset input at the UART
# boundary. Preserve that exact port contract; it is not an architectural port.
set stream [open [file join $rtl_dir UartConsole.sv] r]
set source [read $stream]
close $stream
set source [string map {module\ UartConsole( module\ UartConsoleRouted(} $source]
set pos [string first ");" $source]
set source [string replace $source $pos [expr {$pos + 1}] ", input wire \\reset_pipe\[2\]_bufg_place \n);"]
set wrapper [file join $out UartConsoleRouted.sv]
set stream [open $wrapper w]
puts $stream $source
close $stream
create_project -in_memory -part xczu15eg-ffvb1156-2-i
read_verilog -sv [list $wrapper [file join $rtl_dir Queue2_RegisterResponse.sv] [file join $rtl_dir ram_2x65.sv]]
synth_design -top UartConsoleRouted -mode out_of_context -part xczu15eg-ffvb1156-2-i -flatten_hierarchy none
if {[llength [get_ports]] != 215} {error "Routed UART boundary changed"}
set_property ASYNC_REG TRUE [get_cells {rxMeta_reg rxSync_reg}]
write_checkpoint [file join $out uart_routed.dcp]
write_edif [file join $out uart_routed.edf]
report_utilization -file [file join $out uart_utilization.rpt]
close_project
puts "RECLOCK: PARTITIONS COMPLETE"
