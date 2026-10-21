source [file join [file dirname [info script]] common_cdc.tcl]
proc assert {condition text} {if {![uplevel 1 [list expr $condition]]} {error $text}}
set ::clock dst;set ::literal 0;set ::same_ce 1
proc common_cdc::ff {capture clock args} {if {$clock ne $::clock} {error {wrong destination clock}}}
proc common_cdc::constant {pin value} {if {$value!=$::literal} {error {not that constant}}}
proc common_cdc::same_net {a b} {if {!$::same_ce || $a ne {capture/CE} || $b ne {ram_capture/CE}} {error {capture CE differs}}}
assert {[common_cdc::captured_constant capture dst ram_capture]==0} {literal-zero capture rejected}
set ::literal 1
assert {[common_cdc::captured_constant capture dst ram_capture]==1} {literal-one capture rejected}
set ::literal X
assert {[catch {common_cdc::captured_constant capture dst ram_capture}]} {dynamic non-RAM data accepted}
set ::literal 0;set ::same_ce 0
assert {[catch {common_cdc::captured_constant capture dst ram_capture}]} {different capture event accepted}
set ::same_ce 1;set ::clock src
assert {[catch {common_cdc::captured_constant capture dst ram_capture}]} {wrong capture clock accepted}
puts LOCAL_CAPTURE_LITERAL_CLOCK_CE_POSITIVE_NEGATIVE_CONTROLS_PASS
