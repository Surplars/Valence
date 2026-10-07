# Build only the changed ROM IP. CPU, DDR and GMAC clocks are not regenerated.
if {$argc != 1} {error "Expected PRIVATE_CANDIDATE_ROOT"}
set root [file normalize [lindex $argv 0]]
set out [file join $root ip-build]
if {[file exists $out]} {error "Preserve existing ROM build"}
set_param general.maxThreads 8
create_project board_ip $out -part xczu15eg-ffvb1156-2-i
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
    CONFIG.Load_Init_File true CONFIG.Coe_File [file join $root firmware bootrom.coe] \
    CONFIG.Use_RSTA_Pin false CONFIG.Use_RSTB_Pin false] [get_ips blk_mem_gen_0]
generate_target all [get_ips blk_mem_gen_0]
create_ip_run [get_ips blk_mem_gen_0]
launch_runs blk_mem_gen_0_synth_1 -jobs 1
wait_on_run blk_mem_gen_0_synth_1
if {[get_property PROGRESS [get_runs blk_mem_gen_0_synth_1]] ne "100%"} {error "ROM synthesis failed"}
set dest [file join $out board_ip.gen sources_1 ip blk_mem_gen_0 blk_mem_gen_0.dcp]
if {![file exists $dest]} {
    file copy [file join [get_property DIRECTORY [get_runs blk_mem_gen_0_synth_1]] blk_mem_gen_0.dcp] $dest
}
report_ip_status -file [file join $out ip_status.rpt]
puts "PASS_NETBOOT_ROM_IP_BUILT ROM_BYTES=131072"
close_project
