# Mock Vivado object API. This proves fail-closed Tcl decisions, not a device DCP.
source [file join [file dirname [info script]] ../../fpga/next/check_jtag_chain.tcl]
set cases 0
proc get_cells {args} {return $::cells}
proc get_debug_cores {args} {return $::hubs}
proc list_property {object} {return [dict keys [dict get $::properties $object]]}
proc get_property {property object} {return [dict get $::properties $object $property]}
proc reset_mock {} {
    set ::cells {loader/user_scan hub/user_scan}
    set ::hubs {dbg_hub}
    set ::properties [dict create loader/user_scan [dict create NAME loader/user_scan JTAG_CHAIN 2] \
        hub/user_scan [dict create NAME hub/user_scan JTAG_CHAIN 1] \
        dbg_hub [dict create C_USER_SCAN_CHAIN 1]]
}
proc expect_fail {script pattern} {
    if {![catch {uplevel 1 $script} message] || ![string match $pattern $message]} {
        error "Expected failure $pattern, got $message"
    }
    incr ::cases
}
reset_mock
if {![valence_assert_jtag_chain 2 loader/user_scan]} {error "valid allocation rejected"};incr cases
expect_fail {valence_assert_jtag_chain 0 loader/user_scan} {*1..4*}
expect_fail {valence_assert_jtag_chain 2 *user_scan*} {*wildcard*}
expect_fail {valence_assert_jtag_chain 2 missing} {*collision*}
expect_fail {valence_assert_jtag_chain 3 loader/user_scan} {*expected USER3*}
dict set properties hub/user_scan JTAG_CHAIN 2
expect_fail {valence_assert_jtag_chain 2 loader/user_scan} {*collision*}
reset_mock;dict set properties dbg_hub C_USER_SCAN_CHAIN 2
expect_fail {valence_assert_jtag_chain 2 loader/user_scan} {*debug hub*}
reset_mock;dict set properties loader/user_scan JTAG_CHAIN unknown
expect_fail {valence_assert_jtag_chain 2 loader/user_scan} {*Unverified*}
reset_mock;dict unset properties loader/user_scan JTAG_CHAIN
expect_fail {valence_assert_jtag_chain 2 loader/user_scan} {*Cannot verify*}
reset_mock;set cells {}
expect_fail {valence_assert_jtag_chain 2 loader/user_scan} {*No BSCANE2*}
reset_mock;dict unset properties dbg_hub C_USER_SCAN_CHAIN
expect_fail {valence_assert_jtag_chain 2 loader/user_scan} {*Cannot verify*}
puts "JTAG_CHAIN_GUARD_PASS cases=$cases mock_only=1"
