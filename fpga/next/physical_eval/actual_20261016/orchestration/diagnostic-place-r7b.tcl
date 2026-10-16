# External continuation of the successful live synthesis consumer session.
set f [open [file join $out actual-project-files.tsv] w]
foreach asset [lsort [get_files -all]] {
    puts $f [list $asset [get_property FILE_TYPE $asset]]
}
close $f
set f [open [file join $out actual-repair-registers.tsv] w]
foreach cell [lsort [get_cells -hier -filter {NAME =~ *preparationDescriptor* || NAME =~ *headClassification* || NAME =~ *tailClassification* || NAME =~ *nextLineDecision*}]] {
    puts $f [list $cell [get_property REF_NAME $cell]]
}
close $f
report_ip_status -file [file join $out ip-status-after-synth.rpt]
source [file join $pkg source fpga next physical_eval r3_common.tcl]
source [file join $root external-rom-deployment-compat-r1 r3_rom_graph_leaf_r2.tcl]
source [file join $root rom-preflight-official-r2 local-rom-contract.tcl]
source [file join $root orchestration rom-live-object-adapter-r7b.tcl]
proc diag_rom {stage checkpoint} {
    diag_event rom_${stage} begin
    rom_live_r7::rebuild
    set dump [file join $::out rom-${stage}.tsv]
    r3_rom_actual_dump $dump
    set decoderRoot [string trim [exec {D:/TOOLS/ENV/anaconda3/python.exe} -I -B [file join $::root orchestration prepare_rom_decoder.py] $::root $stage $checkpoint]]
    puts [exec {D:/TOOLS/ENV/anaconda3/python.exe} -I -B [file join $::pkg source fpga next physical_eval verify_combined_rom_graph.py] $decoderRoot $dump --rom-sha256 ee7c2e5fb86d50dad55df532aeb7ccb1d0b91cb37b0b7042d03b446eee362d79 --padded-sha256 0d03f41230ed458e133d9503acba36edb34689f5aaa6cafd41ea2f81ec5879fd --report [file join $::out rom-${stage}.json]]
    diag_event rom_${stage} passed {ACTUAL_LEAF_CLOCK_PROOF_AND_32768_WORDS}
}
proc diag_report {path command} {
    set code [catch {uplevel #0 $command} why options]
    set f [open [file join $::out report-status.tsv] a]
    puts $f [list $path [expr {$code ? {FAILED} : {EXPORTED}}] $why]
    close $f
    if {$code} {
        set e [open ${path}.error.txt w];puts $e $why;puts $e [dict get $options -errorinfo];close $e
        puts "REPORT_FAILED $path $why"
    }
    return $code
}
proc diag_reports {stage {full 1}} {
    set d [file join $::out reports $stage];file mkdir $d
    set cpu [get_clocks -of_objects [get_pins $::V_SOC_ROOT/clock]]
    foreach {name command} [list utilization [list report_utilization -hierarchical] timing_summary [list report_timing_summary -delay_type min_max -report_unconstrained] clocks [list report_clocks] check_timing [list check_timing -verbose] clock_interaction [list report_clock_interaction] exceptions [list report_exceptions -coverage] cdc [list report_cdc -details] bus_skew [list report_bus_skew] drc [list report_drc]] {
        diag_report [file join $d $name] [concat $command [list -file [file join $d ${name}.rpt]]]
    }
    foreach {delay mode} {max setup min hold} {
        set opts [list -delay_type $delay -max_paths 40 -nworst 3 -input_pins -nets -path_type full_clock_expanded]
        diag_report [file join $d $mode] [concat [list report_timing] $opts [list -file [file join $d ${mode}.rpt]]]
        diag_report [file join $d cpu_$mode] [concat [list report_timing -from $cpu -to $cpu] $opts [list -file [file join $d cpu_${mode}.rpt]]]
        foreach {dir names} {rx {eth_rxd[*] eth_rx_ctl} tx {eth_txd[*] eth_tx_ctl}} {
            set ports [get_ports -quiet $names]
            set side [expr {$dir eq {rx} ? {-from} : {-to}}]
            diag_report [file join $d ${dir}_${mode}] [concat [list report_timing $side $ports] $opts [list -file [file join $d ${dir}_${mode}.rpt]]]
        }
    }
    set async [get_pins -quiet -hier -filter {REF_PIN_NAME == CLR || REF_PIN_NAME == PRE}]
    foreach {delay mode} {max recovery min removal} {
        diag_report [file join $d $mode] [list report_timing -to $async -delay_type $delay -max_paths 40 -nworst 3 -input_pins -nets -path_type full_clock_expanded -file [file join $d ${mode}.rpt]]
    }
    if {$full} {diag_report [file join $d congestion] [list report_design_analysis -congestion -file [file join $d congestion.rpt]]}
    diag_report [file join $d constraints] [list write_xdc -force [file join $d actual-constraints.xdc]]
}
r3_discover
diag_rom synth [file join $out post-synth-unconstrained.dcp]
diag_event constraints begin {rate1000 VERSIONED_BOTH_CLOCK_AND_PIN_RECIPE}
read_xdc [file join $deps board board_ddr.xdc]
read_xdc [file join $deps board pl_ddr4_pins.xdc]
read_xdc [file join $pkg network export board trispeed_pins_only.xdc]
source [file join $pkg network scripts board_controls.tcl]
v_apply_board_constraints 1000
set cpuClock [get_clocks -of_objects [get_pins $V_SOC_ROOT/clock]]
source [file join $pkg network export board bscan_timing.tcl]
valence_apply_bscan_timing $V_BSCAN_PRIMITIVE $V_BSCAN_ENGINE $cpuClock zu15eg-user2-tck50-positive-v1
source [file join $pkg network export board mac-netlist-binding.tcl]
source [file join $pkg network export board audit_mac_netlist.tcl]
source [file join $pkg network export board mac_registered_level_constraints.tcl]
valence_mac_registered_level_constraints $VALENCE_MAC_CONTRACT
valence_native_mac_assert_mode $V_RGMII_ROOT
diag_save constrained_synthesis constrained-synth.dcp
diag_event constraints passed
diag_reports synthesis 0
puts [exec C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -File [file join $root orchestration memory_before_place.ps1] $root]
set_param general.maxThreads 4
diag_event optimization actual_begin
valence_native_mac_opt_design
diag_event optimization actual_end
diag_save optimized optimized.dcp
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error {Functional blackbox after optimization}}
valence_trispeed_packet_cdc_constraints $V_GMAC_ROOT
v_control_constraints
valence_reapply_bscan_cdc $V_BSCAN_PRIMITIVE $V_BSCAN_ENGINE $cpuClock
valence_mac_registered_level_constraints $VALENCE_MAC_CONTRACT
valence_native_mac_assert_mode $V_RGMII_ROOT
diag_rom optimized [file join $out optimized.dcp]
diag_save optimized_constrained optimized-constrained.dcp
puts [exec C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -File [file join $root orchestration memory_before_place.ps1] $root before-place]
source [file join $root placement-thread-choice.tcl]
diag_event placement actual_begin
place_design -directive Explore
diag_event placement actual_end
# Save before all auxiliary exports, retaining recovery evidence on any audit failure.
diag_save placed_unreviewed placed.dcp
diag_reports placed-1000
diag_rom placed [file join $out placed.dcp]
diag_event mac_actual_audit begin
set auditFailures [diag_report [file join $out mac-placed-1000] [list valence_mac::collect $VALENCE_MAC_CONTRACT $VALENCE_MAC_BINDING [file join $out mac-placed-1000] 1000]]
source [file join $pkg network export board audit_bscan_netlist.tcl]
incr auditFailures [diag_report [file join $out bscan-placed] [list valence_collect_bscan_netlist $V_BSCAN_PRIMITIVE $V_BSCAN_ENGINE $cpuClock [file join $out bscan-placed]]]
# Read-only STA scenario changes after saving the1000Mbps placed checkpoint.
# Internal fixed125/PAD250 clocks and8ns CDC budgets remain as bound by the package.
proc diag_media_case {rate} {
    diag_event sta_${rate} begin
    remove_input_delay [get_ports {eth_rxd[*] eth_rx_ctl}]
    remove_output_delay [get_ports {eth_txd[*] eth_tx_ctl}]
    remove_clocks [get_clocks {phy_tx_capture phy_rx_launch phy_rx}]
    valence_trispeed_rx_constraints $rate
    valence_trispeed_clock_reset_audit $::V_GMAC_ROOT $rate
    valence_trispeed_quarter_tx_constraints $::V_RGMII_ROOT $rate
    diag_reports placed-${rate} 0
    valence_mac::collect $::VALENCE_MAC_CONTRACT $::VALENCE_MAC_BINDING [file join $::out mac-placed-${rate}] $rate
    diag_event sta_${rate} exported
}
foreach rate {100 10} {
    incr auditFailures [diag_report [file join $out sta-${rate}] [list diag_media_case $rate]]
}
if {$auditFailures} {error "Placed DCP retained; $auditFailures auxiliary audit/scenario failures require review; see report-status.tsv"}
diag_event mac_actual_audit passed
diag_seal placed_gates_passed [file join $out placed.dcp]
