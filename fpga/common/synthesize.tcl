source [file join $valence(root) fpga common producer_common.tcl]
if {![info exists valence(resume_raw)] || !$valence(resume_raw)} {
if {![info exists valence(resume_ooc)] || !$valence(resume_ooc)} {
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
# Never import/reuse the frozen CPU300 clock DCP for the low-clock candidate.
# A static third output separates selected fabric50/250 from fixed UI/time/debug250.
if {$valence(clock_profile) in {boot50-static performance300-static}} {
    set_property -dict [list CONFIG.NUM_OUT_CLKS 3 CONFIG.CLKOUT3_USED true \
        CONFIG.CLKOUT3_REQUESTED_OUT_FREQ [expr {$valence(hz_fabric)/1.0e6}] CONFIG.CLKOUT3_DRIVES BUFG] [get_ips clk_wiz_common]
    set_property verilog_define {VALENCE_INDEPENDENT_FIXED_DOMAINS} [current_fileset]
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
} else {
    if {![info exists valence(diagnosticOnly)] || $valence(diagnosticOnly)!=1} {error "OOC resume is diagnostic-only"}
    open_project [file join $valence(out) project common_board.xpr]
    if {[get_property PART [current_project]] ne $valence(part)} {error "Resume project part differs"}
    set runs [get_runs -quiet -filter {IS_SYNTHESIS == 1 && NAME != synth_1}]
    if {[lsort $runs] ne [lsort {blk_mem_gen_0_synth_1 clk_wiz_common_synth_1 ddr4_0_synth_1}]} {error "Unexpected resume OOC run set"}
}
set ipEvidence {}
foreach run $runs {
    wait_on_runs $run
    set status [get_property STATUS [get_runs $run]]
    if {![string match {*synth_design Complete!*} $status]} {error "IP synthesis failed: $run $status"}
    if {[info exists valence(resume_ooc)] && $valence(resume_ooc)} {
        set expectedDir [file normalize [file join $valence(out) project common_board.runs $run]]
        if {[file normalize [get_property DIRECTORY [get_runs $run]]] ne $expectedDir} {error "Resume OOC run directory differs: $run"}
        if {[get_property NEEDS_REFRESH [get_runs $run]] ni {0 false FALSE}} {error "Resume OOC run needs refresh: $run"}
    }
    set file [file join [get_property DIRECTORY [get_runs $run]] common-ip-threads.txt]
    if {![file isfile $file]} {error "IP child did not verify its own thread request: $run"}
    set f [open $file]; set evidence [string trim [read $f]]; close $f
    if {![string match "requested=$valence(threads) general_limit=* synth_design_effective_max=4 active_threads=UNMEASURED vivado=*" $evidence]} {error "Wrong IP thread evidence: $run"}
    lappend ipEvidence [format {"%s":{"status":%s,"threads":%s}} $run [common_json $status] [common_json $evidence]]
}
if {![info exists valence(resume_ooc)] || !$valence(resume_ooc)} {common_log ip-synthesis.json "\{[join $ipEvidence ,]\}"}
# Project-mode macros belong to sources_1, not per-file read_verilog -define.
set defines [get_property verilog_define [current_fileset]]
set independent [expr {$valence(clock_profile) in {boot50-static performance300-static}}]
if {$independent != ([lsearch -exact $defines VALENCE_INDEPENDENT_FIXED_DOMAINS]>=0)} {error "Independent-domain fileset macro missing or unexpected"}
foreach source [common_files rtl_filelist] {
    read_verilog -sv $source
}
foreach xdc $valence(constraints) {read_xdc $xdc}
common_design_step synth_design -top $valence(top) -part $valence(part) -flatten_hierarchy none
# Preserve expensive synthesis BEFORE any clock/CDC/media post-check can fail.
write_checkpoint raw-synthesized-unqualified.dcp
if {[info exists valence(recovery_tools)]} {
    puts [exec $valence(python) -E [file join $valence(recovery_tools) resume_diagnostic.py] $valence(root) seal-raw]
}
} else {
    open_checkpoint raw-synthesized-unqualified.dcp
    # Original completed synthesis thread evidence is retained on post-only retry.
    common_record synth_design {synth_design RECOVERED_RAW_CHECKPOINT} unsupported 4 synth_design-threads.txt "Recovered hash-bound unqualified synthesis; no new synthesis"
}
# Verify actual elaborated generated clock objects, never just requested CONFIG.
set clockOutputs [list clk_out1 $valence(hz_cpu) clk_out2 $valence(hz_aon)]
if {$valence(clock_profile) in {boot50-static performance300-static}} {
    lappend clockOutputs clk_out3 $valence(hz_fabric)
}
set clockEvidence {}
foreach {output expectedHz} $clockOutputs {
    set pin [get_pins -quiet u_clk_wiz/$output]
    if {[llength $pin] != 1} {error "Missing actual Clock Wizard output $output"}
    set clocks [get_clocks -quiet -of_objects $pin]
    if {[llength $clocks] != 1} {error "Missing/ambiguous generated output clock $output"}
    if {[get_property IS_GENERATED $clocks] ni {1 true TRUE}} {error "Clock Wizard output is not a generated clock: $output"}
    set period [get_property PERIOD $clocks]
    if {![string is double -strict $period] || $period <= 0 || abs($period-1.0e9/$expectedHz)>0.002} {
        error "Generated Clock Wizard frequency differs: $output period=$period expected_hz=$expectedHz"
    }
    lappend clockEvidence "$output clock=[get_property NAME $clocks] actual_period_ns=$period expected_hz=$expectedHz master=[get_property MASTER_CLOCK $clocks] source_pins=[get_property SOURCE_PINS $clocks]"
}
common_log clock-output-checks.txt [join $clockEvidence \n]
report_clocks -file generated-clocks.rpt
# Actual mapped hierarchy checks and bounded crossings precede checkpoint export.
source $valence(post_synth_constraints)
write_checkpoint synthesized.dcp
report_utilization -file utilization.rpt
common_receipt
close_project
