# Strict post-opt representation of unused INTERNAL PLL feedback: OUT open,
# IN tied to the tool-created primitive GND. External ownership stays strict.
rename valence_trispeed_same_net valence_trispeed_same_net_preopt_r18
proc valence_trispeed_same_net {left right label} {
 if {$left eq {network_clock/enabled.pll/CLKFBOUT} && $right eq {network_clock/enabled.pll/CLKFBIN}} {
  set pll [get_cells -quiet network_clock/enabled.pll]
  if {[llength $pll]!=1 || [get_property REF_NAME $pll] ne {PLLE4_ADV} || [get_property COMPENSATION $pll] ne {INTERNAL}} {error {Unproved INTERNAL PLL}}
  set a [get_pins -quiet $left];set b [get_pins -quiet $right]
  if {[llength $a]!=1 || [llength $b]!=1} {error {Missing feedback pin}}
  set an [get_nets -quiet -segments -of_objects $a]
  set bn [get_nets -quiet -segments -of_objects $b]
  if {![llength $an] && [llength $bn]==1 && [get_property TYPE $bn] eq {GROUND}} {
   set drivers [get_pins -quiet -leaf -of_objects $bn -filter {DIRECTION == OUT}]
   if {[llength $drivers]!=1 || [get_property REF_PIN_NAME $drivers] ne {G} || [get_property REF_NAME [get_cells -of_objects $drivers]] ne {GND}} {error {Unproved post-opt feedback ground primitive}}
   puts {ACTUAL_POSTOPT_INTERNAL_PLL_CLKFBOUT_OPEN_CLKFBIN_GND_NO_TIMING_EXCEPTION}
   return
  }
 }
 return [valence_trispeed_same_net_preopt_r18 $left $right $label]
}
diag_event network_clock postopt_feedback_representation {INTERNAL_OUT_OPEN_IN_PRIMITIVE_GND_EXTERNAL_OWNERSHIP_UNCHANGED}