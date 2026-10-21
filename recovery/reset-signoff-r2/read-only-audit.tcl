set out [file normalize {out/reset-signoff-r2}]
open_checkpoint {E:/VM/Share/Valence-rtl/valence-i1-optional-20261019-r1/recovery-timing-batch-20261021-r2/diagnostic-implementation-r1/routed-diagnostic-unqualified.dcp}
report_drc -checks [get_drc_checks DCIRST-1] -file $out/dcirst-full.rpt -force
report_cdc -details -file $out/cdc-full.rpt
set f [open $out/reset-cones.txt w]
puts $f "DCIRESET cells: [get_cells -hier -filter {REF_NAME == DCIRESET}]"
puts $f {ENDPOINT phy_reset_pipe_reg[0]/PRE}
set p [get_pins -quiet {phy_reset_pipe_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT u_soc/peripherals/cmu/bridge/destinationResetSync/release_0_reg[0]/PRE}
set p [get_pins -quiet {u_soc/peripherals/cmu/bridge/destinationResetSync/release_0_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT u_soc/peripherals/uart/agent/release_0/release_0_reg[0]/PRE}
set p [get_pins -quiet {u_soc/peripherals/uart/agent/release_0/release_0_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT u_soc/peripherals/uart/bridge/destinationResetSync/release_0_reg[0]/PRE}
set p [get_pins -quiet {u_soc/peripherals/uart/bridge/destinationResetSync/release_0_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT u_soc/peripherals/uart/gatedClock_gate/release_0/release_0_reg[0]/PRE}
set p [get_pins -quiet {u_soc/peripherals/uart/gatedClock_gate/release_0/release_0_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT u_soc/peripherals/uart/ingress/release_0/release_0_reg[0]/PRE}
set p [get_pins -quiet {u_soc/peripherals/uart/ingress/release_0/release_0_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT u_soc/peripherals/uart/rawRelease/release_0_reg[0]/PRE}
set p [get_pins -quiet {u_soc/peripherals/uart/rawRelease/release_0_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT phy_reset_pipe_reg[0]/PRE}
set p [get_pins -quiet {phy_reset_pipe_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT ui_reset_pipe_reg[0]/PRE}
set p [get_pins -quiet {ui_reset_pipe_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT rx_reset_pipe_reg[0]/PRE}
set p [get_pins -quiet {rx_reset_pipe_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT u_soc/peripherals/gmac/physicalIngress/crossing/fifo/sourceRelease/release_0_reg[0]/PRE}
set p [get_pins -quiet {u_soc/peripherals/gmac/physicalIngress/crossing/fifo/sourceRelease/release_0_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT u_soc/peripherals/gmac/physicalIngress/sourceRelease/release_0_reg[0]/PRE}
set p [get_pins -quiet {u_soc/peripherals/gmac/physicalIngress/sourceRelease/release_0_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT u_soc/peripherals/gmac/rawDiagnostics/mailbox/sourceRelease/release_0_reg[0]/PRE}
set p [get_pins -quiet {u_soc/peripherals/gmac/rawDiagnostics/mailbox/sourceRelease/release_0_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT u_soc/peripherals/gmac/rawDiagnostics/sourceRelease/release_0_reg[0]/PRE}
set p [get_pins -quiet {u_soc/peripherals/gmac/rawDiagnostics/sourceRelease/release_0_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT u_soc/peripherals/gmac/rawRxRelease/release_0_reg[0]/PRE}
set p [get_pins -quiet {u_soc/peripherals/gmac/rawRxRelease/release_0_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT u_soc/peripherals/gmac/rxClockWatchdog/sourceRelease/release_0_reg[0]/PRE}
set p [get_pins -quiet {u_soc/peripherals/gmac/rxClockWatchdog/sourceRelease/release_0_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT u_soc/peripherals/gmac/rxRate/destinationRelease/release_0_reg[0]/PRE}
set p [get_pins -quiet {u_soc/peripherals/gmac/rxRate/destinationRelease/release_0_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT network_clock/phase_reset_reg[0]/PRE}
set p [get_pins -quiet {network_clock/phase_reset_reg[0]/PRE}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT u_debug/enabled.transport/raw_release_reg[0]/CLR}
set p [get_pins -quiet {u_debug/enabled.transport/raw_release_reg[0]/CLR}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT u_debug/enabled.transport/source_release_reg[0]/CLR}
set p [get_pins -quiet {u_debug/enabled.transport/source_release_reg[0]/CLR}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
puts $f {ENDPOINT u_debug/enabled.transport/update_release_reg[0]/CLR}
set p [get_pins -quiet {u_debug/enabled.transport/update_release_reg[0]/CLR}]
if {[llength $p]} {
 puts $f "RESET_NET [get_nets -of_objects $p]"
 puts $f "STARTPOINTS [all_fanin -flat -startpoints_only -to $p]"
 set cone [all_fanin -flat -only_cells -to $p]
 foreach c $cone { puts $f "CONE $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c] INIT=[get_property INIT $c]"; foreach cp [get_pins -of_objects $c] {puts $f "CONEPIN $cp NET=[get_nets -of_objects $cp]"} }
 set root [get_cells -of_objects $p]
 set stem [regsub {\[[0-9]+\]$} $root {}]
 foreach c [get_cells -quiet "${stem}*"] {
  puts $f "CHAIN $c REF=[get_property REF_NAME $c] ASYNC_REG=[get_property ASYNC_REG $c]"
  foreach pin [get_pins -of_objects $c] {puts $f "PIN $pin NET=[get_nets -of_objects $pin]"}
 }
}
foreach p [get_ports -filter {IOSTANDARD =~ *DCI*}] {
 puts $f "DCIPORT $p PACKAGE_PIN=[get_property PACKAGE_PIN $p] IOSTANDARD=[get_property IOSTANDARD $p]"
 puts $f "DCIPINS [get_pins -leaf -of_objects [get_nets -of_objects $p]]"
}
close $f
exit
