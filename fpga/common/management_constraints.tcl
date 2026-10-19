# Reviewed subset of public native_board_constraints.tcl, adapted to the common
# bank only. Never source its old RX-MMCM/clock-rewiring/zero-budget recipe.
# common_cdc helpers and public native-gmac-cdc-constraints are already loaded.
proc common_management_constraints {} {
    set bank u_soc/peripherals
    foreach bridge {cmu/bridge uart/bridge} {
        valence_register_cdc_constraints $bank/$bridge 4.0
    }
    foreach c [get_cells -quiet -hier -filter "REF_NAME =~ CdcLevel* && NAME =~ $bank/*"] {
        set h [get_property NAME $c]
        if {$h eq "$bank/gmac/mdio_io_mdioIn_sync"} {continue}
        set pins [get_pins -quiet -of_objects $c -filter {REF_PIN_NAME == levelIn}]
        if {[llength $pins]!=1} {error "Missing actual management scalar input $h"}
        # A tied-off level has no asynchronous data transition to constrain.
        if {![catch {common_cdc::constant $h/levelIn 0}] || ![catch {common_cdc::constant $h/levelIn 1}]} {continue}
        set scope [common_cdc::level $h]
        set_max_delay -datapath_only [dict get $scope budget] \
            -from [common_cdc::objects get_pins [dict get $scope starts]] \
            -to [common_cdc::objects get_pins [dict get $scope ends]]
    }
    foreach {port pin budget} [list uart_rxd $bank/uart/sampledRx_meta_reg/D 20.0 \
                                   eth_mdio "$bank/gmac/mdio_io_mdioIn_sync/stages_reg\[0\]/D" 10.0] {
        set endpoint [common_cdc::one get_pins $pin]
        set pad [get_ports -quiet $port]
        if {[llength $pad]!=1} {error "Missing management input pad $port"}
        set_max_delay -datapath_only $budget -from $pad -to $endpoint
    }
    set uart [get_clocks -quiet -of_objects [get_pins -quiet $bank/uart/uart/clock]]
    if {[llength $uart]!=1 || abs([get_property PERIOD $uart]-20.0)>0.002} {error "Wrong actual UART50 clock"}
    # Public asynchronous serial connector budget; not a synchronous CPU port.
    set_output_delay -clock $uart -max 10.0 [get_ports uart_txd]
    set_output_delay -clock $uart -min 0.0 [get_ports uart_txd]
    # Clause22 <=2.5MHz; bound each physical leg to20ns, preserving >=160ns
    # differential margin for PHY10ns setup/hold. LED/reset are async status.
    foreach port {eth_mdc eth_mdio led eth_reset_gate} {
        set endpoint [get_ports -quiet $port]
        if {[llength $endpoint]!=1} {error "Missing management output $port"}
        set starts [filter [all_fanin -flat -startpoints_only -to $endpoint] {REF_PIN_NAME == C || REF_PIN_NAME == CLK}]
        if {![llength $starts]} {error "Unregistered management output $port"}
        set_max_delay -datapath_only 20.0 -from $starts -to $endpoint
    }
    # Async assertion only at proved three-stage reset synchronizer PRE pins.
    # D->Q and every downstream functional reset recovery/removal remain timed.
    set chains {ui_reset_pipe_reg delay_reset_pipe_reg phy_reset_pipe_reg rx_reset_pipe_reg network_clock/phase_reset_reg}
    foreach c [get_cells -quiet -hier -filter {REF_NAME =~ CdcResetRelease*}] {
        set name [get_property NAME $c]
        if {[string first u_soc/ $name]==0} {lappend chains $name/release_0_reg}
    }
    foreach prefix $chains {
        set stages [common_cdc::bank $prefix 3]
        set clock [common_cdc::clock [lindex $stages 0]/C]
        set first [lindex $stages 0]
        common_cdc::constant $first/D 0
        foreach c $stages {
            common_cdc::ff $c $clock 1
            if {[get_property REF_NAME [common_cdc::one get_cells $c]] ne "FDPE"} {error "Reset release must asynchronously set $c"}
            common_cdc::same_net $c/PRE $first/PRE
        }
        for {set i 1} {$i<3} {incr i} {
            set a [lindex $stages [expr {$i-1}]];set b [lindex $stages $i]
            set loads [list $b/D]
            if {$prefix eq "network_clock/phase_reset_reg" && $i==2} {
                # Public divider reset epoch intentionally releases both DIVs
                # at stage1; stage2 controls lock publication only.
                lappend loads network_clock/raw_div/CLR network_clock/quarter_div/CLR
            }
            if {[common_cdc::drivers $b/D] ne [list $a/Q] || [common_cdc::loads $a/Q] ne [lsort $loads]} {error "Reset release has unreviewed intermediate fanout $prefix"}
        }
        set_false_path -to [common_cdc::objects get_pins [lmap c $stages {string cat $c /PRE}]]
    }
    puts "COMMON_MANAGEMENT_BOUNDED scoped_reset_assertion_only functional_recovery_removal_timed"
}
