# Exact xsdbm v3.0 revision4 CDC contract from original Vivado2025.1 routed DCP.
# Source export SHA256: 30a24dc9ce9deecedd74244615ced9c277e90da446da12b941f4eedec3b3a0de
# Retained IP DCP SHA256: f88a2ef15c36fc04273d93759d5885c436a86a0e33cbc61c75e12fc713d0d342
# Only vendor timing commands; no CDC report waivers and no clock grouping.
namespace eval common_debug_hub_contract {
 variable commands {
  {set_false_path -from [filter [all_fanout -from [get_pins -filter REF_PIN_NAME=~wr_clk -of_objects [get_cells -hierarchical -filter {NAME =~ "*SUBCORE_FIFO.*rdfifo_inst"}]] -flat -endpoints_only] IS_LEAF] -to [get_cells -hierarchical -filter {NAME =~ *U_RD_FIFO*gdm.dm_gen.dm*/gpr1.dout_i_reg*}]}
  {set_max_delay -datapath_only -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_RD/U_RD_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_rdfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.gcx.clkx/*rd_pntr_gc_reg[*]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_RD/U_RD_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_rdfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.gcx.clkx/*gsync_stage[1].wr_stg_inst/Q_reg_reg[*]"}] 50.000}
  {set_bus_skew -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_RD/U_RD_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_rdfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.gcx.clkx/*rd_pntr_gc_reg[*]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_RD/U_RD_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_rdfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.gcx.clkx/*gsync_stage[1].wr_stg_inst/Q_reg_reg[*]"}] 16.000}
  {set_max_delay -datapath_only -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_RD/U_RD_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_rdfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.gcx.clkx/*wr_pntr_gc_reg[*]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_RD/U_RD_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_rdfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.gcx.clkx/*gsync_stage[1].rd_stg_inst/Q_reg_reg[*]"}] 16.000}
  {set_bus_skew -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_RD/U_RD_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_rdfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.gcx.clkx/*wr_pntr_gc_reg[*]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_RD/U_RD_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_rdfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.gcx.clkx/*gsync_stage[1].rd_stg_inst/Q_reg_reg[*]"}] 16.000}
  {set_false_path -from [filter [all_fanout -from [get_pins -filter REF_PIN_NAME=~wr_clk -of_objects [get_cells -hierarchical -filter {NAME =~ "*SUBCORE_FIFO.*wrfifo_inst"}]] -flat -endpoints_only] IS_LEAF] -to [get_cells -hierarchical -filter {NAME =~ *U_WR_FIFO*gdm.dm_gen.dm*/gpr1.dout_i_reg*}]}
  {set_max_delay -datapath_only -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_WR/U_WR_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_wrfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.gcx.clkx/*rd_pntr_gc_reg[*]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_WR/U_WR_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_wrfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.gcx.clkx/*gsync_stage[1].wr_stg_inst/Q_reg_reg[*]"}] 16.000}
  {set_bus_skew -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_WR/U_WR_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_wrfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.gcx.clkx/*rd_pntr_gc_reg[*]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_WR/U_WR_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_wrfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.gcx.clkx/*gsync_stage[1].wr_stg_inst/Q_reg_reg[*]"}] 16.000}
  {set_max_delay -datapath_only -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_WR/U_WR_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_wrfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.gcx.clkx/*wr_pntr_gc_reg[*]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_WR/U_WR_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_wrfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.gcx.clkx/*gsync_stage[1].rd_stg_inst/Q_reg_reg[*]"}] 50.000}
  {set_bus_skew -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_WR/U_WR_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_wrfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.gcx.clkx/*wr_pntr_gc_reg[*]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_WR/U_WR_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_wrfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.gcx.clkx/*gsync_stage[1].rd_stg_inst/Q_reg_reg[*]"}] 16.000}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/icn_cmd_en_reg[5]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/icn_cmd_en_5_temp_reg"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD1/icn_cmd_en_temp_reg"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD1/ctl_reg_en_1_reg[0]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD2/icn_cmd_en_temp_reg"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD2/stat_reg_ld_reg[0]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD3/icn_cmd_en_temp_reg"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD3/stat_reg_ld_reg[0]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD4/icn_cmd_en_temp_reg"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD4/ctl_reg_en_1_reg[0]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD5/icn_cmd_en_temp_reg"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD5/ctl_reg_en_1_reg[0]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD7_CTL/icn_cmd_en_temp_reg"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD7_CTL/ctl_reg_en_1_reg[0]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD7_CTL/shift_reg_in_reg[*]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD7_CTL/ctl_reg_reg[*]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD7_CTL/shift_reg_in_reg[0]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD7_STAT/stat_reg_reg[0]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD7_STAT/icn_cmd_en_temp_reg"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD7_STAT/stat_reg_ld_reg[0]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/wrdata_rst_reg"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_WR/U_WR_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_wrfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/rstblk/ngwrdrst.grst.g7serrst.rst_rd_reg1_reg"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/wrdata_rst_reg"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_WR/U_WR_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_wrfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/rstblk/ngwrdrst.grst.g7serrst.rst_rd_reg2_reg"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD4/shift_reg_in_reg[*]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD4/ctl_reg_reg[*]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD1/shift_reg_in_reg[*]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD1/ctl_reg_reg[*]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD5/shift_reg_in_reg[*]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD5/ctl_reg_reg[*]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD1/ctl_reg_reg[0]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/ma_rst_1_reg"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD2/stat_reg_reg[*]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD2/stat_reg_1_reg[*]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD3/stat_reg_reg[*]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD3/stat_reg_1_reg[*]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD7_STAT/stat_reg_reg[*]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD7_STAT/stat_reg_1_reg[*]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/rddata_rst_reg"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_RD/U_RD_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_rdfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/rstblk/ngwrdrst.grst.g7serrst.rst_rd_reg1_reg"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/rddata_rst_reg"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_RD/U_RD_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_rdfifo_inst/inst_fifo_gen/gconvfifo.rf/grf.rf/rstblk/ngwrdrst.grst.g7serrst.rst_rd_reg2_reg"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/rddata_rst_reg"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD6_RD/shift_reg_in_reg[*]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD1/ctl_reg_reg[0]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD4/shift_reg_in_reg[*]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD1/ctl_reg_reg[0]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD5/shift_reg_in_reg[*]"}]}
  {set_false_path -from [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD1/ctl_reg_reg[0]"}] -to [get_cells -hierarchical -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD7_CTL/shift_reg_in_reg[*]"}]}
 }
 variable expected_counts {{59 16} {4 4} {4 4} {4 4} {4 4} {59 16} {4 4} {4 4} {4 4} {4 4} {1 1} {1 1} {1 1} {1 1} {1 1} {1 1} {1 1} {3 3} {1 1} {1 1} {1 1} {1 1} {28 28} {2 2} {18 18} {1 1} {4 4} {3 3} {3 3} {1 1} {1 1} {1 16} {1 28} {1 18} {1 3}}
 variable inspected {}
 proc inspect {kind args} {
  variable inspected
  set row {}
  foreach opt {-from -to} {
   set i [lsearch -exact $args $opt]
   if {$i<0} {error "Original hub contract missing $opt"}
   lappend row [llength [lindex $args [expr {$i+1}]]]
  }
  lappend inspected $row
 }
}
proc common_restore_debug_hub_vendor_contract {profile retained_dcp {scope dbg_hub/inst}} {
 if {$profile ne {xsdbm-v3_0_4-original-16ns-system-50ns-user1-tck}} {error {Explicit original hub CDC profile required}}
 package require sha256
 set sha [string tolower [::sha2::sha256 -hex -filename $retained_dcp]]
 if {$sha ne {f88a2ef15c36fc04273d93759d5885c436a86a0e33cbc61c75e12fc713d0d342}} {error {Retained vendor hub DCP hash differs}}
 if {$scope ne {dbg_hub/inst}} {
  if {$scope ne {inst} || [get_property NAME [current_design]] ne {checkpoint_dbg_hub}} {error {Unexpected debug hub contract scope}}
 }
 set saved [current_instance .]
 current_instance
 set cell [get_cells -quiet $scope]
 if {[llength $cell]!=1} {error {Exact vendor hub instance missing}}
 current_instance $scope
 try {
  set tck_cell [get_cells -quiet -hier -filter {NAME =~ "*BSCANID.u_xsdbm_id/SWITCH_N_EXT_BSCAN.bscan_inst/SERIES7_BSCAN.bscan_inst"}]
  if {[llength $tck_cell]!=1 || [get_property REF_NAME $tck_cell] ne {BSCANE2} || [get_property JTAG_CHAIN $tck_cell]!=1} {error {Original unique USER1 BSCANE2 missing}}
  set tck [get_pins -quiet -of_objects $tck_cell -filter {REF_PIN_NAME == INTERNAL_TCK}]
  set hubclk [get_pins -quiet -of_objects [get_cells -quiet -hier -filter {NAME =~ "*BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/U_CMD1/ctl_reg_reg[0]"}] -filter {REF_PIN_NAME == C}]
  if {[llength $hubclk]!=1} {error {Original hub system-clock pin missing}}
  foreach pin [list $tck $hubclk] period {50.0 16.0} {
   set clocks [get_clocks -quiet -of_objects $pin]
   if {[llength $clocks]!=1 || abs([get_property PERIOD $clocks]-$period)>0.001} {error "Hub contract clock period mismatch: $pin requires $period ns"}
  }
  set ::common_debug_hub_contract::inspected {}
  foreach command $::common_debug_hub_contract::commands {
   regexp {^(\S+)} $command -> kind
   set query [string range $command [string length $kind] end]
   eval "::common_debug_hub_contract::inspect $kind $query"
  }
  if {$::common_debug_hub_contract::inspected ne $::common_debug_hub_contract::expected_counts} {error "Original hub contract endpoint cardinalities differ: $::common_debug_hub_contract::inspected"}
  foreach command $::common_debug_hub_contract::commands {eval $command}
  puts {ORIGINAL_VENDOR_HUB_REV4_CDC_RESTORED_27_FALSE_PATH_4_MAX_DELAY_4_BUS_SKEW_NO_CDC_WAIVERS}
 } finally {
  current_instance
  if {$saved ne {}} {current_instance $saved}
 }
}



