# Called only by inspect-scalars-and-continue.tcl, in the same open design.
if {[get_property NAME [current_design]] ne {soc_top_common_ddr}} {error {Unexpected open design}}
set argv [list $repo $out $target $profile 1 REUSE_HASH_VERIFIED_IP_RESTORED_CHECKPOINT DIAGNOSTIC_IMPLEMENT_NO_BIT]
set f [open [file join $repo fpga common recovery_map_constraints.tcl]]
set code [read $f];close $f
set needle {open_checkpoint $target}
if {[string first $needle $code]<0 || [string first $needle $code [expr {[string first $needle $code]+1}]]>=0} {
 error {Expected unique checkpoint-open command missing}
}
puts {CONTINUE_HASH_VERIFIED_EXISTING_DESIGN_NO_DCP_REOPEN}
eval [string map [list $needle {puts {REUSE_CURRENT_SCALAR_CENSUS_DESIGN_NO_REOPEN}}] $code]
