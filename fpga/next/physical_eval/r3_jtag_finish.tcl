# Read-only final allocation gate after optimization has generated the Debug Hub.
source [file join $root export board check_jtag_chain.tcl]
valence_assert_jtag_chain 2 $V_BSCAN_PRIMITIVE
set jtagFile [open jtag-inventory.txt w]
foreach cell [get_cells -quiet -hier -filter {REF_NAME == BSCANE2}] {
    puts $jtagFile "BSCANE2 [get_property NAME $cell] USER[valence_jtag_integer_property $cell {JTAG_CHAIN CONFIG.JTAG_CHAIN}]"
}
foreach hub [get_debug_cores -quiet *dbg_hub*] {
    puts $jtagFile "DEBUG_HUB $hub USER[valence_jtag_integer_property $hub {C_USER_SCAN_CHAIN CONFIG.C_USER_SCAN_CHAIN}]"
}
puts $jtagFile "PASS_EXACT_USER2_OWNER $V_BSCAN_PRIMITIVE NO_CHAIN_COLLISION"
close $jtagFile
valence_native_mac_assert_mode $V_RGMII_ROOT
set macFile [open mac-raw-handoff-final.txt w]
puts $macFile [valence_mac_roles::audit $V_RGMII_ROOT 1 1 1]
close $macFile
