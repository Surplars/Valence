source [file join $valence(root) fpga common skew_scope.tcl]
common_skew_begin
source [file join $valence(root) fpga common media_constraints.tcl]
source [file join $valence(root) fpga common common_cdc.tcl]
source [file join $valence(root) fpga inorder bscan_timing_i1.tcl]
common_media_apply 1000
common_media_cdc
set fabric [get_clocks -quiet -of_objects [get_pins -quiet u_soc/fabricClock]]
if {[llength $fabric] != 1} {error "Missing actual fabric clock"}
valence_apply_bscan_timing u_debug/enabled.user_scan u_debug/enabled.transport [get_property NAME $fabric] zu15eg-user2-tck50-halfcycle-i1-v2
common_cdc::constrain
source [file join $valence(root) fpga common management_constraints.tcl]
common_management_constraints

common_skew_end
