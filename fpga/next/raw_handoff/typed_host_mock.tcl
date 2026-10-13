# Host-only graph and opaque-kind mock. No Vivado commands are invoked.
namespace eval mock {variable db {}; variable arcs {}; variable handles {}; variable serial 0; variable api 0; variable reports {}; variable fault {}; variable timing {}; variable paths {}; variable stale {}}
proc mock::handle {kind name} {
    variable handles; variable serial
    set token @H[incr serial]
    dict set handles $token [list $kind $name]
    return $token
}
proc mock::decode {tokens {expected {}}} {
    variable handles; variable api; variable stale; incr api
    if {![llength $tokens]} {error "TYPE: empty collection"}
    set names {}
    foreach token $tokens {
        if {![dict exists $handles $token]} {error "TYPE: untyped/stale object $token"}
        if {[dict exists $stale $token]} {error "TYPE: collection degraded before consumption $token"}
        lassign [dict get $handles $token] kind name
        if {$expected ne "" && $kind ne $expected} {error "TYPE: expected $expected got $kind"}
        lappend names $name
    }
    return $names
}
proc mock::wrap {kind names} {return [lmap name $names {handle $kind $name}]}
proc mock::add {kind name props} {variable db; dict set props NAME $name;dict set db $kind $name $props}
proc mock::cell {name ref {init 0}} {add cell $name [dict create REF_NAME $ref INIT $init IS_SEQUENTIAL [expr {$ref in {FDCE FDPE}}] ASYNC_REG 0 IS_C_INVERTED 0 IS_CLR_INVERTED 0]}
proc mock::pin {cell pin net {dir IN} {leaf 1}} {
    variable db;variable arcs
    add pin $cell/$pin [dict create REF_PIN_NAME $pin CELL $cell DIRECTION $dir IS_LEAF $leaf IS_INVERTED 0]
    dict set arcs $cell/$pin $net
    if {![dict exists $db net $net]} {add net $net [dict create TYPE SIGNAL]}
}
proc mock::ff {cell net data clock reset {fall 0}} {
    variable db;cell $cell FDCE;dict set db cell $cell IS_C_INVERTED $fall
    foreach {p n} [list Q $net D $data CE power C $clock CLR $reset] {pin $cell $p $n [expr {$p eq "Q" ? "OUT" : "IN"}]}
    dict set db pin $cell/C IS_INVERTED $fall
}
proc mock::lut {cell inputs net init} {
    cell $cell LUT[llength $inputs] $init;set i 0
    foreach n $inputs {pin $cell I$i $n;incr i};pin $cell O $net OUT
}
proc mock::query {kind args} {
    variable db;variable arcs;variable query_cache;variable handles
    if {![info exists query_cache]} {set query_cache {}}
    set normalized $args
    set pos [lsearch -exact $args -of_objects]
    if {$pos >= 0} {
        set key_objects {};set tokens [lindex $args [expr {$pos+1}]]
        decode $tokens
        foreach token $tokens {lappend key_objects [dict get $handles $token]}
        set normalized [lreplace $args [expr {$pos+1}] [expr {$pos+1}] $key_objects]
    }
    set cache_key [list $kind $normalized]
    if {[dict exists $query_cache $cache_key]} {return [wrap $kind [dict get $query_cache $cache_key]]}
    set at [lsearch -exact $args -of_objects];set selected {}
    if {$at >= 0} {
        set tokens [lindex $args [expr {$at+1}]]
        foreach token $tokens {
            variable handles
            if {![dict exists $handles $token]} {error "TYPE: -of_objects untyped"}
            lassign [dict get $handles $token] source_kind source
            decode [list $token] $source_kind
            switch -- $kind/$source_kind {
                pin/net {dict for {p n} $arcs {if {$n eq $source} {lappend selected $p}}}
                pin/cell {dict for {p props} [dict get $db pin] {if {[dict get $props CELL] eq $source} {lappend selected $p}}}
                net/pin {lappend selected [dict get $arcs $source]}
                cell/pin {lappend selected [dict get $db pin $source CELL]}
                clock/pin {set n [dict get $arcs $source];if {[dict exists $db net $n CLOCK]} {lappend selected [dict get $db net $n CLOCK]}}
                default {error "TYPE: wrong -of_objects boundary $kind/$source_kind"}
            }
        }
    } else {
        set selected [dict keys [dict get $db $kind]]
        set at [lsearch -exact $args -regexp]
        if {$at >= 0} {set re [lindex $args [expr {$at+1}]];set selected [lmap n $selected {if {![regexp -- $re $n]} {continue};set n}]}
    }
    set at [lsearch -exact $args -filter]
    if {$at >= 0} {
        set filter [lindex $args [expr {$at+1}]]
        if {![regexp {^(DIRECTION|REF_NAME) == (.+)$} $filter -> key value]} {error "unsupported filter"}
        set selected [lmap n $selected {if {[dict get $db $kind $n $key] ne $value} {continue};set n}]
    }
    if {"-leaf" in $args} {set selected [lmap n $selected {if {![dict get $db pin $n IS_LEAF]} {continue};set n}]}
    set selected [lsort -unique $selected]
    dict set query_cache $cache_key $selected
    return [wrap $kind $selected]
}
foreach {command kind} {get_cells cell get_pins pin get_nets net get_clocks clock} {proc ::$command {args} [format {return [mock::query %s {*}$args]} $kind]}
proc get_property {key tokens} {
    variable ::mock::handles;variable ::mock::db;variable ::mock::paths
    if {[dict exists $paths $tokens]} {return [dict get $paths $tokens $key]}
    set result {}
    foreach token $tokens {
        mock::decode [list $token]
        lassign [dict get $handles $token] kind name
        if {![dict exists $db $kind $name $key]} {error "missing mock property: $kind $name $key"}
        lappend result [dict get $db $kind $name $key]
    }
    if {[llength $result] == 1} {return [lindex $result 0]};return $result
}
proc mock::drivers {net} {
    variable arcs;variable db;set result {}
    dict for {p n} $arcs {if {$n eq $net && [dict get $db pin $p DIRECTION] eq "OUT" && [dict get $db pin $p IS_LEAF]} {lappend result $p}}
    return $result
}
proc mock::fanin {pin {seen {}}} {
    variable arcs;variable db
    set n [dict get $arcs $pin]
    if {$n in $seen} {error "mock cone cycle"};lappend seen $n
    if {[dict get $db net $n TYPE] in {POWER GROUND}} {return {}}
    set result {}
    foreach q [drivers $n] {
        set c [dict get $db pin $q CELL]
        if {[dict get $db cell $c IS_SEQUENTIAL]} {lappend result $q;continue}
        dict for {p props} [dict get $db pin] {if {[dict get $props CELL] eq $c && [dict get $props DIRECTION] eq "IN"} {lappend result {*}[fanin $p $seen]}}
    }
    return [lsort -unique $result]
}
proc mock::fanout {pin {seen {}}} {
    variable arcs;variable db
    set n [dict get $arcs $pin]
    if {$n in $seen} {error "mock cone cycle"};lappend seen $n
    set result {}
    dict for {p net} $arcs {
        if {$net ne $n || [dict get $db pin $p DIRECTION] ne "IN" || ![dict get $db pin $p IS_LEAF]} {continue}
        set c [dict get $db pin $p CELL]
        if {[dict get $db cell $c IS_SEQUENTIAL]} {lappend result $p;continue}
        dict for {out props} [dict get $db pin] {if {[dict get $props CELL] eq $c && [dict get $props DIRECTION] eq "OUT"} {lappend result {*}[fanout $out $seen]}}
    }
    return [lsort -unique $result]
}
proc all_fanin {args} {return [mock::wrap pin [mock::fanin [lindex [mock::decode [lindex $args end] pin] 0]]]}
proc all_fanout {args} {return [mock::wrap pin [mock::fanout [lindex [mock::decode [lindex $args end] pin] 0]]]}
proc mock::arg {args flag} {return [lindex $args [expr {[lsearch -exact $args $flag]+1}]]}
proc get_timing_paths {args} {
    variable ::mock::fault;variable ::mock::paths;variable ::mock::serial;variable ::mock::timing
    set from [lindex [mock::decode [mock::arg $args -from] pin] 0]
    set to [lindex [mock::decode [mock::arg $args -to] pin] 0]
    set delay [mock::arg $args -delay_type]
    set q [string range $from 0 end-1]Q
    if {$q ni [mock::fanin $to]} {error "timing pair not connected: $q -> $to"}
    lappend timing [list $from $to $delay]
    if {$fault eq "missing_$delay" || ($fault eq "missing_clr" && [string match */CLR $to])} {return {}}
    set token @PATH[incr serial]
    set slack 0.1
    if {$fault eq "negative"} {set slack -0.1}
    if {$fault eq "nan"} {set slack NaN}
    dict set paths $token [dict create STARTPOINT_PIN [expr {$fault eq "wrong_start" ? $q : $from}] ENDPOINT_PIN [expr {$fault eq "wrong_end" ? "$to.bad" : $to}] REQUIREMENT [expr {$fault eq "relaxed" ? 12.0 : 4.0}] SLACK $slack]
    return $token
}
proc report_timing {args} {
    variable ::mock::reports
    mock::decode [mock::arg $args -from] pin;mock::decode [mock::arg $args -to] pin
    if {[mock::arg $args -path_type] ne "full_clock_expanded" || "-input_pins" ni $args || "-nets" in $args || "-file" ni $args} {error "wrong timing report options"}
    lappend reports $args
}
foreach name {report_exceptions report_clock_interaction report_pulse_width report_timing_summary} {proc $name {args} {if {"-file" ni $args} {error "missing report file"}}}
proc open_checkpoint {path} {return MOCK_OPEN_ONLY}
proc mock::verify_inventory {contract} {
    variable timing;variable reports
    if {![dict get $contract enabled]} {return}
    set r [dict get $contract roles];set expected {}
    set sources [concat [dict get $r ingress_delayed] [dict get $r falling_rx_outputs] [dict get $r managed_rx_outputs] [list [dict get $r tx_step_output]] [dict get $r encoder_phase_and_rate_gap] [dict get $r empty_launches]]
    foreach q [lsort -unique $sources] {
        foreach end [fanout $q] {
            foreach delay {min max} {lappend expected [list [string range $q 0 end-1]C $end $delay]}
        }
    }
    foreach {q cells} [list rawrelease/Q [concat [dict get $r falling_rx_outputs] [list [dict get $r tx_step_output]]] rxrelease/Q [dict get $r managed_rx_outputs]] {
        foreach output $cells {foreach delay {min max} {lappend expected [list [string range $q 0 end-1]C [string range $output 0 end-1]CLR $delay]}}
    }
    set expected [lsort -unique $expected]
    if {[llength $expected] != 150 || [llength $timing] != 150 || [lsort $timing] ne $expected} {error "INVENTORY: exact source/endpoint/min/max set mismatch"}
    set reported {}
    foreach args $reports {
        set from [lindex [decode [arg $args -from] pin] 0];set to [lindex [decode [arg $args -to] pin] 0]
        lappend reported [list $from $to [arg $args -delay_type]]
    }
    if {[lsort $reported] ne $expected} {error "INVENTORY: timing reports differ from queries"}
    puts {EXACT_INVENTORY_PASS 150 min/max pairs including 23 CLR endpoints}
}
foreach name {set_property set_false_path set_multicycle_path set_max_delay set_min_delay create_clock create_generated_clock} {proc $name {args} {error "MUTATION FORBIDDEN"}}
# Trace catches explicit timing-path list/index/dict/string conversion by the
# checker. This is an opaque registry, not a Vivado Tcl_Obj implementation.
proc mock::guard {command arguments} {
    variable stale
    if {![regexp {@(H|PATH)[0-9]+} $arguments]} {return}
    if {[catch {set caller [::mock::base_lindex [info level -2] 0]}]} {return}
    set ns [uplevel 2 {namespace current}]
    if {$ns ne "::raw_handoff" && ![string match raw_handoff::* $caller] && $caller ni {mock_collection_misuse mock_path_misuse}} {return}
    if {$command ne "llength" && [regexp {@PATH[0-9]+} $arguments]} {error "TYPE: serialized timing path"}
    if {$command in {llength lsort lindex}} {
        foreach token [regexp -all -inline {@H[0-9]+} $arguments] {dict set stale $token 1}
    }
}
foreach command {llength lsort lindex list join format} {
    rename ::$command ::mock::base_$command
    proc ::$command {args} [subst -nocommands {mock::guard $command \$args;return [::mock::base_$command {*}\$args]}]
}

proc mock::fixture {mode {merge 0}} {
    variable db;variable arcs
    set root {fresh.mac[0]};cell $root TriSpeedManagedGmac
    add net power [dict create TYPE POWER];add net ground [dict create TYPE GROUND]
    foreach {clock period wave} {refclk 2 {0 1} rawclk 8 {0 4} padclk 4 {0 2}} {add clock $clock [dict create PERIOD $period WAVEFORM $wave]}
    foreach {c ratio net clk} {rawdiv 4 raw rawclk paddiv 2 pad padclk} {
        cell $c BUFGCE_DIV;dict set db cell $c BUFGCE_DIVIDE $ratio
        foreach {p n} [list I ref CE power CLR cold O $net] {pin $c $p $n [expr {$p eq "O" ? "OUT" : "IN"}]}
        dict set db net $net CLOCK $clk
    }
    dict set db net ref CLOCK refclk
    foreach domain {rx tx} {
        cell ${domain}gate BUFGCE;dict set db cell ${domain}gate CE_TYPE SYNC
        foreach {p n} [list I raw CE ${domain}enable O ${domain}clock] {pin ${domain}gate $p $n [expr {$p eq "O" ? "OUT" : "IN"}]}
        dict set db net ${domain}clock CLOCK rawclk
        pin $root ${domain}GateCE ${domain}enable IN 0
    }
    ff rawrelease rawreset ground raw cold;ff rxrelease rxreset ground rxclock cold;ff ingressrelease ingressreset ground raw cold
    foreach {p n} {rawClock raw padClock pad rxClock rxclock txClock txclock rawReset rawreset rxReset rxreset ingressReset ingressreset} {pin $root $p $n IN 0}
    set r [dict create raw_clock $root/rawClock pad_clock $root/padClock rx_clock $root/rxClock tx_clock $root/txClock raw_reset $root/rawReset rx_reset $root/rxReset ingress_reset $root/ingressReset rx_gate_ce $root/rxGateCE tx_gate_ce $root/txGateCE unchanged_properties {{cell rawdiv BUFGCE_DIVIDE 4}}]
    set c [dict create schema raw-handoff-mapped-v1 enabled $mode mac_root $root mac_ref TriSpeedManagedGmac off_raw_clock $root/rawClock]
    if {!$mode} {return $c}
    set inputs {};set fall {};set managed {}
    for {set i 0} {$i < 11} {incr i} {
        set src [format {%s/ingress/input[%d]} $root $i];set f [format {%s/rawHandoff/fall[%d]} $root $i];set m [format {%s/rawHandoff/managed[%d]} $root $i]
        ff $src source$i ground raw ingressreset;ff $f falling$i source$i raw rawreset 1;ff $m managed$i falling$i rxclock rxreset
        lappend inputs $src/Q;lappend fall $f/Q;lappend managed $m/Q
        ff $root/rx/consumer$i consumer$i managed$i rxclock rxreset
    }
    set decode {};set decode_nets {}
    for {set i 0} {$i < 11} {incr i} {set name [format {%s/encode/state[%d]} $root $i];ff $name decode$i ground raw rawreset;lappend decode $name/Q;lappend decode_nets decode$i}
    lut $root/encode/zero_a [lrange $decode_nets 0 5] za 64'h1;lut $root/encode/zero_b [lrange $decode_nets 6 10] zb 32'h1;lut $root/encode/and {za zb} bytestep 4'h8
    set tx $root/rawHandoff/tx;ff $tx txstep bytestep raw rawreset 1
    foreach name {tx stats ack} {ff $root/tx/$name q_$name txstep txclock rawreset}
    ff $root/activity0 active ground raw ingressreset
    if {$merge} {set activity source9;set tail [lindex $inputs 9]} else {ff $root/activity127 activity ground raw ingressreset;set activity activity;set tail $root/activity127/Q}
    lut $root/empty [list active $activity] empty 4'h1
    pin $root ingressEmpty empty IN 0
    ff $root/ingressEmptySource emptysource empty raw rawreset
    set idle_inputs {};set idle_nets {}
    for {set i 0} {$i < 8} {incr i} {
        if {$i == 5} {set pin $root/ingressEmpty;set n empty} elseif {$i == 6} {set pin [lindex $managed 9];set n managed9} else {ff $root/idle$i idle$i ground rxclock rxreset;set pin $root/idle$i/Q;set n idle$i}
        lappend idle_inputs $pin;lappend idle_nets $n
    }
    lut $root/idle_a [lrange $idle_nets 0 5] idle_a 64'h200000000000
    lut $root/idle_b [lrange $idle_nets 6 7] idle_b 4'h4
    lut $root/idle_and {idle_a idle_b} localidle 4'h8
    pin $root localIdle localidle IN 0;ff $root/rx/ack rxack localidle rxclock rxreset
    dict set r ingress_delayed $inputs;dict set r falling_rx_outputs $fall;dict set r managed_rx_outputs $managed
    dict set r tx_step_output $tx/Q;dict set r encoder_phase_and_rate_gap $decode;dict set r rx_pending [lindex $managed 9]
    dict set r local_idle_inputs $idle_inputs;dict set r local_idle_output $root/localIdle
    dict set r ingress_empty $root/ingressEmpty;dict set r ingress_empty_source_d $root/ingressEmptySource/D
    dict set r empty_launches [fanin $root/ingressEmpty];dict set r reviewed_valid_activity_merge $merge;dict set r ingress_activity_tail $tail
    set ingress_fanouts {};foreach p $inputs {lappend ingress_fanouts [fanout $p]};dict set r ingress_source_fanouts $ingress_fanouts
    set fanouts {};for {set i 0} {$i < 11} {incr i} {dict set fanouts rx_$i [fanout [lindex $managed $i]]}
    dict set fanouts tx [fanout $tx/Q];dict set fanouts empty [fanout $root/ingressEmpty];dict set r fanouts $fanouts
    dict set c roles $r;return $c
}
