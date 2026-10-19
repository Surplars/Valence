# One bounded implementation of the already-qualified network OOC checkpoint.
# No synthesis, RTL edits, clock relaxation, blanket CDC exceptions or bit.
if {$argc != 3} {
    error "usage: route_network_diagnostic.tcl RTL_PACKAGE CONSTRAINED_DCP FRESH_OUTPUT"
}
lassign $argv package checkpoint output
foreach name {package checkpoint output} { set $name [file normalize [set $name]] }
if {![file isfile $checkpoint]} { error "existing constrained checkpoint required" }
if {[file exists $output]} { error "preserve previous physical evidence" }
file mkdir $output
set_param general.maxThreads 8
open_checkpoint $checkpoint
if {[get_property TOP [current_design]] ne "I1NetworkFpgaShell" ||
    [string tolower [get_property PART [current_design]]] ne "xczu15eg-ffvb1156-2-i"} {
    error "independent I1 network shell/part required"
}
proc i1_network_clock_contract {} {
    foreach {name period} {
        orbital_i1_cpu 3.333 i1_aon 20.0 i1_uart 20.0
        i1_mac_tx 8.0 i1_mac_rx 8.0
        valence_bscan_tck 50.0 valence_bscan_drck 50.0 valence_bscan_update 50.0
    } {
        set clock [get_clocks -quiet $name]
        if {[llength $clock] != 1 || abs([get_property PERIOD $clock] - $period) > 0.0005} {
            error "original clock period missing/changed: $name"
        }
    }
}
i1_network_clock_contract
# These three global buffers are outside the OOC shell. Explicit hypothetical
# sites permit routing diagnostics, NOT board clock/IP qualification. UART/TX
# use the existing five real parallel BUFGCEs and their original delay groups.
set context [open [file join $output context.txt] w]
puts $context "NETWORK_INTERNAL_OOC_DIAGNOSTIC_NOT_BOARD_NOT_MIG_NO_BIT"
puts $context "input_checkpoint=$checkpoint"
puts $context "CPU300MHz UART50MHz AON50MHz MAC_RX_TX125MHz USER2_TCK20MHz"
puts $context "Original OOC I/O delays, CDC max-delay/skew and USER2 exceptions retained."
puts $context "No actual Clock Wizard/MIG/RGMII IOB or board pin qualification."
foreach {port site} {
    io_clockIn BUFGCE_X0Y0
    io_alwaysOnClock BUFGCE_X0Y1
    io_macRxClock BUFGCE_X0Y2
} {
    if {[llength [get_ports -quiet $port]] != 1 ||
        [llength [get_sites -quiet $site]] != 1} {
        error "missing real OOC root/site: $port $site"
    }
    set_property HD.CLK_SRC $site [get_ports $port]
    puts $context "hypothetical_external_clock_source=$port:$site"
    puts "I1_NETWORK_OOC_CLOCK_CONTEXT port=$port site=$site NOT_BOARD_SIGNOFF"
}
close $context
set primitive [get_cells -quiet -hierarchical -filter {REF_NAME == BSCANE2}]
if {[llength $primitive] != 1} { error "one real USER2 primitive required" }
set primitive [get_property NAME $primitive]
if {![regsub {([/.])user_scan$} $primitive {\1transport} engine]} {
    error "USER2 sibling hierarchy changed"
}
source [file join $package bscan_timing_i1.tcl]
source [file join $package network_cdc.tcl]
source [file join $package network_clock_balance.tcl]

set ledger [open [file join $output stages.jsonl] w]
proc i1_network_stage {name output ledger} {
    i1_network_clock_contract
    set cpu [get_clocks orbital_i1_cpu]
    set setup [get_timing_paths -from $cpu -to $cpu -delay_type max -max_paths 1]
    set hold [get_timing_paths -from $cpu -to $cpu -delay_type min -max_paths 1]
    if {[llength $setup] != 1 || [llength $hold] != 1} {
        error "missing actual CPU setup/hold paths: $name"
    }
    set wns [get_property SLACK $setup]
    set whs [get_property SLACK $hold]
    puts $ledger "{\"stage\":\"$name\",\"cpu_setup_wns_ns\":$wns,\"cpu_clock_group_hold_whs_ns\":$whs}"
    flush $ledger
    puts "I1_NETWORK_PHYSICAL_STAGE stage=$name CPU_WNS=$wns CPU_CLOCK_GROUP_WHS=$whs"
    report_timing_summary -delay_type min_max -report_unconstrained \
        -file [file join $output timing_$name.rpt]
    report_timing -from $cpu -to $cpu -delay_type max -max_paths 10 -nworst 1 \
        -file [file join $output setup_cpu_$name.rpt]
}
opt_design -directive Explore
# Reapply only the SAME source-qualified endpoint-specific CDC recipes after
# opt_design. No new false paths, clock groups, periods or latency exceptions.
valence_reapply_bscan_cdc $primitive $engine orbital_i1_cpu
i1_network_cdc [get_property PERIOD [get_clocks orbital_i1_cpu]]
i1_balanced_clock_roots [file join $output balanced_clock_roots.txt]
write_checkpoint [file join $output optimized.dcp]
place_design -directive Explore
i1_network_stage placed $output $ledger
write_checkpoint [file join $output placed.dcp]
phys_opt_design -directive AggressiveExplore
i1_network_stage pre_route_physopt $output $ledger
route_design -directive Explore
i1_network_stage first_route $output $ledger
write_checkpoint [file join $output first_routed.dcp]
# One bounded post-route optimization/repair, never an open-ended retry loop.
set cpu [get_clocks orbital_i1_cpu]
set setup [get_property SLACK [get_timing_paths -from $cpu -to $cpu -delay_type max -max_paths 1]]
set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
if {$setup < 0.0 || $hold < 0.0} {
    phys_opt_design -directive AggressiveExplore
    route_design -directive Explore
    puts "I1_NETWORK_POST_ROUTE_REPAIR count=1 NO_NEW_SYNTHESIS"
} else {
    puts "I1_NETWORK_POST_ROUTE_REPAIR count=0 INITIAL_TIMING_MET"
}
i1_network_stage final_route $output $ledger
close $ledger
write_checkpoint [file join $output routed.dcp]
report_route_status -file [file join $output route_status.rpt]
report_utilization -file [file join $output utilization.rpt]
report_utilization -hierarchical -file [file join $output hierarchical_utilization.rpt]
report_drc -file [file join $output drc.rpt]
report_cdc -details -file [file join $output cdc.rpt]
report_bus_skew -file [file join $output bus_skew.rpt]
report_clocks -file [file join $output clocks.rpt]
report_clock_interaction -file [file join $output clock_interaction.rpt]
report_exceptions -coverage -file [file join $output exceptions.rpt]
check_timing -verbose -file [file join $output check_timing.rpt]
set all [all_registers]
set cpu_registers [get_cells -quiet -hierarchical -filter {IS_SEQUENTIAL == 1 && NAME =~ soc/*}]
set ingress [get_cells -quiet -hierarchical -filter {IS_SEQUENTIAL == 1 && NAME =~ bank/uart/ingress/*}]
set uart [get_cells -quiet -hierarchical -filter {IS_SEQUENTIAL == 1 && NAME =~ bank/uart/uart/*}]
foreach {name starts ends kind} [list \
    setup_global {} {} max hold_global {} {} min \
    setup_internal $all $all max hold_internal $all $all min \
    setup_cpu $cpu $cpu max hold_cpu $cpu $cpu min \
    hold_cpu_internal $cpu_registers $cpu_registers min \
    hold_uart_raw_to_gated $ingress $uart min] {
    if {$starts eq "" && $ends eq ""} {
        set path [get_timing_paths -delay_type $kind -max_paths 1]
        report_timing -delay_type $kind -max_paths 20 -nworst 1 \
            -file [file join $output $name.rpt]
    } else {
        if {![llength $starts] || ![llength $ends]} { error "missing real endpoint: $name" }
        set path [get_timing_paths -from $starts -to $ends -delay_type $kind -max_paths 1]
        report_timing -from $starts -to $ends -delay_type $kind -max_paths 20 -nworst 1 \
            -file [file join $output $name.rpt]
    }
    if {[llength $path] != 1} { error "missing actual routed path: $name" }
    puts "I1_NETWORK_ROUTED_PATH scope=$name slack=[get_property SLACK $path]"
}
foreach {name pattern} {
    ex_packet soc/core/core/addrPacket*
    instruction_translation soc/core/it/*
    instruction_cache soc/core/icache/coherent/cache/*
    fetch_admission soc/fabric/nativeCut/*
    cache_probe *cache/coherent/cache/probe*
    cache_metadata *cache/coherent/cache/valid*
    cache_replacement *cache/coherent/cache/replacement*
    directory soc/fabric/home/*
    line_writer soc/fabric/home/lineTransfer/writer/*
    dma dma/*
    network bank/gmac/*
    fpu *I1FloatingPointSharedArithmetic*
} {
    set ends [get_cells -quiet -hierarchical -filter "IS_SEQUENTIAL == 1 && NAME =~ $pattern"]
    if {![llength $ends]} { error "missing routed timing family: $name" }
    report_timing -from $all -to $ends -delay_type max -max_paths 10 -nworst 1 \
        -file [file join $output setup_$name.rpt]
}
puts "I1_NETWORK_INTERNAL_OOC_ROUTING_DONE CPU300MHz NOT_BOARD_NOT_MIG_NO_BIT"
close_design
