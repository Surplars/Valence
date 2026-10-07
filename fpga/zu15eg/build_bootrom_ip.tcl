# Build only an isolated copy of the existing 128 KiB ROM IP.
set out {D:/TOOLS/projects/vivadoProjects/ZU15EG/src/board-ddr50/bootrom-v01-noprompt}
file mkdir $out
set_param general.maxThreads 8
create_project bootrom_update [file join $out ip-build] -part xczu15eg-ffvb1156-2-i
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
    CONFIG.Load_Init_File true CONFIG.Coe_File [file join $out bootrom.coe] \
    CONFIG.Use_RSTA_Pin false CONFIG.Use_RSTB_Pin false] [get_ips blk_mem_gen_0]
generate_target all [get_ips blk_mem_gen_0]
synth_ip [get_ips blk_mem_gen_0]
puts "ROM_UPDATE: isolated ROM IP synthesis complete"
close_project
