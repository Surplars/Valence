if {$argc != 2} {error "usage: combined_place.tcl CANDIDATE_ROOT FRESH_RUN_NAME"}
set root [file normalize [lindex $argv 0]]
set name [lindex $argv 1]
if {![regexp {^[a-zA-Z0-9_-]+$} $name]} {error "Invalid run basename"}
source [file join $root scripts runtime.tcl]
r3_load_config $root
source [file join $root scripts combined_runtime.tcl]
combined_gate $root
puts [combined_python $root combined_stage_receipt.py [list [combined_root_path $root] --vivado-version [version -short] --check-synthesis]]
set out [file join $root $name]
if {[file exists $out]} {error "Preserve previous physical evidence"}
file mkdir $out
cd $out
r3_apply_threads place_begin
source [file join $root scripts r3_common.tcl]
if {[catch {
    open_checkpoint [file join $root synthesis post_synth_unconstrained.dcp]
    r3_discover
    source [file join $root export board native-mac-mode.tcl]
    r3_configure_python $out
    valence_native_mac_verify_export
    source [file join $root scripts r3_rom_graph.tcl]
    r3_rom_actual_dump rom-init-preplace.tsv
    puts [combined_verify_rom $root [file join $out rom-init-preplace.tsv] [file join $out combined-rom-preplace.json]]
    read_xdc [file join $root board board_ddr.xdc]
    read_xdc [file join $root board pl_ddr4_pins.xdc]
    read_xdc [file join $root export board trispeed_pins_only.xdc]
    r3_source_bound [file join $root scripts board_controls.tcl]
    v_apply_board_constraints 1000
    set cpuClock [get_clocks -of_objects [r3_one get_pins $V_SOC_ROOT/clock]]
    if {[llength $cpuClock]!=1 || abs([get_property PERIOD $cpuClock]-10.0)>0.001} {error "CPU100 clock required"}
    source [file join $root export board bscan_timing.tcl]
    valence_apply_bscan_timing $V_BSCAN_PRIMITIVE $V_BSCAN_ENGINE $cpuClock zu15eg-user2-tck50-positive-v1
    r3_source_bound [file join $root export board mac-netlist-binding.tcl]
    source [file join $root export board mac_registered_level_constraints.tcl]
    valence_mac_registered_level_constraints $VALENCE_MAC_CONTRACT
    valence_native_mac_assert_mode $V_RGMII_ROOT
    set f [open mac-raw-handoff-synth.txt w];puts $f [valence_mac_roles::audit $V_RGMII_ROOT 1 1 1];close $f
    r3_source_bound [file join $root scripts final_board_inventory.tcl]
    write_checkpoint constrained.dcp
    r3_reports [file join $out post_synth] $cpuClock
    r3_apply_threads before_opt
    opt_design
    r3_apply_threads after_opt
    if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Functional black boxes after opt"}
    valence_trispeed_packet_cdc_constraints $V_GMAC_ROOT
    v_control_constraints
    valence_reapply_bscan_cdc $V_BSCAN_PRIMITIVE $V_BSCAN_ENGINE $cpuClock
    valence_mac_registered_level_constraints $VALENCE_MAC_CONTRACT
    valence_native_mac_assert_mode $V_RGMII_ROOT
    set f [open mac-raw-handoff-opt.txt w];puts $f [valence_mac_roles::audit $V_RGMII_ROOT 1 1 1];close $f
    r3_rom_dump rom-init-opt.tsv
    write_checkpoint optimized.dcp
    place_design -directive Explore
    write_checkpoint placed.dcp
    r3_rom_actual_dump rom-init-placed.tsv
    puts [combined_verify_rom $root [file join $out rom-init-placed.tsv] [file join $out combined-rom-placed.json]]
    r3_reports [file join $out post_place] $cpuClock
    report_design_analysis -congestion -file [file join $out post_place congestion.rpt]
    r3_source_bound [file join $root scripts final_board_inventory.tcl]
    set f [open stage-result.txt w];puts $f "PLACED_REQUIRES_REVIEW CPU100 PROOF3 CREDIT2 LSU4 MAC_GENERICS1 USER2 EXPLICIT_SELECTED_COMBINED_ROM_GRAPH_VERIFIED NO_ROUTE_NO_BIT";close $f
    close_design
    puts [combined_python $root combined_stage_receipt.py [list [combined_root_path $root] --vivado-version [version -short] --seal-stage $name]]
} why options]} {
    set f [open failure.txt w];puts $f $why;puts $f [dict get $options -errorinfo];close $f
    puts stderr "COMBINED_PLACE_FAILED $why"
    exit 1
}
exit 0
