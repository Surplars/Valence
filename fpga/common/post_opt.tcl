source [file join $valence(root) fpga common dci_constraints.tcl]
common_dci_clock
source [file join $valence(root) fpga common skew_scope.tcl]
common_skew_begin
# Re-prove changed mapped endpoints after optimization; keep existing clocks.
source [file join $valence(root) fpga common media_constraints.tcl]
source [file join [file dirname [info script]] common_cdc.tcl]
source [file join $valence(root) fpga inorder bscan_timing_i1.tcl]
valence_native_mac_assert_mode u_rgmii
common_media_cdc
set debugPin u_soc/fabricClock
if {[info exists valence(clock_profile)] && $valence(clock_profile) in {boot50-static performance300-static boot50-dynamic}} {
    common_cdc::static_clock_anchors u_soc u_soc/fixedTimer u_soc/debugCrossing
    set debugPin u_soc/debugCrossing/sourceClock
    if {$valence(clock_profile) eq "boot50-dynamic"} {
        set debugPin u_soc/debugSequence/boundary/crossing/requests/sourceClock
    }
}
set fabric [get_clocks -quiet -of_objects [get_pins -quiet $debugPin]]
if {[llength $fabric] != 1} {error "Missing actual debug transport clock"}
valence_reapply_bscan_cdc u_debug/enabled.user_scan u_debug/enabled.transport [get_property NAME $fabric]
common_cdc::constrain
source [file join $valence(root) fpga common management_constraints.tcl]
common_management_constraints
source [file join [file dirname [info script]] performance_telemetry_constraints.tcl]
common_performance_telemetry_constraints

common_skew_end

if {[info exists valence(clock_profile)] && $valence(clock_profile) eq "boot50-dynamic"} {
    # Re-prove the narrow LOCKED topology and normal interstage timing after opt.
    source [file join [file dirname [file normalize [info script]]] dynamic dynamic_clock_constraints.tcl]
    native_dynamic_clock_constraints
    source [file join [file dirname [file normalize [info script]]] dynamic performance_targets.tcl]
    native_dynamic_performance_targets
}
