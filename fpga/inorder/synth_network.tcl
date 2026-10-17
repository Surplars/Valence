# One32KiB/TL-C/RV64GC/tri-speed synthesis. Not a board bit or timing closure.
if {$argc != 2} { error "usage: synth_network.tcl RTL_PACKAGE FRESH_REPORT_ROOT" }
set rtl_root [file normalize [lindex $argv 0]]
set report_root [file normalize [lindex $argv 1]]
if {[file exists $report_root]} { error "preserve previous synthesis evidence" }
file mkdir $report_root
cd $rtl_root
set_param general.maxThreads 8
create_project -in_memory -part xczu15eg-ffvb1156-2-i
set files [lsort [glob -directory $rtl_root *.sv]]
read_verilog -sv $files
read_xdc [file join $rtl_root network_ooc.xdc]
synth_design -top I1NetworkFpgaShell -part xczu15eg-ffvb1156-2-i -mode out_of_context \
    -flatten_hierarchy rebuilt -directive Default -verilog_define ENABLE_INITIAL_MEM_
# Keep a usable checkpoint BEFORE constraint or resource gates.
write_checkpoint [file join $report_root synthesized.dcp]
report_utilization -file [file join $report_root utilization.rpt]
report_utilization -hierarchical -file [file join $report_root hierarchical_utilization.rpt]
set native_cuts [get_cells -quiet -hierarchical -filter {REF_NAME =~ I1RegisteredDataBoundary*}]
set manifest_file [open [file join $rtl_root manifest.json]]
set manifest_text [read $manifest_file]
close $manifest_file
if {![regexp {"native_timing_boundary_count": ([0-9]+)} $manifest_text _ expected_native] ||
    $expected_native ni {6 7}} { error "explicit tested boundary count missing" }
if {[llength $native_cuts] != $expected_native} {
    error "expected $expected_native actual native request/reply timing boundaries, got [llength $native_cuts]"
}
puts "I1_NATIVE_BOUNDARIES_CONFIRMED $native_cuts"
set line_cuts [get_cells -quiet -hierarchical -filter {REF_NAME =~ I1RegisteredLineReadRequestBoundary*}]
if {![regexp {"line_read_request_boundaries": ([0-9]+)} $manifest_text _ expected_line] ||
    $expected_line ni {0 1} || [llength $line_cuts] != $expected_line} {
    error "whole-line request-only boundary differs from tested manifest"
}
puts "I1_LINE_REQUEST_BOUNDARIES_CONFIRMED $line_cuts"
set compact_writer [get_cells -quiet -hierarchical -filter {REF_NAME =~ TileLinkSerializedLineWriteEngine*}]
if {[llength $compact_writer] != 1} { error "one real serialized Home writer required" }
puts "I1_SERIALIZED_HOME_WRITER_CONFIRMED $compact_writer"
source [file join $rtl_root network_clock_balance.tcl]
i1_balanced_clock_roots [file join $report_root balanced_clock_roots.txt]
report_timing -from [get_clocks orbital_i1_cpu] -to [get_clocks orbital_i1_cpu] \
    -delay_type max -max_paths 30 -nworst 1 -file [file join $report_root setup_cpu_raw.rpt]
set primitive [get_cells -quiet -hierarchical -filter {REF_NAME == BSCANE2}]
if {[llength $primitive] != 1} { error "one USER2 instance required" }
set primitive [get_property NAME $primitive]
if {![regsub {([/.])user_scan$} $primitive {\1transport} engine]} { error "BSCAN sibling hierarchy changed" }
source [file join $rtl_root bscan_timing_i1.tcl]
valence_apply_bscan_timing $primitive $engine orbital_i1_cpu zu15eg-user2-tck50-halfcycle-i1-v2
source [file join $rtl_root network_cdc.tcl]
set cdc_counts [i1_network_cdc [get_property PERIOD [get_clocks orbital_i1_cpu]]]
write_checkpoint [file join $report_root synthesized_constrained.dcp]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $report_root timing_synth.rpt]
report_timing -from [all_registers] -to [all_registers] -delay_type max -max_paths 40 -nworst 1 \
    -file [file join $report_root setup_internal_synth.rpt]
report_timing -from [get_clocks orbital_i1_cpu] -to [get_clocks orbital_i1_cpu] \
    -delay_type max -max_paths 30 -nworst 1 -file [file join $report_root setup_cpu_synth.rpt]
report_timing -delay_type min -max_paths 20 -nworst 1 -file [file join $report_root hold_synth.rpt]
report_timing -from [get_clocks orbital_i1_cpu] -to [get_clocks orbital_i1_cpu] \
    -delay_type min -max_paths 10 -nworst 1 -file [file join $report_root hold_cpu_synth.rpt]
report_clocks -file [file join $report_root clocks.rpt]
report_clock_interaction -file [file join $report_root clock_interaction.rpt]
report_cdc -details -file [file join $report_root cdc.rpt]
check_timing -verbose -file [file join $report_root check_timing.rpt]
set units {core soc/core/core/* fpu *I1FloatingPointSharedArithmetic* cache *cache/coherent/cache/*
    directory soc/fabric/home/* fabric soc/fabric/* network bank/gmac/* dma dma/*
    line_writer soc/fabric/home/lineTransfer/writer/*
    ex_packet soc/core/core/addrPacket*
    fetch_admission soc/fabric/nativeCut/*
    instruction_translation soc/core/it/*
    instruction_cache soc/core/icache/coherent/cache/*
    cache_probe *cache/coherent/cache/probe*
    cache_metadata *cache/coherent/cache/valid*
    cache_replacement *cache/coherent/cache/replacement*}
foreach {name pattern} $units {
    set ends [get_cells -quiet -hierarchical -filter "IS_SEQUENTIAL == 1 && NAME =~ $pattern"]
    if {![llength $ends] && $name in {instruction_translation instruction_cache cache_probe}} {
        error "missing actual IF/probe timing endpoints: $name"
    }
    if {[llength $ends]} {
        report_timing -to $ends -delay_type max -max_paths 10 -nworst 1 \
            -file [file join $report_root [format "setup_%s_synth.rpt" $name]]
    }
}
set bram36 [get_cells -hierarchical -filter {REF_NAME == RAMB36E2}]
set bram18 [get_cells -hierarchical -filter {REF_NAME == RAMB18E2}]
set dsps [get_cells -hierarchical -filter {REF_NAME == DSP48E2}]
set rf 0; set fpr 0; set cache 0; set cache_bits 0; set rom 0
set map [open [file join $report_root ram_dsp_mapping.txt] w]
puts $map "32KiB_I_32KiB_D 2ways DDR2GiB CPU300MHz UART50MHz MAC125MHz"
foreach cell [concat $bram36 $bram18 $dsps] {
    puts $map "$cell [get_property REF_NAME $cell]"
    if {[string match "*rf*bank*" $cell]} { incr rf }
    if {[string match "*fpr*fpBank*" $cell]} { incr fpr }
    if {[string match "*cache*data*" $cell]} {
        incr cache
        if {[get_property REF_NAME $cell] eq "RAMB36E2"} { incr cache_bits 36864 } else { incr cache_bits 18432 }
    }
    if {[string match "*rom*storage*" $cell]} { incr rom }
}
set tag_ff [get_cells -quiet -hierarchical -filter \
    {IS_SEQUENTIAL == 1 && (NAME =~ *tagBanks* || NAME =~ *directoryBanks*) && REF_NAME =~ FD*}]
puts $map "rf=$rf fpr=$fpr cache=$cache cache_allocated_bram_bits=$cache_bits rom=$rom tag_or_directory_payload_ff=[llength $tag_ff]"
puts $map "cdc_counts=$cdc_counts"
close $map
if {$rf < 2 || $fpr < 3 || $cache < 16 || $cache_bits < 524288 || $rom == 0 || [llength $dsps] == 0} {
    error "required real RAM/DSP mapping missing: rf=$rf fpr=$fpr cache=$cache rom=$rom"
}
if {[llength $tag_ff] > 0} { error "tag/directory payloads expanded into FF" }
set cpu [get_timing_paths -from [get_clocks orbital_i1_cpu] -to [get_clocks orbital_i1_cpu] -max_paths 1]
set cpu_wns [get_property SLACK $cpu]
set result [open [file join $report_root result.json] w]
puts $result "{\"status\":\"COMPLETE_NETWORK_SYNTHESIS_ONLY_NOT_ROUTED\",\"cpu_target_hz\":300000000,\"cpu_setup_wns_ns\":$cpu_wns,\"cache_bytes_each\":32768,\"ramb36\":[llength $bram36],\"ramb18\":[llength $bram18],\"dsp\":[llength $dsps],\"cache_bram_primitives\":$cache,\"native_timing_boundaries\":[llength $native_cuts],\"line_engine_entries\":2,\"physical_qualified\":false,\"board_qualified\":false,\"bit_generated\":false}"
close $result
puts "I1_NETWORK_SYNTHESIS_DONE CPU300MHz CPU_WNS=$cpu_wns CACHE32K32K NOT_ROUTED NO_BIT"
close_project
