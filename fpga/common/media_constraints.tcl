# Reuse public semantic proofs; adapt ONLY the instance prefix, no private candidate.
source [file join $valence(root) fpga next native_mac_roles.tcl]
foreach {name expected} {clocks 2 audit 1} {
    set command ::valence_mac_roles::$name
    set body [info body $command]
    if {[regexp -all {u_soc/board/nativeBank/gmac} $body] != $expected} {
        error "Public MAC proof changed; review hierarchy adaptation before use"
    }
    set args {}
    foreach arg [info args $command] {
        if {[info default $command $arg default]} {lappend args [list $arg $default]} else {lappend args $arg}
    }
    proc $command $args [string map {u_soc/board/nativeBank/gmac u_soc/peripherals/gmac} $body]
}
# Exact source wrapper fixes both parameters to zero. The optimized-away control
# equality lemma comes only from the freshly hash-checked complete common encoder/parent form.
# Fresh mapped endpoint and transition proofs remain mandatory.
namespace eval ::valence_native_mac_mode {variable t1 0; variable selected 0; variable control_lemma 0}
if {[info exists valence(control_lemma)] && $valence(control_lemma) == 1} {set ::valence_native_mac_mode::control_lemma 1}
proc valence_native_mac_assert_mode {{hier u_rgmii}} {return [::valence_mac_roles::audit $hier 0 0]}
source [file join $valence(root) fpga zu15eg trispeed_board_constraints.tcl]
# Preserve the complete public clock/reset topology check, changing the old CPU
# clock witness to the actual common fabric source domain (not CPU300/100).
set body [info body valence_trispeed_clock_reset_audit]
if {[regexp -all {u_soc/clock 10.0} $body] != 1} {error "Public media clock audit changed"}
proc valence_trispeed_clock_reset_audit {bank mbps} [string map {{u_soc/clock 10.0} {u_soc/fabricClock 4.0}} $body]
proc common_media_apply {rate} {
    valence_trispeed_rx_constraints $rate
    valence_trispeed_clock_reset_audit u_soc/peripherals/gmac $rate
    valence_trispeed_quarter_tx_constraints u_rgmii $rate 0
}
proc common_media_cdc {} {valence_trispeed_packet_cdc_constraints u_soc/peripherals/gmac}
