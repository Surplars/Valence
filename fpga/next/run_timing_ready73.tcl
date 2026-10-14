# Fresh ready73 physical evaluation. No checkpoint recovery or timing-PASS claim.
# Private board/tool paths live in the caller's reviewed binding, not this file.
proc ready73_design_identity {} {
    if {[get_property TOP [current_design]] ne "soc_top_fpga_next_ddr" ||
        [get_property PART [current_design]] ne "xczu15eg-ffvb1156-2-i"} {error "Wrong ready73 top/part"}
}
proc ready73_blackboxes {stage} {
    if {$stage ni {synth postopt placed}} {error "Unknown physical stage"}
    set boxes [get_cells -quiet -hier -filter {IS_BLACKBOX}]
    foreach c $boxes {
        if {$stage ne "synth" || [get_property NAME $c] ne "dbg_hub" ||
            [get_property REF_NAME $c] ne "dbg_hub_CV" ||
            [get_property ORIG_REF_NAME $c] ne "dbg_hub_CV" ||
            [get_property IS_PRIMITIVE $c] ni {0 FALSE false}} {
            error "Unresolved black box at $stage: $c"
        }
    }
    if {$stage eq "synth" && [llength $boxes]>1} {error "Only the one exact pre-opt debug-generation stub is allowed"}
}
proc ready73_gate {stage} {
    ready73_design_identity
    ready73_blackboxes $stage
    valence_native_mac_verify_export
    uplevel #0 [list source [file join $::READY73_EXPORT board native_mac_roles.tcl]]
    set roles [valence_mac_roles::audit u_rgmii 1 1 1]
    uplevel #0 [list source [file join $::READY73_EXPORT board require_jtag_chain.tcl]]
    if {$stage eq "placed"} {
        valence_bscan_qualifiers $::VALENCE_JTAG_OWN_CELL $::READY73_BSCAN_ENGINE
        valence_bscan_phase_handoff $::READY73_BSCAN_ENGINE
        valence_bscan_fault_phase $::READY73_BSCAN_ENGINE
    }
    set f [open [file join $::READY73_OUTPUT $stage.roles.txt] w]
    puts $f $roles; close $f
}
proc ready73_run {} {
    global argv
    if {[llength $argv]!=3} {error "Usage: run_timing_ready73.tcl BINDING OUTPUT EXPORT"}
    set ::READY73_OUTPUT [file normalize [lindex $argv 1]]
    if {[file exists $::READY73_OUTPUT]} {error "Fresh output directory required"}
    uplevel #0 [list source [file normalize [lindex $argv 0]]]
    foreach key {READY73_EXPORT READY73_READ_DESIGN READY73_CONFIGURE_PYTHON READY73_SYNTH_ARGS READY73_ORIGINAL_CLOCKS READY73_CONTROL_CDC READY73_BSCAN_ENGINE READY73_FABRIC_CLOCK VALENCE_JTAG_OWN_CELL VALENCE_TRISPEED_MBPS} {
        if {![info exists ::$key]} {error "Missing reviewed binding: $key"}
    }
    if {[file normalize $::READY73_EXPORT] ne [file normalize [lindex $argv 2]]} {error "Binding export differs from validated named ready73 export"}
    file mkdir $::READY73_OUTPUT
    uplevel #0 $::READY73_READ_DESIGN
    uplevel #0 [list source [file join $::READY73_EXPORT board native-mac-mode.tcl]]
    uplevel #0 $::READY73_CONFIGURE_PYTHON
    valence_native_mac_synth_design {*}$::READY73_SYNTH_ARGS
    ready73_design_identity
    ready73_blackboxes synth
    # Board/IP primary clocks and package-only XDC precede clock-dependent gates.
    uplevel #0 $::READY73_ORIGINAL_CLOCKS
    uplevel #0 [list source [file join $::READY73_EXPORT board require_trispeed.tcl]]
    uplevel #0 $::READY73_CONTROL_CDC
    uplevel #0 [list source [file join $::READY73_EXPORT board bscan_timing.tcl]]
    valence_apply_bscan_timing $::VALENCE_JTAG_OWN_CELL $::READY73_BSCAN_ENGINE $::READY73_FABRIC_CLOCK zu15eg-user2-tck50-positive-v1
    ready73_gate synth
    valence_native_mac_checkpoint synth [file join $::READY73_OUTPUT synth.dcp]
    valence_native_mac_opt_design
    ready73_blackboxes postopt
    valence_trispeed_packet_cdc_constraints u_soc/board/nativeBank/gmac
    uplevel #0 $::READY73_CONTROL_CDC
    valence_reapply_bscan_cdc $::VALENCE_JTAG_OWN_CELL $::READY73_BSCAN_ENGINE $::READY73_FABRIC_CLOCK
    valence_mac_registered_level_constraints $::VALENCE_MAC_CONTRACT
    ready73_gate postopt
    valence_native_mac_checkpoint postopt [file join $::READY73_OUTPUT postopt.dcp]
    place_design
    # Placement invalidates the original live synth/opt seal by design. Never
    # reseal it: placed output is a separate fresh mapped observation/checkpoint.
    ready73_gate placed
    write_checkpoint [file join $::READY73_OUTPUT placed.dcp]
    report_timing_summary -file [file join $::READY73_OUTPUT placed_timing.rpt]
    report_utilization -file [file join $::READY73_OUTPUT placed_utilization.rpt]
    set f [open [file join $::READY73_OUTPUT evaluation-complete.txt] {WRONLY CREAT EXCL}]
    puts $f "COMPLETED_SYNTH_OPT_PLACE_NOT_TIMING_SIGNOFF"
    puts $f "top=[get_property TOP [current_design]]"
    puts $f "design_name=[get_property NAME [current_design]]"
    close $f
}
if {[catch {ready73_run} why options]} {
    puts stderr "READY73_PHYSICAL_EVALUATION_FAILED: $why"
    if {[dict exists $options -errorinfo]} {puts stderr [dict get $options -errorinfo]}
    exit 1
}
exit 0
