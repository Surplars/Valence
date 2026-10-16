# Complete-board controls adapted to the frozen FpgaNext hierarchy.
# Packet/IO budgets are the exported recipe, unchanged. No global clock cuts.
source [file join [file dirname [info script]] .. export board trispeed_board_constraints_v1.tcl]
proc v_one {kind name} {
 set v [${kind} -quiet $name]
 if {[llength $v]!=1} {error "Expected exactly one $kind $name; got $v"}
 return $v
}
proc v_reset_release {base active_low {phase_dividers 0}} {
 set cells {}; set firstClock {}; set commonAsync {}; set firstInversion {}
 set apin [expr {$active_low ? "CLR" : "PRE"}]
 set ref [expr {$active_low ? "FDCE" : "FDPE"}]
 set value [expr {$active_low ? "POWER" : "GROUND"}]
 for {set i 0} {$i<3} {incr i} {
  set cell [v_one get_cells [format {%s[%d]} $base $i]]
  if {[get_property REF_NAME $cell] ne $ref || [get_property ASYNC_REG $cell] ni {TRUE true 1}} {error "Unproved reset-release FF $cell"}
  set clock [get_nets -of_objects [v_one get_pins $cell/C]]
  set async [get_nets -of_objects [v_one get_pins $cell/$apin]]
  set inversion [get_property IS_INVERTED [v_one get_pins $cell/C]]
  if {$inversion ni {0 1}} {error "Missing physical reset-release clock polarity: $cell"}
  if {$i==0} {set firstClock $clock;set commonAsync $async;set firstInversion $inversion}
  if {$clock ne $firstClock || $async ne $commonAsync || $inversion ne $firstInversion} {error "Reset chain lacks common clock/assertion: $base"}
  set din [get_nets -of_objects [v_one get_pins $cell/D]]
  if {$i==0} {
   if {[get_property TYPE $din] ne $value} {error "Reset chain constant entry changed: $base"}
  } else {
   set prior [v_one get_pins [format {%s[%d]/Q} $base [expr {$i-1}]]]
   if {$din ne [get_nets -of_objects $prior]} {error "Reset release is not a direct 3FF shift: $base"}
  }
  if {$i<2} {
   set sinks [get_pins -leaf -of_objects [get_nets -segments -of_objects [v_one get_pins $cell/Q]] -filter {DIRECTION == IN}]
   set next [v_one get_pins [format {%s[%d]/D} $base [expr {$i+1}]]]
   set expected [list $next]
   if {$phase_dividers && $i==1} {
    if {$base ne "network_clock/enabled/phase_reset_reg" || $active_low} {error "Divider exception only applies to exact frozen phase sequencer"}
    foreach div {network_clock/enabled/raw_div} {
     if {[get_property REF_NAME [v_one get_cells $div]] ne "BUFGCE_DIV" || [get_nets -of_objects [v_one get_pins network_clock/enabled/pad_buffer/O]] ne $clock} {error "Phase-reset divider source clock mismatch"}
     lappend expected [v_one get_pins $div/CLR]
    }
    puts "REVIEWED_PAD_DOMAIN_TWO_STAGE_DIVIDER_RELEASE third_stage_lock_indicator FUNCTIONAL_DIVIDER_CLR_FULLY_TIMED"
   }
   if {[lsort $sinks] ne [lsort $expected]} {error "Reset release early-stage functional fanout: $cell $sinks"}
  }
  lappend cells $cell
 }
 # Only explicitly checked release flops; functional reset sinks remain timed.
 set_false_path -to [get_pins -of_objects $cells -filter "REF_PIN_NAME == $apin"]
 puts "REVIEWED_THREE_STAGE_RESET_RELEASE $base polarity=$active_low cells=$cells"
}
proc v_clock_placement {} {
 set region [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AA7]]]
 set txRegion [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AC8]]]
 if {[llength $region]!=1 || $txRegion ne $region} {error "RGMII pads must share physical region"}
 set plls [lsort -dictionary [get_sites -of_objects $region -filter {NAME =~ PLL_X*}]]
 if {[llength $plls]!=2} {error "Missing physical network PLL sites"}
 set_property LOC [lindex $plls 0] [v_one get_cells network_clock/enabled/pll]
 set_property PHASESHIFT_MODE WAVEFORM [get_cells network_clock/enabled/pll]
 set uiBuffer [v_one get_pins u_ddr/inst/u_ddr4_infrastructure/u_bufg_divClk/O]
 set_property CLOCK_DEDICATED_ROUTE SAME_CMT_COLUMN [get_nets -of_objects $uiBuffer]
 foreach path {rx_clock_buffer rx_capture_clock_buffer network_clock/enabled/raw_div network_clock/enabled/pad_buffer network_clock/enabled/delay_buffer u_soc/board/nativeBank/gmac/txManaged_gate/buffer u_soc/board/nativeBank/gmac/rxManaged_gate/buffer} {
  set cell [v_one get_cells $path]
  set_property CLOCK_REGION $region $cell
  set_property USER_CLOCK_ROOT $region [get_nets -of_objects [v_one get_pins $path/O]]
 }
 # One shared dedicated PAD250 tree already drives all six DDRs.
 set_property CLOCK_DELAY_GROUP VALENCE_TX_PHASE_PAIR [get_nets -of_objects [get_pins network_clock/enabled/pad_buffer/O]]
}
proc v_control_constraints {} {
 set bank u_soc/board/nativeBank
 foreach hier {cmu/bridge uart/bridge} {valence_register_cdc_constraints $bank/$hier 8.0}
 foreach cell [get_cells -hier -filter "REF_NAME =~ CdcLevel* && NAME =~ $bank/*"] {
  set first [get_cells -quiet "$cell/stages_reg?0?"]
  if {[llength $first]!=1} {error "Missing exact CdcLevel first stage: $cell"}
  set ends [get_pins -of_objects $first -filter {REF_PIN_NAME == D}]
  set drivers [all_fanin -flat -startpoints_only -to $ends]
  if {$cell eq "$bank/gmac/mdio_io_mdioIn_sync"} {
   if {$drivers ne [get_ports eth_mdio]} {error "MDIO synchronizer must originate at actual pad"}
   set_max_delay -datapath_only 10.0 -from [get_ports eth_mdio] -to $ends
  } else {
   set starts [filter $drivers {REF_PIN_NAME == C || REF_PIN_NAME == CLK}]
   if {[llength $starts]==0} {error "Untimed CdcLevel source: $cell $drivers"}
   set_max_delay -datapath_only 8.0 -from $starts -to $ends
   puts "CONTROL_LEVEL_BOUNDED $cell budget=8 sources=$drivers"
   if {[llength $starts]!=1} {puts "CONTROL_LEVEL_RECONVERGENCE_REVIEW_REQUIRED $cell"}
  }
 }
 set uart [v_one get_pins $bank/uart/sampledRx_meta_reg/D]
 set_max_delay -datapath_only 20.0 -from [get_ports uart_rxd] -to $uart
 foreach base {ui_reset_pipe_reg reset_pipe_reg delay_reset_pipe_reg phy_reset_pipe_reg rx_reset_pipe_reg tx_release/tx_reset_pipe_reg} {v_reset_release $base 0}
 v_reset_release network_clock/enabled/phase_reset_reg 0 1
 foreach release [get_cells -quiet -hier -filter {REF_NAME =~ CdcResetRelease*}] {v_reset_release $release/release_0_reg 0}
 set uartClock [get_clocks -of_objects [v_one get_pins $bank/uart/uart/clock]]
 if {[llength $uartClock]!=1 || abs([get_property PERIOD $uartClock]-20.0)>0.001} {error "UART must retain actual 50MHz clock"}
 set_output_delay -clock $uartClock -max 10.0 [get_ports uart_txd]
 set_output_delay -clock $uartClock -min 0.0 [get_ports uart_txd]
 foreach port {eth_mdc eth_mdio led eth_reset_gate} {
  set endpoint [v_one get_ports $port]
  set starts [filter [all_fanin -flat -startpoints_only -to $endpoint] {REF_PIN_NAME == C || REF_PIN_NAME == CLK}]
  if {[llength $starts]==0} {error "Management output must be registered: $port"}
  set_max_delay -datapath_only 20.0 -from $starts -to $endpoint
 }
 foreach {port pin} {eth_mdc Y1 eth_reset_gate Y2 eth_mdio Y12} {
  if {[get_property PACKAGE_PIN [get_ports $port]] ne $pin} {error "Management package mapping mismatch $port"}
 }
}
proc v_apply_board_constraints {mbps} {
 valence_quarter_tx_clocks network_clock
 v_clock_placement
 valence_trispeed_board_constraints $mbps
 v_control_constraints
 foreach {pin period} {u_soc/clock 10 u_soc/io_alwaysOnClock 20 u_soc/board/nativeBank/uart/uart/clock 20 u_soc/io_nativeGmac_rawTxClock 8 u_rgmii/delay_clock 2 u_rgmii/tx_pad_clock 4} {
  set clock [get_clocks -of_objects [v_one get_pins $pin]]
  if {[llength $clock]!=1 || abs([get_property PERIOD $clock]-$period)>0.001} {error "Clock contract mismatch $pin"}
 }
 foreach port [get_ports] {
  if {[get_property PACKAGE_PIN $port] eq "" || [get_property IOSTANDARD $port] in {"" DEFAULT}} {error "Unbound physical board port $port"}
 }
}
