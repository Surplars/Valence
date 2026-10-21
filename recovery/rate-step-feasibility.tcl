# Parameter legality only: never synthesize or implement a design.
set out [file normalize [lindex $argv 0]]
file mkdir $out
foreach cmd {synth_design launch_runs create_ip_run opt_design place_design phys_opt_design route_design write_checkpoint write_bitstream} {
 if {[llength [info commands $cmd]]} {
  rename $cmd forbidden_$cmd
  proc $cmd {args} {error {RATE_FEASIBILITY_NO_SYNTHESIS_OR_IMPLEMENTATION}}
 }
}
if {[catch {
 create_project rate_feasibility [file join $out project] -part xczu15eg-ffvb1156-2-i
 create_ip -name clk_wiz -vendor xilinx.com -library ip -version 6.0 -module_name rate_probe
 set ip [get_ips rate_probe]
 set f [open [file join $out exact-rates.csv] w]
 puts $f {requested_mhz,actual_mhz,d,m,o,pfd_mhz,vco_mhz,ip_validated}
 for {set hz 50} {$hz<=200} {incr hz 5} {
  # A constructive integer-only solution, not a rounded Clock Wizard request.
  set d 10
  if {$hz<=75} {set o 20} elseif {$hz<=160} {set o 10} else {set o 5}
  set m [expr {$hz*$o/25}]
  if {$m*25 != $hz*$o} {error "Nonintegral multiplier for $hz"}
  set_property CONFIG.OVERRIDE_MMCM false $ip
  set_property CONFIG.CLKOUT1_REQUESTED_OUT_FREQ [format %.3f $hz] $ip
  set_property -dict [list CONFIG.PRIMITIVE MMCM CONFIG.PRIM_SOURCE No_buffer \
    CONFIG.PRIM_IN_FREQ 250.000 CONFIG.NUM_OUT_CLKS 1 \
    CONFIG.CLKOUT1_DRIVES BUFG CONFIG.USE_RESET true CONFIG.USE_LOCKED true \
    CONFIG.USE_DYN_RECONFIG true CONFIG.OVERRIDE_MMCM true \
    CONFIG.MMCM_DIVCLK_DIVIDE $d CONFIG.MMCM_CLKFBOUT_MULT_F [format %.3f $m] \
    CONFIG.MMCM_CLKOUT0_DIVIDE_F [format %.3f $o]] $ip
  set valid [validate_ip -verbose $ip]
  if {$valid!=1} {error "Clock Wizard rejected exact $hz MHz configuration"}
  set actual_d [get_property CONFIG.MMCM_DIVCLK_DIVIDE $ip]
  set actual_m [get_property CONFIG.MMCM_CLKFBOUT_MULT_F $ip]
  set actual_o [get_property CONFIG.MMCM_CLKOUT0_DIVIDE_F $ip]
  set actual [expr {250.0*$actual_m/$actual_d/$actual_o}]
  if {abs($actual-$hz)>0.000000001} {error "Clock Wizard approximated $hz as $actual"}
  set pfd [expr {250.0/$actual_d}]
  set vco [expr {$pfd*$actual_m}]
  if {$pfd<10 || $pfd>500 || $vco<800 || $vco>1600} {error "Out-of-range clock for $hz"}
  puts $f "$hz,$actual,$actual_d,$actual_m,$actual_o,$pfd,$vco,$valid"
  flush $f
  puts "RATE_PARAMETER_LEGAL requested=$hz actual=$actual D=$actual_d M=$actual_m O=$actual_o PFD=$pfd VCO=$vco"
 }
 close $f
 # Check whether this IP-level validation actually rejects an illegal VCO.
 set rejected [catch {
  set_property -dict [list CONFIG.MMCM_DIVCLK_DIVIDE 10 CONFIG.MMCM_CLKFBOUT_MULT_F 8.000 CONFIG.MMCM_CLKOUT0_DIVIDE_F 4.000] $ip
  set negative_valid [validate_ip -verbose $ip]
  if {$negative_valid!=1} {error {IP_VALIDATOR_REJECTED_NEGATIVE_VCO_200}}
 } negative_reason]
 set f [open [file join $out negative-control.tcllist] w]
 puts $f [list vco_mhz 200 rejected $rejected reason $negative_reason]
 close $f
 puts "RATE_NEGATIVE_CONTROL vco=200 rejected=$rejected reason=$negative_reason"
 puts {RATE_PARAMETER_SWEEP_COMPLETE_31_EXACT_CONFIGS_NO_SYNTH_NO_BOARD_SIGNOFF}
 close_project
} reason options]} {
 puts "RATE_PARAMETER_SWEEP_FAILED $reason"
 puts [dict get $options -errorinfo]
 catch {close $f}
 catch {close_project}
 exit 2
}
exit 0
