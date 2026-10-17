# Reuse the completed exact synthesized checkpoint. NO synthesis/place/route.
# Report/constraint fixes are separated from frozen hardware input.
if {$argc != 4} { error "usage: resume_network_reports.tcl PACKAGE RAW_DCP NEW_OUTPUT REVIEWED_SCRIPTS" }
lassign $argv package checkpoint output scripts
foreach key {package checkpoint output scripts} { set $key [file normalize [set $key]] }
if {[file exists $output]} { error "preserve prior reports" }
file mkdir $output
set_param general.maxThreads 8
open_checkpoint $checkpoint
if {[get_property TOP [current_design]] ne "I1NetworkFpgaShell"} { error "checkpoint top mismatch" }
foreach {name period} {orbital_i1_cpu 3.333 i1_aon 20 i1_uart 20 i1_mac_tx 8 i1_mac_rx 8} {
    set clk [get_clocks -quiet $name]
    if {[llength $clk] != 1 || abs([get_property PERIOD $clk] - $period) > 0.0006} {
        error "unchanged300/125/50MHz clock contract required: $name"
    }
}
# Reapply the declarative I/O budget portion only; no clock replacement.
set constraints [open [file join $scripts network_ooc.xdc]]
set text [read $constraints]
close $constraints
foreach line [split $text "\n"] {
    if {[string match "set_input_delay *" $line] || [string match "set_output_delay *" $line]} { eval $line }
}
set primitive [get_property NAME [get_cells -hierarchical -filter {REF_NAME == BSCANE2}]]
if {![regsub {([/.])user_scan$} $primitive {\1transport} engine]} { error "USER2 sibling shape changed" }
source [file join $scripts bscan_timing_i1.tcl]
valence_apply_bscan_timing $primitive $engine orbital_i1_cpu zu15eg-user2-tck50-halfcycle-i1-v2
source [file join $package native-gmac-cdc-constraints.tcl]
source [file join $scripts network_cdc.tcl]
set cdc_failed [catch {i1_network_cdc [get_property PERIOD [get_clocks orbital_i1_cpu]]} cdc_result]
set fd [open [file join $output cdc_constraint_gate.txt] w]
puts $fd "cdc_failed=$cdc_failed result=$cdc_result"
close $fd
if {$cdc_failed} { puts "I1_CDC_GATE_FAILED $cdc_result REPORTS_ARE_DIAGNOSTIC_NOT_SIGNOFF" }
write_checkpoint [file join $output synthesized_report_context.dcp]
report_utilization -file [file join $output utilization.rpt]
report_utilization -hierarchical -file [file join $output hierarchical_utilization.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $output timing_synth.rpt]
report_timing -from [get_clocks orbital_i1_cpu] -to [get_clocks orbital_i1_cpu] \
    -delay_type max -max_paths 30 -nworst 1 -file [file join $output setup_cpu_synth.rpt]
report_timing -from [all_registers] -to [all_registers] -delay_type max -max_paths 40 -nworst 1 \
    -file [file join $output setup_internal_synth.rpt]
report_timing -delay_type min -max_paths 20 -nworst 1 -file [file join $output hold_synth.rpt]
report_clocks -file [file join $output clocks.rpt]
report_clock_interaction -file [file join $output clock_interaction.rpt]
report_cdc -details -file [file join $output cdc.rpt]
check_timing -verbose -file [file join $output check_timing.rpt]
foreach {name pattern} {core soc/core/core/* fpu *I1FloatingPointSharedArithmetic*
    cache *cache/coherent/cache/* directory soc/fabric/home/* fabric soc/fabric/*
    network bank/gmac/* dma dma/*} {
    set ends [get_cells -quiet -hierarchical -filter "IS_SEQUENTIAL == 1 && NAME =~ $pattern"]
    if {[llength $ends]} {
        report_timing -to $ends -delay_type max -max_paths 10 -nworst 1 \
            -file [file join $output [format "setup_%s_synth.rpt" $name]]
    }
}
set b36 [get_cells -hierarchical -filter {REF_NAME == RAMB36E2}]
set b18 [get_cells -hierarchical -filter {REF_NAME == RAMB18E2}]
set dsps [get_cells -hierarchical -filter {REF_NAME == DSP48E2}]
set rf 0; set fpr 0; set cache 0; set cache_bits 0; set rom 0
set fd [open [file join $output ram_dsp_mapping.txt] w]
foreach cell [concat $b36 $b18 $dsps] {
    set ref [get_property REF_NAME $cell]
    puts $fd "$cell $ref"
    if {[string match "*rf*bank*" $cell]} { incr rf }
    if {[string match "*fpr*fpBank*" $cell]} { incr fpr }
    if {[string match "*cache*data*" $cell]} {
        incr cache
        if {$ref eq "RAMB36E2"} { incr cache_bits 36864 } else { incr cache_bits 18432 }
    }
    if {[string match "*rom*storage*" $cell]} { incr rom }
}
set tag_ff [get_cells -quiet -hierarchical -filter \
    {IS_SEQUENTIAL == 1 && (NAME =~ *tagBanks* || NAME =~ *directoryBanks*) && REF_NAME =~ FD*}]
puts $fd "rf=$rf fpr=$fpr cache=$cache cache_allocated_bram_bits=$cache_bits rom=$rom tag_payload_ff=[llength $tag_ff]"
close $fd
set mapping_met [expr {$rf >= 2 && $fpr >= 3 && $cache_bits >= 524288 && $rom > 0 && [llength $tag_ff] == 0}]
set cpu [get_timing_paths -from [get_clocks orbital_i1_cpu] -to [get_clocks orbital_i1_cpu] -max_paths 1]
set wns [get_property SLACK $cpu]
set fd [open [file join $output result.json] w]
puts $fd "{\"status\":\"SYNTHESIS_CHECKPOINT_DIAGNOSTIC_ONLY\",\"cpu_target_hz\":300000000,\"cpu_setup_wns_ns\":$wns,\"cdc_constraint_gate_failed\":$cdc_failed,\"ram_mapping_met\":$mapping_met,\"ramb36\":[llength $b36],\"ramb18\":[llength $b18],\"dsp\":[llength $dsps],\"cache_bram_primitives\":$cache,\"cache_allocated_bram_bits\":$cache_bits,\"tag_payload_ff\":[llength $tag_ff],\"physical_qualified\":false,\"board_qualified\":false,\"bit_generated\":false}"
close $fd
puts "I1_NETWORK_REPORT_REUSE_DONE CPU300MHz WNS=$wns NO_NEW_SYNTHESIS NO_ROUTE NO_BIT"
close_design
if {$cdc_failed || !$mapping_met} { error "diagnostic reports retained; CDC/RAM gates not satisfied" }
