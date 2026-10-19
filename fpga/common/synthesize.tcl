source [file join $valence(root) fpga common producer_common.tcl]
create_project common_board [file join $valence(out) project] -part $valence(part)
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
# import_ip copies the actual user-selected XCI into this run's isolated project.
import_ip -files $valence(mig_xci)
set mig [get_ips -quiet ddr4_0]
if {[llength $mig] != 1} {error "Expected actual MIG named ddr4_0"}
set imported [file normalize [get_property IP_FILE $mig]]
if {[string first [string tolower [file normalize [file join $valence(out) project]]] [string tolower $imported]] != 0} {
    error "MIG import escaped the isolated project"
}
foreach {key expected} {
    CONFIG.C0.DDR4_InputClockPeriod 5000 CONFIG.C0.DDR4_TimePeriod 1000
    CONFIG.C0.DDR4_AxiDataWidth 64 CONFIG.C0.DDR4_DataWidth 32
    CONFIG.C0.DDR4_AxiAddressWidth 31 CONFIG.C0.DDR4_AxiIDWidth 4
    CONFIG.C0.DDR4_AxiSelection true CONFIG.C0.DDR4_MemoryPart MT40A512M16LY-075
} {
    if {[get_property $key $mig] ne $expected} {error "MIG contract mismatch: $key"}
}
create_ip -name clk_wiz -vendor xilinx.com -library ip -version 6.0 -module_name clk_wiz_common
set mhz [expr {$valence(hz_cpu)/1.0e6}]
set_property -dict [list CONFIG.PRIM_SOURCE No_buffer CONFIG.PRIM_IN_FREQ 250.000 \
    CONFIG.NUM_OUT_CLKS 2 CONFIG.CLKOUT1_REQUESTED_OUT_FREQ $mhz CONFIG.CLKOUT1_DRIVES BUFG \
    CONFIG.CLKOUT2_USED true CONFIG.CLKOUT2_REQUESTED_OUT_FREQ 50.000 CONFIG.CLKOUT2_DRIVES BUFG \
    CONFIG.USE_RESET true CONFIG.USE_LOCKED true CONFIG.USE_DYN_RECONFIG false] [get_ips clk_wiz_common]
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
    CONFIG.Load_Init_File true CONFIG.Coe_File $valence(rom_coe) \
    CONFIG.Use_RSTA_Pin false CONFIG.Use_RSTB_Pin false] [get_ips blk_mem_gen_0]
generate_target all [get_ips]
# Project-mode OOC IP runs. Every child process executes the same >=8 request;
# synthesis still has the documented effective maximum4. jobs1 serializes
# DISTINCT IP builds; it is not a worker-thread count or duplicate synthesis.
foreach ip [get_ips] {create_ip_run $ip}
set runs [get_runs -quiet -filter {IS_SYNTHESIS == 1 && NAME != synth_1}]
if {[llength $runs]<3} {error "Missing generated clock/ROM/MIG synthesis runs"}
set_property STEPS.SYNTH_DESIGN.TCL.PRE [file join $valence(root) fpga common ip_threads.tcl] $runs
launch_runs $runs -jobs 1
set ipEvidence {}
foreach run $runs {
    wait_on_runs $run
    set status [get_property STATUS [get_runs $run]]
    if {![string match {*synth_design Complete!*} $status]} {error "IP synthesis failed: $run $status"}
    set file [file join [get_property DIRECTORY [get_runs $run]] common-ip-threads.txt]
    if {![file isfile $file]} {error "IP child did not verify its own thread request: $run"}
    set f [open $file]; set evidence [string trim [read $f]]; close $f
    if {![string match "requested=$valence(threads) general_limit=* synth_design_effective_max=4 active_threads=UNMEASURED vivado=*" $evidence]} {error "Wrong IP thread evidence: $run"}
    lappend ipEvidence [format {"%s":{"status":%s,"threads":%s}} $run [common_json $status] [common_json $evidence]]
}
common_log ip-synthesis.json "\{[join $ipEvidence ,]\}"
foreach source [common_files rtl_filelist] {read_verilog -sv $source}
foreach xdc $valence(constraints) {read_xdc $xdc}
common_design_step synth_design -top $valence(top) -part $valence(part) -flatten_hierarchy none
# Actual mapped hierarchy checks and bounded crossings precede checkpoint export.
source $valence(post_synth_constraints)
write_checkpoint synthesized.dcp
report_utilization -file utilization.rpt
common_receipt
close_project
