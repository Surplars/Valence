# Accept only the exact Vivado-inserted, permanently enabled, noninverting
# ASYNC BUFGCE between the CPU release Q and its original reset consumers.
rename valence_mac::same_net valence_mac::same_net_direct_before_r23
proc valence_mac::same_net {a b} {
 if {![catch {valence_mac::same_net_direct_before_r23 $a $b}]} {return}
 set q {u_soc/board/nativeBank/gmac/cpuRelease/release_0_reg[2]/Q}
 set c {u_soc/board/nativeBank/gmac/cpuRelease/release_0_reg[2]_bufg_place}
 if {$a eq $q} {set sink $b} elseif {$b eq $q} {set sink $a} else {error "MAC nets differ outside reviewed release buffer: $a / $b"}
 set cell [valence_mac::one get_cells $c]
 if {[get_property REF_NAME $cell] ne {BUFGCE} || [get_property CE_TYPE $cell] ne {ASYNC}} {error {Unreviewed placed release buffer type}}
 foreach p {I CE} {
  if {[get_property IS_INVERTED [valence_mac::one get_pins $c/$p]] ni {0 FALSE false 1'b0}} {error {Unproved placed release buffer input polarity}}
 }
 set ce [get_nets -quiet -segments -of_objects [get_pins $c/CE]]
 if {[llength $ce]!=1 || [get_property TYPE $ce] ne {POWER}} {error {Placed release buffer CE is not constant one}}
 if {[valence_mac::drivers $c/I] ne [list $q] || [valence_mac::drivers $sink] ne [list $c/O]} {error {Placed release buffer exact unique drivers differ}}
 valence_mac::same_net_direct_before_r23 $c/I $q
 valence_mac::same_net_direct_before_r23 $c/O $sink
 puts $::valence_mac::facts [list PLACED_TRANSPARENT_CPU_RELEASE_BUFFER $c source $q sink $sink CE POWER CE_TYPE ASYNC I_INVERTED 0 CE_INVERTED 0 NO_TIMING_EXCEPTION 1]
}
diag_event placed_release_buffer proven {EXACT_ASYNC_BUFGCE_CE_ONE_NONINVERTING_UNIQUE_INPUT_OUTPUT}
