# The retained original routed-DCP constraint declares this existing USER1
# INTERNAL_TCK at 50ns. Restore only that exact source; do not waive hub paths.
proc common_restore_debug_hub_clock {profile} {
 if {$profile ne {zu15eg-existing-user1-debug-hub-tck50ns}} {error {Explicit original debug-hub clock profile required}}
 source [file join [file dirname [info script]] .. next check_jtag_chain.tcl]
 set name dbg_hub/inst/BSCANID.u_xsdbm_id/SWITCH_N_EXT_BSCAN.bscan_inst/SERIES7_BSCAN.bscan_inst
 set cell [get_cells -quiet $name]
 if {[llength $cell]!=1 || [get_property REF_NAME $cell] ne {BSCANE2}} {error {Original exact debug-hub BSCANE2 absent}}
 set owners 0
 foreach c [get_cells -quiet -hier -filter {REF_NAME == BSCANE2}] {
  if {[valence_jtag_integer_property $c {JTAG_CHAIN CONFIG.JTAG_CHAIN}]==1} {
   if {[get_property NAME $c] ne $name} {error {Unexpected USER1 BSCAN owner}}
   incr owners
  }
 }
 if {$owners!=1} {error {Original debug-hub USER1 ownership differs}}
 set pin [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME == INTERNAL_TCK}]
 if {[llength $pin]!=1 || [get_property NAME $pin] ne "$name/INTERNAL_TCK"} {error {Original debug-hub INTERNAL_TCK absent}}
 set clocks [get_clocks -quiet -of_objects $pin]
 if {![llength $clocks]} {
  create_clock -name valence_debug_hub_tck -period 50.000 $pin
 } elseif {[llength $clocks]!=1 || abs([get_property PERIOD $clocks]-50.0)>0.001} {
  error {Existing debug-hub clock differs from original 50ns profile}
 }
 puts {ORIGINAL_DEBUG_HUB_USER1_TCK_RESTORED_50NS_NO_PATH_WAIVER}
}
