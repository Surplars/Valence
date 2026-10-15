if {$argc != 1} {error "usage: r3_synth.tcl FRESH_CANDIDATE_ROOT"}
set root [file normalize [lindex $argv 0]]
source [file join $root scripts runtime.tcl]
r3_load_config $root
set out [file join $root synthesis]
if {[file exists $out]} {error "Preserve prior synthesis evidence"}
file mkdir $out
cd $out
r3_apply_threads synthesis_begin
source [file join $root scripts r3_common.tcl]
if {[catch {
    create_project -in_memory -part [dict get $::r3_config part]
    set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
    set iproot [file join $root ip-build board_ip.srcs sources_1 ip]
    foreach name {blk_mem_gen_0 clk_wiz_ddr axi_clock_converter_ddr} {read_ip [file join $iproot $name $name.xci]}
    read_ip [file join $root mig ZU15EG.srcs sources_1 ip ddr4_0 ddr4_0.xci]
    foreach {key value} {CONFIG.C0.DDR4_InputClockPeriod 5000 CONFIG.C0.DDR4_TimePeriod 1000 CONFIG.C0.DDR4_AxiDataWidth 64 CONFIG.C0.DDR4_DataWidth 32 CONFIG.C0.DDR4_AxiAddressWidth 31 CONFIG.C0.DDR4_AxiIDWidth 4 CONFIG.C0.DDR4_AxiSelection true CONFIG.C0.DDR4_MemoryPart MT40A512M16LY-075} {
        if {[get_property $key [get_ips ddr4_0]] ne $value} {error "MIG mismatch $key"}
    }
    foreach {key value} {CONFIG.CLKOUT1_REQUESTED_OUT_FREQ 100.000 CONFIG.CLKOUT2_REQUESTED_OUT_FREQ 50.000 CONFIG.CLKOUT3_REQUESTED_OUT_FREQ 125.000} {
        if {abs([get_property $key [get_ips clk_wiz_ddr]]-$value)>0.001} {error "Clock mismatch $key"}
    }
    source [file join $root export board native-mac-mode.tcl]
    r3_configure_python $out
    puts "R3_EXACT_SYNTH core178 profile95 proof3 credits2 LSU4 CPU100 MAC_T1=1 MAC_SELECTED_HALF=1"
    valence_native_mac_synth_design -flatten_hierarchy none
    write_checkpoint post_synth_unconstrained.dcp
    report_utilization -hierarchical -file utilization.rpt
    report_ip_status -file ip_status.rpt
    r3_discover
    set fp [get_cells -quiet -hier -filter {REF_NAME == FloatingPointSystem}]
    if {[llength $fp]!=1} {error "Missing unique actual F/D unit"}
    r3_rom_dump rom-init.tsv
    set f [open stage-result.txt w];puts $f "SYNTH_COMPLETE_ROM_INIT_VERIFY_AND_CONSTRAINTS_REQUIRED NO_ROUTE_NO_BIT";close $f
    close_project
} why options]} {
    set f [open failure.txt w];puts $f $why;puts $f [dict get $options -errorinfo];close $f
    puts stderr "R3_SYNTH_FAILED $why"
    exit 1
}
exit 0
